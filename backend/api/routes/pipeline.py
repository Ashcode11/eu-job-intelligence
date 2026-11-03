"""Run the agent pipeline, reprocess jobs, and read notifications."""

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select, update

from backend.deps import CandidateDep, SessionDep
from backend.security import ActorDep
from backend.services.audit import record_audit
from backend.services.tasks import enqueue
from common.enums import NotificationStatus
from database.models import Job, Notification, SearchConfiguration

router = APIRouter(tags=["pipeline"])


class PipelineRunRequest(BaseModel):
    search_config_id: uuid.UUID | None = None
    analyse_only: bool = False
    force: bool = False


@router.post("/pipeline/run", status_code=status.HTTP_202_ACCEPTED)
async def run_pipeline(
    body: PipelineRunRequest,
    candidate: CandidateDep,
    session: SessionDep,
    actor: ActorDep,
    request: Request,
) -> dict:
    """Discovery + all analysis agents. `analyse_only` re-scores stored jobs without fetching."""
    from workers.tasks.agents import run_pipeline as task

    queued = []
    if body.analyse_only:
        queued.append(
            {
                "task_id": await enqueue(task, force=body.force, trigger="api"),
                "scope": "analysis of stored jobs",
            }
        )
    else:
        stmt = select(SearchConfiguration).where(SearchConfiguration.candidate_id == candidate.id)
        stmt = (
            stmt.where(SearchConfiguration.id == body.search_config_id)
            if body.search_config_id
            else stmt.where(SearchConfiguration.enabled.is_(True))
        )
        configs = list(await session.scalars(stmt))
        if not configs:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No matching search configuration")
        for cfg in configs:
            tid = await enqueue(task, search_config_id=str(cfg.id), force=body.force, trigger="api")
            queued.append({"task_id": tid, "scope": cfg.name})
    record_audit(
        session,
        request=request,
        actor=actor,
        action="pipeline.run",
        entity_type="pipeline",
        details=body.model_dump(),
    )
    await session.commit()
    return {"queued": queued}


@router.post("/jobs/{job_id}/reprocess", status_code=status.HTTP_202_ACCEPTED)
async def reprocess_job(
    job_id: uuid.UUID, session: SessionDep, actor: ActorDep, request: Request
) -> dict:
    """Re-run every analysis for one job, ignoring cached results."""
    from workers.tasks.agents import run_pipeline as task

    if await session.get(Job, job_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    tid = await enqueue(task, job_ids=[str(job_id)], force=True, trigger="reprocess")
    record_audit(
        session,
        request=request,
        actor=actor,
        action="job.reprocess",
        entity_type="job",
        entity_id=job_id,
    )
    await session.commit()
    return {"task_id": tid}


class NotificationRead(BaseModel):
    id: uuid.UUID
    kind: str
    channel: str
    title: str
    body: str
    job_id: uuid.UUID | None
    status: str
    created_at: str


@router.get("/notifications", response_model=list[NotificationRead])
async def list_notifications(
    candidate: CandidateDep,
    session: SessionDep,
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[NotificationRead]:
    stmt = (
        select(Notification)
        .where(Notification.candidate_id == candidate.id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    if unread_only:
        stmt = stmt.where(Notification.status != NotificationStatus.READ)
    return [
        NotificationRead(
            id=n.id,
            kind=n.kind.value,
            channel=n.channel.value,
            title=n.title,
            body=n.body,
            job_id=n.job_id,
            status=n.status.value,
            created_at=n.created_at.isoformat(),
        )
        for n in await session.scalars(stmt)
    ]


@router.post("/notifications/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(
    candidate: CandidateDep, session: SessionDep, ids: list[uuid.UUID] | None = None
) -> None:
    """Mark the given notifications (or all) as read."""
    stmt = (
        update(Notification)
        .where(Notification.candidate_id == candidate.id)
        .values(status=NotificationStatus.READ)
    )
    if ids:
        stmt = stmt.where(Notification.id.in_(ids))
    await session.execute(stmt)
    await session.commit()
