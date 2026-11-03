"""Application tracker. Tracks status only; nothing is ever submitted on the user's behalf."""

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.deps import CandidateDep, SessionDep
from backend.schemas.jobs import ApplicationCreate, ApplicationRead, ApplicationUpdate
from backend.security import ActorDep
from backend.services.audit import record_audit
from backend.services.tasks import enqueue
from common.enums import ApplicationStatus
from database.models import Application, CandidateResume, Job

router = APIRouter(prefix="/applications", tags=["applications"])


def _to_read(app: Application) -> ApplicationRead:
    data = ApplicationRead.model_validate(app)
    if app.job is not None:
        data.job_title = app.job.title
        data.company_name = app.job.company.name if app.job.company else None
        data.country = app.job.country
    return data


async def _load(session: SessionDep, app_id: uuid.UUID, candidate_id: uuid.UUID) -> Application:
    app = await session.scalar(
        select(Application)
        .where(Application.id == app_id, Application.candidate_id == candidate_id)
        .options(selectinload(Application.job).selectinload(Job.company))
        .execution_options(populate_existing=True)
    )
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    return app


@router.get("", response_model=list[ApplicationRead])
async def list_applications(
    candidate: CandidateDep,
    session: SessionDep,
    app_status: Annotated[list[ApplicationStatus] | None, Query(alias="status")] = None,
) -> list[ApplicationRead]:
    stmt = (
        select(Application)
        .where(Application.candidate_id == candidate.id)
        .options(selectinload(Application.job).selectinload(Job.company))
        .order_by(Application.updated_at.desc())
    )
    if app_status:
        stmt = stmt.where(Application.status.in_(app_status))
    return [_to_read(a) for a in await session.scalars(stmt)]


@router.post("", response_model=ApplicationRead, status_code=status.HTTP_201_CREATED)
async def create_application(
    body: ApplicationCreate,
    candidate: CandidateDep,
    session: SessionDep,
    actor: ActorDep,
    request: Request,
) -> ApplicationRead:
    if await session.get(Job, body.job_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    existing = await session.scalar(
        select(Application.id).where(
            Application.candidate_id == candidate.id, Application.job_id == body.job_id
        )
    )
    if existing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Job is already tracked",
            headers={"Location": f"/api/v1/applications/{existing}"},
        )
    now = datetime.now(UTC)
    app = Application(
        candidate_id=candidate.id,
        job_id=body.job_id,
        status=body.status,
        notes=body.notes,
        status_history=[{"from": None, "to": body.status.value, "at": now.isoformat()}],
        applied_at=now if body.status == ApplicationStatus.APPLIED else None,
    )
    session.add(app)
    await session.flush()
    record_audit(
        session,
        request=request,
        actor=actor,
        action="application.create",
        entity_type="application",
        entity_id=app.id,
        details={"job_id": body.job_id, "status": body.status},
    )
    await session.commit()
    return _to_read(await _load(session, app.id, candidate.id))


@router.patch("/{application_id}", response_model=ApplicationRead)
async def update_application(
    application_id: uuid.UUID,
    body: ApplicationUpdate,
    candidate: CandidateDep,
    session: SessionDep,
    actor: ActorDep,
    request: Request,
) -> ApplicationRead:
    app = await _load(session, application_id, candidate.id)
    now = datetime.now(UTC)
    if body.status is not None and body.status != app.status:
        entry = {"from": app.status.value, "to": body.status.value, "at": now.isoformat()}
        if body.status_note:
            entry["note"] = body.status_note
        app.status_history = [*app.status_history, entry]  # reassign so JSONB change is tracked
        app.status = body.status
        if body.status == ApplicationStatus.APPLIED and app.applied_at is None:
            app.applied_at = now
    if body.notes is not None:
        app.notes = body.notes
    if body.interview_at is not None:
        app.interview_at = body.interview_at
    record_audit(
        session,
        request=request,
        actor=actor,
        action="application.update",
        entity_type="application",
        entity_id=app.id,
        details=body.model_dump(exclude_none=True),
    )
    await session.commit()
    return _to_read(await _load(session, app.id, candidate.id))


@router.delete("/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_application(
    application_id: uuid.UUID,
    candidate: CandidateDep,
    session: SessionDep,
    actor: ActorDep,
    request: Request,
) -> None:
    app = await _load(session, application_id, candidate.id)
    await session.delete(app)
    record_audit(
        session,
        request=request,
        actor=actor,
        action="application.delete",
        entity_type="application",
        entity_id=application_id,
    )
    await session.commit()


@router.post("/{application_id}/prepare", status_code=status.HTTP_202_ACCEPTED)
async def prepare_application(
    application_id: uuid.UUID,
    candidate: CandidateDep,
    session: SessionDep,
    actor: ActorDep,
    request: Request,
) -> dict:
    """Ask the Application agent for drafts. Nothing is sent or submitted."""
    from workers.tasks.agents import prepare_application as task

    await _load(session, application_id, candidate.id)
    tid = await enqueue(task, str(application_id))
    record_audit(
        session,
        request=request,
        actor=actor,
        action="application.prepare",
        entity_type="application",
        entity_id=application_id,
    )
    await session.commit()
    return {"task_id": tid}


class DraftsUpdate(BaseModel):
    cover_letter_draft: Annotated[str, StringConstraints(max_length=20000)] | None = None
    outreach_message_draft: Annotated[str, StringConstraints(max_length=2000)] | None = None


@router.patch("/{application_id}/drafts", response_model=ApplicationRead)
async def edit_drafts(
    application_id: uuid.UUID,
    body: DraftsUpdate,
    candidate: CandidateDep,
    session: SessionDep,
    actor: ActorDep,
    request: Request,
) -> ApplicationRead:
    """Edit drafts. Any edit clears a previous approval."""
    app = await _load(session, application_id, candidate.id)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(app, k, v)
    app.drafts_approved_at = None
    record_audit(
        session,
        request=request,
        actor=actor,
        action="application.edit_drafts",
        entity_type="application",
        entity_id=application_id,
    )
    await session.commit()
    return _to_read(await _load(session, application_id, candidate.id))


@router.post("/{application_id}/approve-drafts", response_model=ApplicationRead)
async def approve_drafts(
    application_id: uuid.UUID,
    candidate: CandidateDep,
    session: SessionDep,
    actor: ActorDep,
    request: Request,
) -> ApplicationRead:
    """Record your approval of the drafts. You still send or submit them yourself."""
    app = await _load(session, application_id, candidate.id)
    if not (app.cover_letter_draft or app.outreach_message_draft):
        raise HTTPException(status.HTTP_409_CONFLICT, "No drafts to approve yet")
    app.drafts_approved_at = datetime.now(UTC)
    record_audit(
        session,
        request=request,
        actor=actor,
        action="application.approve_drafts",
        entity_type="application",
        entity_id=application_id,
    )
    await session.commit()
    return _to_read(await _load(session, application_id, candidate.id))


@router.get("/{application_id}/tailored-cv")
async def download_tailored_cv(
    application_id: uuid.UUID, candidate: CandidateDep, session: SessionDep
) -> FileResponse:
    app = await _load(session, application_id, candidate.id)
    resume = (
        await session.get(CandidateResume, app.tailored_resume_id)
        if app.tailored_resume_id
        else None
    )
    if resume is None or not await asyncio.to_thread(Path(resume.storage_path).is_file):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No tailored CV yet")
    return FileResponse(
        resume.storage_path, media_type=resume.content_type, filename=resume.original_filename
    )
