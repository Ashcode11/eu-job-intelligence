"""Overview statistics and agent monitoring."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import distinct_on

from backend.deps import CandidateDep, SessionDep
from backend.schemas.jobs import AgentExecutionRead, AgentSummary, OverviewStats
from common.enums import (
    ApplicationStatus,
    ExecutionStatus,
    JobStatus,
    VisaClassification,
)
from database.models import AgentExecution, Application, Job, JobMatch, VisaAssessment

router = APIRouter(tags=["monitoring"])

MATCH_THRESHOLD = 50.0
HIGH_MATCH_THRESHOLD = 75.0
AGENTS = [
    "discovery",
    "cv_intelligence",
    "matching",
    "visa",
    "salary",
    "application",
    "orchestrator",
    "notifications",
]

_SUBMITTED = [
    ApplicationStatus.APPLIED,
    ApplicationStatus.INTERVIEW_SCHEDULED,
    ApplicationStatus.REJECTED,
    ApplicationStatus.OFFER_RECEIVED,
]
_PENDING = [ApplicationStatus.SAVED, ApplicationStatus.SHORTLISTED, ApplicationStatus.PREPARED]


@router.get("/stats/overview", response_model=OverviewStats)
async def overview(candidate: CandidateDep, session: SessionDep) -> OverviewStats:
    jobs = (
        await session.execute(
            select(
                func.count(Job.id),
                func.count(Job.id).filter(Job.status == JobStatus.ACTIVE),
                func.count(Job.id).filter(
                    and_(Job.status == JobStatus.ACTIVE, JobMatch.overall_score >= MATCH_THRESHOLD)
                ),
                func.count(Job.id).filter(
                    and_(
                        Job.status == JobStatus.ACTIVE,
                        JobMatch.overall_score >= HIGH_MATCH_THRESHOLD,
                    )
                ),
                func.count(Job.id).filter(
                    and_(
                        Job.status == JobStatus.ACTIVE,
                        VisaAssessment.classification.in_(
                            [
                                VisaClassification.EXPLICIT_SPONSORSHIP,
                                VisaClassification.POTENTIAL_SPONSORSHIP,
                            ]
                        ),
                    )
                ),
            )
            .outerjoin(
                JobMatch, and_(JobMatch.job_id == Job.id, JobMatch.candidate_id == candidate.id)
            )
            .outerjoin(VisaAssessment, VisaAssessment.job_id == Job.id)
            .where(Job.canonical_job_id.is_(None))
        )
    ).one()
    apps = (
        await session.execute(
            select(
                func.count().filter(Application.status.in_(_SUBMITTED)),
                func.count().filter(Application.status.in_(_PENDING)),
            ).where(Application.candidate_id == candidate.id)
        )
    ).one()
    return OverviewStats(
        total_jobs=jobs[0],
        active_jobs=jobs[1],
        matching_jobs=jobs[2],
        high_match_jobs=jobs[3],
        visa_sponsorship_jobs=jobs[4],
        applications_submitted=apps[0],
        applications_pending=apps[1],
        match_threshold=MATCH_THRESHOLD,
        high_match_threshold=HIGH_MATCH_THRESHOLD,
    )


@router.get("/agents/executions", response_model=list[AgentExecutionRead])
async def list_executions(
    session: SessionDep,
    agent: str | None = None,
    exec_status: Annotated[ExecutionStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[AgentExecution]:
    stmt = select(AgentExecution).order_by(AgentExecution.started_at.desc()).limit(limit)
    if agent:
        stmt = stmt.where(AgentExecution.agent_name == agent)
    if exec_status:
        stmt = stmt.where(AgentExecution.status == exec_status)
    return list(await session.scalars(stmt))


@router.get("/agents/summary", response_model=list[AgentSummary])
async def agent_summary(session: SessionDep) -> list[AgentSummary]:
    since = datetime.now(UTC) - timedelta(hours=24)
    agg = {
        r.agent_name: r
        for r in await session.execute(
            select(
                AgentExecution.agent_name,
                func.count().label("runs"),
                func.count()
                .filter(AgentExecution.status == ExecutionStatus.FAILED)
                .label("failures"),
                func.coalesce(func.sum(AgentExecution.items_created), 0).label("created"),
                func.coalesce(
                    func.sum(
                        func.coalesce(AgentExecution.llm_prompt_tokens, 0)
                        + func.coalesce(AgentExecution.llm_completion_tokens, 0)
                    ),
                    0,
                ).label("tokens"),
            )
            .where(AgentExecution.started_at >= since)
            .group_by(AgentExecution.agent_name)
        )
    }
    last_run = (
        select(AgentExecution)
        .ext(distinct_on(AgentExecution.agent_name))
        .order_by(AgentExecution.agent_name, AgentExecution.started_at.desc())
    )
    latest = {e.agent_name: e for e in await session.scalars(last_run)}

    names = sorted(set(AGENTS) | set(latest), key=lambda n: (n not in AGENTS, n))
    out = []
    for name in names:
        last, a = latest.get(name), agg.get(name)
        out.append(
            AgentSummary(
                agent_name=name,
                last_status=last.status if last else None,
                last_started_at=last.started_at if last else None,
                last_duration_ms=last.duration_ms if last else None,
                runs_24h=a.runs if a else 0,
                failures_24h=a.failures if a else 0,
                items_created_24h=a.created if a else 0,
                llm_tokens_24h=a.tokens if a else 0,
            )
        )
    return out


@router.post("/agents/ping", status_code=status.HTTP_202_ACCEPTED)
async def ping_workers() -> dict[str, str]:
    """Enqueue a no-op task to verify the broker and a worker are alive."""
    from workers.tasks.system import ping

    try:
        result = await asyncio.to_thread(ping.apply_async, expires=60)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Broker unavailable: {type(exc).__name__}"
        ) from exc
    return {"task_id": result.id}


@router.get("/agents/tasks/{task_id}")
async def task_status(task_id: str) -> dict[str, object]:
    from workers.celery_app import celery_app

    def _read() -> dict[str, object]:
        res = celery_app.AsyncResult(task_id)
        return {
            "task_id": task_id,
            "state": res.state,
            "result": res.result if res.successful() else None,
        }

    return await asyncio.to_thread(_read)
