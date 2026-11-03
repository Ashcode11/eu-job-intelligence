"""Central orchestrator: the LangGraph workflow that ties all agents together.

    discover → select → embed → match → visa → salary → rank → notify

- The database is the source of truth; graph state carries ids, flags and counters.
- Every node writes one `agent_executions` row (shared `workflow_run_id`).
- Work is skipped when an analysis' input hash is unchanged, so repeated runs make no
  repeated LLM calls. `force=True` (manual reprocessing) bypasses the hashes.
- One bad job never fails a node: it is counted in `items_failed` and the decision log.
- Transient database errors are retried per node by LangGraph's RetryPolicy.
"""

import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from agents.discovery.service import DiscoveryService
from agents.llm.ollama import LLMUnavailable, OllamaClient
from agents.matching import scorer
from agents.salary_intelligence import analyzer as salary
from agents.skills import canonical, extract_skills
from agents.visa_intelligence import analyzer as visa
from common.enums import (
    ExecutionStatus,
    JobStatus,
    NotificationChannel,
    NotificationKind,
    VisaClassification,
)
from common.logging import get_logger
from database.models import (
    AgentExecution,
    Candidate,
    Job,
    JobMatch,
    Notification,
    SalaryAssessment,
    VisaAssessment,
)

log = get_logger(__name__)

MAX_JOBS_PER_RUN = 500
HIGH_MATCH = 75.0
_DB_RETRY = RetryPolicy(
    max_attempts=3,
    initial_interval=1.0,
    retry_on=lambda e: isinstance(e, OperationalError | DBAPIError),
)


class PipelineState(TypedDict, total=False):
    workflow_run_id: str
    trigger: str
    search_config_id: str | None
    job_ids: list[str] | None  # explicit reprocessing
    force: bool
    candidate_id: str
    discovered: int
    selected: list[str]
    llm_available: bool
    counters: dict[str, dict[str, int]]
    high_matches: list[str]
    new_sponsorship: list[str]


class Pipeline:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        llm: OllamaClient | None = None,
        discovery: DiscoveryService | None = None,
    ) -> None:
        self.sf = session_factory
        self.llm = llm
        self.discovery = discovery or DiscoveryService(session_factory)
        self.graph = self._build()

    # ------------------------------------------------------------------ graph
    def _build(self):
        g = StateGraph(PipelineState)
        for name, fn in (
            ("discover", self.discover),
            ("select", self.select),
            ("embed", self.embed),
            ("match", self.match),
            ("visa", self.visa),
            ("salary", self.salary),
            ("rank", self.rank),
            ("notify", self.notify),
        ):
            g.add_node(name, fn, retry_policy=_DB_RETRY)
        g.add_edge(START, "discover")
        g.add_edge("discover", "select")
        g.add_conditional_edges("select", lambda s: "embed" if s.get("selected") else END)
        for a, b in (
            ("embed", "match"),
            ("match", "visa"),
            ("visa", "salary"),
            ("salary", "rank"),
            ("rank", "notify"),
            ("notify", END),
        ):
            g.add_edge(a, b)
        return g.compile()

    async def run(
        self,
        *,
        search_config_id: uuid.UUID | None = None,
        job_ids: list[uuid.UUID] | None = None,
        force: bool = False,
        trigger: str = "manual",
    ) -> PipelineState:
        run_id = uuid.uuid4()
        t0, started = time.perf_counter(), datetime.now(UTC)
        async with self.sf() as s:
            ex = AgentExecution(
                agent_name="orchestrator",
                trigger=trigger,
                workflow_run_id=run_id,
                status=ExecutionStatus.RUNNING,
                started_at=started,
                details={
                    "search_config_id": str(search_config_id or ""),
                    "job_ids": [str(j) for j in job_ids or []],
                    "force": force,
                },
            )
            s.add(ex)
            await s.commit()
            ex_id = ex.id
        state: PipelineState = {
            "workflow_run_id": str(run_id),
            "trigger": trigger,
            "search_config_id": str(search_config_id) if search_config_id else None,
            "job_ids": [str(j) for j in job_ids] if job_ids else None,
            "force": force,
            "counters": {},
        }
        error: Exception | None = None
        try:
            state = await self.graph.ainvoke(state)
        except Exception as exc:  # recorded below, then re-raised for the task layer
            error = exc
            log.exception("pipeline_failed", workflow_run_id=str(run_id))
        async with self.sf() as s:
            ex = await s.get(AgentExecution, ex_id)
            ex.status = ExecutionStatus.FAILED if error else ExecutionStatus.SUCCEEDED
            ex.finished_at = datetime.now(UTC)
            ex.duration_ms = int((time.perf_counter() - t0) * 1000)
            ex.items_processed = len(state.get("selected") or [])
            ex.items_created = state.get("discovered", 0)
            if error:
                ex.error_type, ex.error_message = type(error).__name__, str(error)[:1000]
            if self.llm:
                u = self.llm.usage
                ex.llm_model, ex.llm_calls = self.llm.chat_model, u.calls
                ex.llm_prompt_tokens, ex.llm_completion_tokens = (
                    u.prompt_tokens,
                    u.completion_tokens,
                )
            ex.details = {
                **ex.details,
                "counters": state.get("counters", {}),
                "high_matches": len(state.get("high_matches") or []),
                "llm_available": state.get("llm_available"),
            }
            await s.commit()
        if error:
            raise error
        return state

    # ------------------------------------------------------------------ helpers
    async def _node(
        self,
        state: PipelineState,
        agent: str,
        body: Callable[[AsyncSession, AgentExecution, dict[str, int]], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        counters = {"processed": 0, "created": 0, "skipped": 0, "failed": 0}
        usage_before = (
            (self.llm.usage.calls, self.llm.usage.prompt_tokens, self.llm.usage.completion_tokens)
            if self.llm
            else (0, 0, 0)
        )
        async with self.sf() as s:
            ex = AgentExecution(
                agent_name=agent,
                trigger=state["trigger"],
                workflow_run_id=uuid.UUID(state["workflow_run_id"]),
                status=ExecutionStatus.RUNNING,
                started_at=datetime.now(UTC),
                decisions=[],
            )
            s.add(ex)
            await s.flush()
            try:
                update = await body(s, ex, counters)
                ex.status = ExecutionStatus.SUCCEEDED
            except Exception as exc:
                await s.rollback()
                ex = AgentExecution(
                    agent_name=agent,
                    trigger=state["trigger"],
                    workflow_run_id=uuid.UUID(state["workflow_run_id"]),
                    status=ExecutionStatus.FAILED,
                    started_at=datetime.now(UTC),
                    error_type=type(exc).__name__,
                    error_message=str(exc)[:1000],
                )
                s.add(ex)
                await s.commit()
                raise
            ex.finished_at = datetime.now(UTC)
            ex.duration_ms = int((time.perf_counter() - t0) * 1000)
            ex.items_processed, ex.items_created = counters["processed"], counters["created"]
            ex.items_failed = counters["failed"]
            ex.details = {**(ex.details or {}), "skipped": counters["skipped"]}
            if self.llm:
                u = self.llm.usage
                calls = u.calls - usage_before[0]
                if calls:
                    ex.llm_model, ex.llm_calls = self.llm.chat_model, calls
                    ex.llm_prompt_tokens = u.prompt_tokens - usage_before[1]
                    ex.llm_completion_tokens = u.completion_tokens - usage_before[2]
            ex.decisions = (ex.decisions or [])[:200]
            await s.commit()
        all_counters = dict(state.get("counters") or {})
        all_counters[agent] = counters
        return {**update, "counters": all_counters}

    async def _jobs(self, s: AsyncSession, ids: list[str]) -> list[Job]:
        return list(
            await s.scalars(
                select(Job)
                .where(Job.id.in_([uuid.UUID(i) for i in ids]))
                .options(
                    selectinload(Job.company),
                    selectinload(Job.visa_assessment),
                    selectinload(Job.salary_assessment),
                )
            )
        )

    # ------------------------------------------------------------------ nodes
    async def discover(self, state: PipelineState) -> dict[str, Any]:
        if not state.get("search_config_id"):
            return {"discovered": 0}
        result = await self.discovery.run(
            uuid.UUID(state["search_config_id"]),
            trigger=state["trigger"],
            workflow_run_id=uuid.UUID(state["workflow_run_id"]),
        )
        counters = dict(state.get("counters") or {})
        counters["discovery"] = {
            "processed": sum(s.fetched for s in result.per_source.values()),
            "created": result.created,
            "skipped": 0,
            "failed": sum(1 for s in result.per_source.values() if s.error),
        }
        return {"discovered": result.created, "counters": counters}

    async def select(self, state: PipelineState) -> dict[str, Any]:
        """Pick jobs whose analyses are missing or stale (input hash changed)."""

        async def body(s: AsyncSession, ex: AgentExecution, c: dict[str, int]):
            cand = await s.scalar(
                select(Candidate)
                .options(selectinload(Candidate.skills))
                .order_by(Candidate.created_at)
                .limit(1)
            )
            if cand is None:
                ex.decisions = [{"decision": "skip", "reason": "no candidate profile"}]
                return {"selected": []}
            stmt = (
                select(Job)
                .where(Job.status == JobStatus.ACTIVE, Job.canonical_job_id.is_(None))
                .options(
                    selectinload(Job.company),
                    selectinload(Job.visa_assessment),
                    selectinload(Job.salary_assessment),
                )
                .order_by(Job.discovered_at.desc())
                .limit(MAX_JOBS_PER_RUN)
            )
            if state.get("job_ids"):
                stmt = (
                    select(Job)
                    .where(Job.id.in_([uuid.UUID(j) for j in state["job_ids"]]))
                    .options(
                        selectinload(Job.company),
                        selectinload(Job.visa_assessment),
                        selectinload(Job.salary_assessment),
                    )
                )
            jobs = list(await s.scalars(stmt))
            matches = {
                m.job_id: m
                for m in await s.scalars(select(JobMatch).where(JobMatch.candidate_id == cand.id))
            }
            cfacts = candidate_facts(cand)
            selected = []
            for job in jobs:
                c["processed"] += 1
                if state.get("force") or _stale(job, cand, cfacts, matches.get(job.id)):
                    selected.append(str(job.id))
                else:
                    c["skipped"] += 1
            ex.decisions = [
                {"decision": "selected", "count": len(selected)},
                {"decision": "unchanged", "count": c["skipped"]},
            ]
            return {"selected": selected, "candidate_id": str(cand.id)}

        return await self._node(state, "selection", body)

    async def embed(self, state: PipelineState) -> dict[str, Any]:
        async def body(s: AsyncSession, ex: AgentExecution, c: dict[str, int]):
            if not self.llm or not await self.llm.available():
                ex.decisions = [
                    {
                        "decision": "skip",
                        "reason": "Ollama unavailable; scoring "
                        "uses deterministic skill coverage instead",
                    }
                ]
                return {"llm_available": False}
            cand = await s.get(
                Candidate,
                uuid.UUID(state["candidate_id"]),
                options=[selectinload(Candidate.skills), selectinload(Candidate.experiences)],
            )
            try:
                cand.profile_embedding = (await self.llm.embed([profile_text(cand)]))[0]
                todo = [j for j in await self._jobs(s, state["selected"]) if j.embedding is None]
                for batch in (todo[i : i + 16] for i in range(0, len(todo), 16)):
                    vectors = await self.llm.embed(
                        [f"{j.title}\n{j.description[:6000]}" for j in batch]
                    )
                    for job, vec in zip(batch, vectors, strict=True):
                        job.embedding = vec
                        c["created"] += 1
                c["processed"] = len(todo)
            except LLMUnavailable as exc:
                ex.decisions = [{"decision": "skip", "reason": str(exc)[:300]}]
                return {"llm_available": False}
            return {"llm_available": True}

        return await self._node(state, "embedding", body)

    async def match(self, state: PipelineState) -> dict[str, Any]:
        """Extract the skills each job asks for (used by matching and CV gap analysis)."""

        async def body(s: AsyncSession, ex: AgentExecution, c: dict[str, int]):
            for job in await self._jobs(s, state["selected"]):
                c["processed"] += 1
                try:
                    skills = sorted(extract_skills(f"{job.title}\n{job.description}"))
                    merged = sorted({canonical(x) for x in [*job.required_skills, *skills]})
                    if merged != sorted(job.required_skills):
                        job.required_skills = merged
                        c["created"] += 1
                except Exception as exc:
                    c["failed"] += 1
                    ex.decisions.append(
                        {"job_id": str(job.id), "decision": "error", "reason": str(exc)[:200]}
                    )
            return {}

        return await self._node(state, "matching", body)

    async def visa(self, state: PipelineState) -> dict[str, Any]:
        async def body(s: AsyncSession, ex: AgentExecution, c: dict[str, int]):
            newly_explicit: list[str] = []
            use_llm = bool(state.get("llm_available") and self.llm)
            for job in await self._jobs(s, state["selected"]):
                c["processed"] += 1
                try:
                    company = job.company
                    documented = company.documented_sponsor if company else None
                    expected = visa.input_hash(job.content_hash, documented)
                    current = job.visa_assessment
                    if current and current.input_hash == expected and not state.get("force"):
                        c["skipped"] += 1
                        continue
                    r = visa.classify(
                        job.description,
                        job_url=job.url,
                        country=job.country,
                        content_hash=job.content_hash,
                        documented_sponsor=documented,
                        documented_sponsor_evidence=(
                            company.sponsorship_evidence if company else None
                        ),
                    )
                    if use_llm:
                        r = await visa.refine_with_llm(r, job.description, self.llm)
                    was = current.classification if current else None
                    _upsert(
                        s,
                        VisaAssessment,
                        job.id,
                        current,
                        dict(
                            classification=r.classification,
                            mentions_sponsorship=r.mentions_sponsorship,
                            relocation_support=r.relocation_support,
                            non_eu_applicants_accepted=r.non_eu_applicants_accepted,
                            eu_authorization_required=r.eu_authorization_required,
                            employer_documented_sponsor=r.employer_documented_sponsor,
                            evidence=r.evidence,
                            country_pathways=r.country_pathways,
                            confidence=r.confidence,
                            rationale=r.rationale,
                            method=r.method,
                            analyzer_version=visa.ANALYZER_VERSION,
                            input_hash=r.input_hash,
                            llm_model=r.llm_model,
                        ),
                    )
                    c["created"] += 1
                    if (
                        r.classification == VisaClassification.EXPLICIT_SPONSORSHIP
                        and was != VisaClassification.EXPLICIT_SPONSORSHIP
                    ):
                        newly_explicit.append(str(job.id))
                    ex.decisions.append(
                        {
                            "job_id": str(job.id),
                            "decision": r.classification.value,
                            "method": r.method,
                            "evidence": [e["signal"] for e in r.evidence],
                        }
                    )
                except Exception as exc:
                    c["failed"] += 1
                    ex.decisions.append(
                        {"job_id": str(job.id), "decision": "error", "reason": str(exc)[:200]}
                    )
            return {"new_sponsorship": newly_explicit}

        return await self._node(state, "visa", body)

    async def salary(self, state: PipelineState) -> dict[str, Any]:
        async def body(s: AsyncSession, ex: AgentExecution, c: dict[str, int]):
            cand = await s.get(Candidate, uuid.UUID(state["candidate_id"]))
            for job in await self._jobs(s, state["selected"]):
                c["processed"] += 1
                try:
                    r = salary.analyse(
                        country=job.country,
                        city=job.city,
                        seniority=job.seniority,
                        salary_min=_f(job.salary_min),
                        salary_max=_f(job.salary_max),
                        salary_currency=job.salary_currency,
                        salary_period=job.salary_period,
                        salary_raw=job.salary_raw,
                        candidate_min_salary_eur=cand.min_salary_eur,
                    )
                    current = job.salary_assessment
                    if current and current.input_hash == r.input_hash and not state.get("force"):
                        c["skipped"] += 1
                        continue
                    values = {
                        k: getattr(r, k)
                        for k in (
                            "has_actual_salary",
                            "actual_min_eur",
                            "actual_max_eur",
                            "source_currency",
                            "fx_rate_to_eur",
                            "estimated_min_eur",
                            "estimated_max_eur",
                            "benchmark_median_eur",
                            "benchmark_source",
                            "est_net_annual_eur",
                            "est_living_cost_annual_eur",
                            "est_savings_annual_eur",
                            "meets_candidate_minimum",
                            "assumptions",
                            "input_hash",
                        )
                    }
                    _upsert(
                        s,
                        SalaryAssessment,
                        job.id,
                        current,
                        {**values, "analyzer_version": salary.ANALYZER_VERSION},
                    )
                    c["created"] += 1
                except Exception as exc:
                    c["failed"] += 1
                    ex.decisions.append(
                        {"job_id": str(job.id), "decision": "error", "reason": str(exc)[:200]}
                    )
            return {}

        return await self._node(state, "salary", body)

    async def rank(self, state: PipelineState) -> dict[str, Any]:
        """Combine everything into the final score and persist JobMatch rows."""

        async def body(s: AsyncSession, ex: AgentExecution, c: dict[str, int]):
            cand = await s.get(
                Candidate,
                uuid.UUID(state["candidate_id"]),
                options=[selectinload(Candidate.skills), selectinload(Candidate.resumes)],
            )
            cfacts = candidate_facts(cand)
            primary = next((r for r in cand.resumes if r.is_primary), None)
            existing = {
                m.job_id: m
                for m in await s.scalars(select(JobMatch).where(JobMatch.candidate_id == cand.id))
            }
            high: list[str] = []
            await s.flush()
            for job in await self._jobs(s, state["selected"]):
                c["processed"] += 1
                try:
                    res = scorer.score(cfacts, job_facts(job), visa_facts(job), salary_facts(job))
                    m = existing.get(job.id)
                    if m and m.input_hash == res.input_hash and not state.get("force"):
                        c["skipped"] += 1
                        continue
                    values = dict(
                        overall_score=res.overall_score,
                        component_scores=res.component_scores,
                        weights_used=res.weights_used,
                        semantic_similarity=res.semantic_similarity,
                        matched_skills=res.matched_skills,
                        missing_skills=res.missing_skills[:50],
                        experience_gaps=res.experience_gaps,
                        reasons_for=res.reasons_for,
                        reasons_against=res.reasons_against,
                        recommended=res.recommended,
                        interview_likelihood=res.interview_likelihood,
                        scorer_version=scorer.SCORER_VERSION,
                        input_hash=res.input_hash,
                        resume_id=primary.id if primary else None,
                        llm_model=None,
                    )
                    if m is None:
                        s.add(JobMatch(job_id=job.id, candidate_id=cand.id, **values))
                    else:
                        for k, v in values.items():
                            setattr(m, k, v)
                    c["created"] += 1
                    if res.recommended and res.overall_score >= HIGH_MATCH:
                        high.append(str(job.id))
                    ex.decisions.append(
                        {
                            "job_id": str(job.id),
                            "score": res.overall_score,
                            "recommended": res.recommended,
                        }
                    )
                except Exception as exc:
                    c["failed"] += 1
                    ex.decisions.append(
                        {"job_id": str(job.id), "decision": "error", "reason": str(exc)[:200]}
                    )
            return {"high_matches": high}

        return await self._node(state, "ranking", body)

    async def notify(self, state: PipelineState) -> dict[str, Any]:
        """Dashboard notifications. Dedup keys make every alert fire at most once."""

        async def body(s: AsyncSession, ex: AgentExecution, c: dict[str, int]):
            cand_id = uuid.UUID(state["candidate_id"])
            rows = []
            for job in await self._jobs(
                s, list({*state.get("high_matches", []), *state.get("new_sponsorship", [])})
            ):
                company = job.company.name if job.company else "Unknown company"
                if str(job.id) in state.get("high_matches", []):
                    rows.append(
                        dict(
                            kind=NotificationKind.HIGH_MATCH,
                            title=f"High match: {job.title}",
                            body=f"{company} · {job.country or 'Europe'} · {job.url}",
                            job_id=job.id,
                            dedup_key=f"high_match:{job.id}:dashboard",
                        )
                    )
                if str(job.id) in state.get("new_sponsorship", []):
                    rows.append(
                        dict(
                            kind=NotificationKind.VISA_SPONSORSHIP,
                            title=f"Visa sponsorship offered: {job.title}",
                            body=f"{company} · {job.country or 'Europe'} · {job.url}",
                            job_id=job.id,
                            dedup_key=f"visa:{job.id}:dashboard",
                        )
                    )
            if state.get("discovered"):
                rows.append(
                    dict(
                        kind=NotificationKind.NEW_JOBS,
                        title=f"{state['discovered']} new jobs discovered",
                        body="Open the job explorer to review them.",
                        job_id=None,
                        dedup_key=f"new_jobs:{state['workflow_run_id']}:dashboard",
                    )
                )
            for row in rows:
                result = await s.execute(
                    pg_insert(Notification)
                    .values(
                        id=uuid.uuid4(),
                        candidate_id=cand_id,
                        channel=NotificationChannel.DASHBOARD,
                        **row,
                    )
                    .on_conflict_do_nothing(index_elements=["dedup_key"])
                )
                c["processed"] += 1
                c["created"] += result.rowcount or 0
            return {}

        return await self._node(state, "notifications", body)


# ---------------------------------------------------------------------- mappers
def candidate_facts(cand: Candidate) -> scorer.CandidateFacts:
    return scorer.CandidateFacts(
        years_experience=_f(cand.years_experience),
        skills={canonical(s.name): s.proficiency for s in cand.skills},
        target_roles=list(cand.target_roles or []),
        preferred_countries=list(cand.preferred_countries or []),
        current_country=cand.current_country,
        open_to_relocation=cand.open_to_relocation,
        requires_visa_sponsorship=cand.requires_visa_sponsorship,
        has_eu_work_authorization=cand.has_eu_work_authorization,
        min_salary_eur=cand.min_salary_eur,
        designation=cand.current_designation,
        weights=dict(cand.match_weights or {}),
        embedding=list(cand.profile_embedding) if cand.profile_embedding is not None else None,
    )


def job_facts(job: Job) -> scorer.JobFacts:
    return scorer.JobFacts(
        title=job.title,
        description=job.description,
        required_skills=list(job.required_skills),
        experience_min_years=_f(job.experience_min_years),
        seniority=job.seniority,
        country=job.country,
        remote_type=job.remote_type,
        content_hash=job.content_hash,
        embedding=list(job.embedding) if job.embedding is not None else None,
    )


def visa_facts(job: Job) -> scorer.VisaFacts:
    v = job.visa_assessment
    if v is None:
        return scorer.VisaFacts(classification=None)
    return scorer.VisaFacts(
        classification=v.classification,
        local_language_required=any(
            e.get("signal") == "local_language_required" for e in v.evidence or []
        ),
        input_hash=v.input_hash,
    )


def salary_facts(job: Job) -> scorer.SalaryFacts:
    a = job.salary_assessment
    if a is None:
        return scorer.SalaryFacts(False, None, None)
    return scorer.SalaryFacts(
        a.has_actual_salary, _f(a.actual_max_eur), _f(a.estimated_max_eur), a.input_hash
    )


def profile_text(cand: Candidate) -> str:
    skills = ", ".join(s.name for s in cand.skills)
    exp = "\n".join(
        f"{e.title} at {e.organization}: {e.description or ''}" for e in cand.experiences
    )
    return (
        f"{cand.current_designation or ''}. {cand.summary or ''}\n"
        f"Target roles: {', '.join(cand.target_roles or [])}\nSkills: {skills}\n{exp}"
    )


def _stale(job: Job, cand: Candidate, cfacts: scorer.CandidateFacts, m: JobMatch | None) -> bool:
    if job.visa_assessment is None or job.salary_assessment is None or m is None:
        return True
    documented = job.company.documented_sponsor if job.company else None
    if job.visa_assessment.input_hash != visa.input_hash(job.content_hash, documented):
        return True
    expected_salary = salary.analyse(
        country=job.country,
        city=job.city,
        seniority=job.seniority,
        salary_min=_f(job.salary_min),
        salary_max=_f(job.salary_max),
        salary_currency=job.salary_currency,
        salary_period=job.salary_period,
        salary_raw=job.salary_raw,
        candidate_min_salary_eur=cand.min_salary_eur,
    ).input_hash
    if job.salary_assessment.input_hash != expected_salary:
        return True
    expected = scorer.input_hash(cfacts, job_facts(job), visa_facts(job), salary_facts(job))
    return m.input_hash != expected


def _upsert(s: AsyncSession, model, job_id: uuid.UUID, current, values: dict) -> None:
    if current is None:
        s.add(model(job_id=job_id, **values))
    else:
        for k, v in values.items():
            setattr(current, k, v)


def _f(v) -> float | None:
    return float(v) if v is not None else None
