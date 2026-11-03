"""Job Discovery Agent: fetch → normalize → filter → deduplicate → persist → close/expire.

Deterministic by design (no LLM). Every run writes one `agent_executions` row with
per-source counts and a capped decision log.
"""

import time
import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from common.config import get_settings
from common.enums import ExecutionStatus, JobStatus
from common.logging import get_logger
from connectors.base import Connector, RawJob, SearchQuery
from connectors.http import PoliteClient, RobotsDisallowed
from connectors.location import ParsedLocation, parse_location
from connectors.normalize import content_hash, dedup_hash, normalize_company_name, normalize_title
from connectors.registry import get_connector_class
from connectors.text import extract_min_years, title_matches
from database.models import AgentExecution, Candidate, Company, Job, JobSource, SearchConfiguration

log = get_logger(__name__)

AGENT_NAME = "discovery"
MAX_DECISIONS = 200
SENIORITY_WORDS = [
    ("principal", "principal"),
    ("head of", "head"),
    ("director", "director"),
    ("lead", "lead"),
    ("staff", "staff"),
    ("manager", "manager"),
    ("senior", "senior"),
    ("junior", "junior"),
]

ConnectorFactory = Callable[[JobSource, PoliteClient], Connector]


def default_connector_factory(source: JobSource, client: PoliteClient) -> Connector:
    return get_connector_class(source.connector)(source.config, client)


@dataclass
class SourceStats:
    fetched: int = 0
    relevant: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    duplicates: int = 0
    reactivated: int = 0
    closed: int = 0
    skipped: Counter = field(default_factory=Counter)
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items() if k != "skipped"}
        d["skipped"] = dict(self.skipped)
        return d


@dataclass
class RunResult:
    execution_id: uuid.UUID
    status: ExecutionStatus
    per_source: dict[str, SourceStats]

    @property
    def created(self) -> int:
        return sum(s.created for s in self.per_source.values())


class DiscoveryService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        connector_factory: ConnectorFactory = default_connector_factory,
        client_factory: Callable[[], PoliteClient] = PoliteClient,
    ) -> None:
        self.session_factory = session_factory
        self.connector_factory = connector_factory
        self.client_factory = client_factory

    async def run(
        self,
        search_config_id: uuid.UUID,
        *,
        trigger: str = "manual",
        task_id: str | None = None,
        workflow_run_id: uuid.UUID | None = None,
    ) -> RunResult:
        started = datetime.now(UTC)
        t0 = time.perf_counter()
        async with self.session_factory() as session:
            cfg = await session.get(SearchConfiguration, search_config_id)
            if cfg is None:
                raise ValueError(f"Search configuration {search_config_id} not found")
            candidate = await session.get(Candidate, cfg.candidate_id)
            query = SearchQuery(
                keywords=cfg.keywords or (candidate.target_roles if candidate else []),
                countries=cfg.countries or (candidate.preferred_countries if candidate else []),
                max_results=cfg.max_results_per_source,
            )
            excluded = list(cfg.excluded_keywords)
            stmt = select(JobSource).where(JobSource.enabled.is_(True))
            if cfg.source_keys:
                stmt = stmt.where(JobSource.key.in_(cfg.source_keys))
            sources = list(await session.scalars(stmt.order_by(JobSource.key)))
            execution = AgentExecution(
                agent_name=AGENT_NAME,
                trigger=trigger,
                task_id=task_id,
                workflow_run_id=workflow_run_id,
                status=ExecutionStatus.RUNNING,
                started_at=started,
                details={
                    "search_config": cfg.name,
                    "keywords": query.keywords,
                    "countries": query.countries,
                    "sources": [s.key for s in sources],
                },
            )
            session.add(execution)
            cfg.last_run_at = started
            await session.commit()
            execution_id = execution.id
            source_ids = [s.id for s in sources]

        per_source: dict[str, SourceStats] = {}
        decisions: list[dict[str, Any]] = []
        requests = 0
        async with self.client_factory() as client:
            for source_id in source_ids:
                key, stats = await self._run_source(source_id, query, excluded, client, decisions)
                per_source[key] = stats
            requests = client.request_count

        failed = [k for k, s in per_source.items() if s.error]
        if per_source and len(failed) == len(per_source):
            status = ExecutionStatus.FAILED
        else:
            status = ExecutionStatus.SUCCEEDED
        async with self.session_factory() as session:
            execution = await session.get(AgentExecution, execution_id)
            assert execution is not None
            execution.status = status
            execution.finished_at = datetime.now(UTC)
            execution.duration_ms = int((time.perf_counter() - t0) * 1000)
            execution.items_processed = sum(s.fetched for s in per_source.values())
            execution.items_created = sum(s.created for s in per_source.values())
            execution.items_failed = len(failed)
            execution.error_type = "SourceErrors" if failed else None
            execution.error_message = (
                "; ".join(f"{k}: {per_source[k].error}" for k in failed) if failed else None
            )
            execution.decisions = decisions[:MAX_DECISIONS]
            execution.details = {
                **execution.details,
                "http_requests": requests,
                "per_source": {k: s.as_dict() for k, s in per_source.items()},
            }
            await session.commit()
        log.info(
            "discovery_run_finished",
            execution_id=str(execution_id),
            status=status.value,
            created=sum(s.created for s in per_source.values()),
            failed_sources=failed,
        )
        return RunResult(execution_id, status, per_source)

    async def _run_source(
        self,
        source_id: uuid.UUID,
        query: SearchQuery,
        excluded: list[str],
        client: PoliteClient,
        decisions: list[dict[str, Any]],
    ) -> tuple[str, SourceStats]:
        stats = SourceStats()
        async with self.session_factory() as session:
            source = await session.get(JobSource, source_id)
            assert source is not None
            key = source.key
            now = datetime.now(UTC)
            source.last_run_at = now
            seen_ids: set[str] = set()
            complete = False
            try:
                connector = self.connector_factory(source, client)
                for host in _hosts_for(connector):
                    client.set_rate_limit(host, source.rate_limit_per_minute)
                async for raw in connector.fetch(query):
                    stats.fetched += 1
                    if raw.external_id in seen_ids:
                        stats.skipped["repeated_in_feed"] += 1
                        continue
                    seen_ids.add(raw.external_id)
                    reason = self._filter(raw, query, excluded)
                    if reason:
                        stats.skipped[reason] += 1
                        continue
                    if stats.relevant >= query.max_results:
                        stats.skipped["max_results_reached"] += 1
                        continue
                    stats.relevant += 1
                    await self._upsert(session, source, raw, now, stats, decisions)
                complete = True
            except RobotsDisallowed as exc:
                stats.error = f"robots.txt: {exc}"
            except Exception as exc:  # one broken source must not stop the others
                stats.error = f"{type(exc).__name__}: {exc}"[:500]
                log.warning("discovery_source_failed", source=key, error=stats.error)
                if isinstance(exc, SQLAlchemyError):
                    # The transaction is unusable; drop this source's partial writes.
                    await session.rollback()
                    source = await session.get(JobSource, source_id)
                    assert source is not None
                    source.last_run_at = now

            if complete and connector.complete_listing:
                stats.closed = await self._close_missing(session, source, seen_ids, now)
            if stats.error:
                source.last_error = stats.error
            else:
                source.last_success_at = now
                source.last_error = None
            await session.commit()
        return key, stats

    @staticmethod
    def _filter(raw: RawJob, query: SearchQuery, excluded: list[str]) -> str | None:
        if not title_matches(raw.title, query.keywords, excluded):
            return "title_not_relevant"
        loc = _location(raw)
        if query.countries:
            if loc.country is None and not loc.europe_wide:
                return "country_unknown"
            if loc.country is not None and loc.country not in query.countries:
                return "country_not_targeted"
        return None

    async def _upsert(
        self,
        session: AsyncSession,
        source: JobSource,
        raw: RawJob,
        now: datetime,
        stats: SourceStats,
        decisions: list[dict[str, Any]],
    ) -> None:
        loc = _location(raw)
        company = await self._company(session, source, raw.company)
        chash = content_hash(
            raw.title,
            raw.description,
            raw.salary_raw,
            str(raw.salary_min),
            str(raw.salary_max),
            raw.location_raw,
        )
        fields = dict(
            company_id=company.id if company else None,
            url=raw.url[:1000],
            apply_url=(raw.apply_url or raw.url)[:1000],
            title=raw.title[:300],
            normalized_title=normalize_title(raw.title)[:300],
            description=raw.description,
            description_html=raw.description_html,
            country=loc.country,
            city=(raw.city or loc.city),
            location_raw=(raw.location_raw or "")[:300] or None,
            remote_type=raw.remote_type,
            employment_type=(raw.employment_type or "")[:50] or None,
            seniority=_seniority(raw.title),
            experience_min_years=extract_min_years(raw.description),
            salary_min=raw.salary_min,
            salary_max=raw.salary_max,
            salary_currency=raw.salary_currency,
            salary_period=raw.salary_period,
            salary_raw=(raw.salary_raw or "")[:300] or None,
            posted_at=raw.posted_at,
            expires_at=raw.expires_at,
            content_hash=chash,
            dedup_hash=dedup_hash(raw.company, raw.title, loc.country, raw.city or loc.city),
            raw_payload=raw.raw,
        )
        job = await session.scalar(
            select(Job).where(Job.source_id == source.id, Job.external_id == raw.external_id)
        )
        if job is not None:
            job.last_seen_at = now
            if job.status != JobStatus.ACTIVE:
                job.status = JobStatus.ACTIVE
                stats.reactivated += 1
            if job.content_hash != chash:
                for k, v in fields.items():
                    setattr(job, k, v)
                job.embedding = None  # re-embedded by the pipeline
                stats.updated += 1
                _decide(decisions, job.id, raw, "updated", "content changed")
            else:
                stats.unchanged += 1
            return

        # Same role already known from another source? Keep it, but point at the original.
        canonical = await session.scalar(
            select(Job.id)
            .where(
                Job.dedup_hash == fields["dedup_hash"],
                Job.source_id != source.id,
                Job.canonical_job_id.is_(None),
            )
            .order_by(Job.discovered_at)
            .limit(1)
        )
        job = Job(
            source_id=source.id,
            external_id=raw.external_id[:255],
            discovered_at=now,
            last_seen_at=now,
            status=JobStatus.ACTIVE,
            canonical_job_id=canonical,
            **fields,
        )
        session.add(job)
        await session.flush()
        if canonical:
            stats.duplicates += 1
            _decide(decisions, job.id, raw, "duplicate", f"same role as job {canonical}")
        else:
            stats.created += 1
            _decide(
                decisions,
                job.id,
                raw,
                "created",
                f"title matched; country={loc.country or 'Europe-wide'}",
            )

    @staticmethod
    async def _company(
        session: AsyncSession, source: JobSource, name: str | None
    ) -> Company | None:
        if not name:
            return None
        norm = normalize_company_name(name)
        if not norm:
            return None
        company = await session.scalar(select(Company).where(Company.normalized_name == norm))
        if company is None:
            company = Company(name=name[:200], normalized_name=norm[:200])
            if source.connector in ("greenhouse", "lever"):
                company.ats_type = source.connector
                company.ats_identifier = source.config.get("board_token") or source.config.get(
                    "site"
                )
            session.add(company)
            await session.flush()
        return company

    @staticmethod
    async def _close_missing(
        session: AsyncSession, source: JobSource, seen: set[str], now: datetime
    ) -> int:
        """On a complete board listing, active jobs that disappeared have been closed."""
        stmt = (
            update(Job)
            .where(Job.source_id == source.id, Job.status == JobStatus.ACTIVE)
            .values(status=JobStatus.CLOSED, updated_at=now)
        )
        if seen:
            stmt = stmt.where(Job.external_id.not_in(seen))
        result = await session.execute(stmt)
        return result.rowcount or 0


async def expire_stale_jobs(
    session_factory: async_sessionmaker[AsyncSession], *, expiry_days: int | None = None
) -> int:
    """Mark jobs expired when past their deadline or not seen for `expiry_days`."""
    days = expiry_days if expiry_days is not None else get_settings().job_expiry_days
    now = datetime.now(UTC)
    async with session_factory() as session:
        result = await session.execute(
            update(Job)
            .where(Job.status == JobStatus.ACTIVE)
            .where((Job.expires_at < now) | (Job.last_seen_at < now - timedelta(days=days)))
            .values(status=JobStatus.EXPIRED, updated_at=now)
        )
        await session.commit()
        return result.rowcount or 0


def _location(raw: RawJob) -> ParsedLocation:
    default = raw.raw.get("default_country") if isinstance(raw.raw, dict) else None
    if raw.country:  # the source states the country explicitly
        parsed = parse_location(raw.location_raw)
        return ParsedLocation(raw.country.upper(), raw.city or parsed.city, False)
    return parse_location(*(raw.location_raw or "").split(";"), default_country=default)


def _seniority(title: str) -> str | None:
    t = title.lower()
    return next((label for word, label in SENIORITY_WORDS if word in t), None)


def _hosts_for(connector: Connector) -> list[str]:
    hosts = {
        "greenhouse": ["boards-api.greenhouse.io"],
        "lever": ["api.lever.co", "api.eu.lever.co"],
        "arbeitnow": ["www.arbeitnow.com"],
        "adzuna": ["api.adzuna.com"],
    }
    return hosts.get(connector.name, [])


def _decide(
    decisions: list[dict[str, Any]], job_id: uuid.UUID, raw: RawJob, decision: str, reason: str
) -> None:
    if len(decisions) < MAX_DECISIONS:
        decisions.append(
            {
                "job_id": str(job_id),
                "title": raw.title[:120],
                "decision": decision,
                "reason": reason,
            }
        )
