"""Job sources and on-demand discovery runs."""

import asyncio
import uuid

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy import func, select

from backend.deps import CandidateDep, SessionDep
from backend.schemas.discovery import (
    ConnectorInfo,
    DiscoveryRunRequest,
    DiscoveryRunResponse,
    SourceCreate,
    SourceRead,
    SourceUpdate,
)
from backend.security import ActorDep
from backend.services.audit import record_audit
from common.enums import JobStatus, SourceType
from connectors.registry import CONNECTORS, get_connector_class
from database.models import Job, JobSource, SearchConfiguration

router = APIRouter(tags=["discovery"])

_SOURCE_TYPES = {
    "greenhouse": SourceType.ATS_BOARD,
    "lever": SourceType.ATS_BOARD,
    "rss": SourceType.RSS,
}


def _validate_config(connector: str, config: dict) -> dict:
    try:
        cls = get_connector_class(connector)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    try:
        return cls.config_model.model_validate(config).model_dump(mode="json", exclude_none=True)
    except ValidationError as exc:
        errors = [{k: v for k, v in e.items() if k in ("loc", "msg", "type")} for e in exc.errors()]
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, {"config_errors": errors}
        ) from exc


async def _with_counts(session: SessionDep, sources: list[JobSource]) -> list[SourceRead]:
    counts = dict(
        (
            await session.execute(
                select(Job.source_id, func.count())
                .where(Job.status == JobStatus.ACTIVE, Job.canonical_job_id.is_(None))
                .group_by(Job.source_id)
            )
        ).all()
    )
    out = []
    for s in sources:
        r = SourceRead.model_validate(s)
        r.active_jobs = counts.get(s.id, 0)
        out.append(r)
    return out


@router.get("/discovery/connectors", response_model=list[ConnectorInfo])
async def list_connectors() -> list[ConnectorInfo]:
    return [
        ConnectorInfo(
            name=n,
            complete_listing=c.complete_listing,
            config_schema=c.config_model.model_json_schema(),
        )
        for n, c in sorted(CONNECTORS.items())
    ]


@router.get("/sources", response_model=list[SourceRead])
async def list_sources(session: SessionDep) -> list[SourceRead]:
    sources = list(await session.scalars(select(JobSource).order_by(JobSource.key)))
    return await _with_counts(session, sources)


@router.post("/sources", response_model=SourceRead, status_code=status.HTTP_201_CREATED)
async def create_source(
    body: SourceCreate, session: SessionDep, actor: ActorDep, request: Request
) -> SourceRead:
    config = _validate_config(body.connector, body.config)
    if await session.scalar(select(JobSource.id).where(JobSource.key == body.key)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Source '{body.key}' already exists")
    source = JobSource(
        key=body.key,
        name=body.name,
        connector=body.connector,
        config=config,
        source_type=_SOURCE_TYPES.get(body.connector, SourceType.API),
        terms_url=body.terms_url,
        enabled=body.enabled,
        rate_limit_per_minute=body.rate_limit_per_minute,
        respects_robots_txt=True,
    )
    session.add(source)
    await session.flush()
    record_audit(
        session,
        request=request,
        actor=actor,
        action="source.create",
        entity_type="job_source",
        entity_id=source.id,
        details={"key": body.key},
    )
    await session.commit()
    return (await _with_counts(session, [source]))[0]


@router.patch("/sources/{source_id}", response_model=SourceRead)
async def update_source(
    source_id: uuid.UUID,
    body: SourceUpdate,
    session: SessionDep,
    actor: ActorDep,
    request: Request,
) -> SourceRead:
    source = await session.get(JobSource, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if "config" in changes:
        changes["config"] = _validate_config(source.connector, changes["config"])
    for k, v in changes.items():
        setattr(source, k, v)
    record_audit(
        session,
        request=request,
        actor=actor,
        action="source.update",
        entity_type="job_source",
        entity_id=source.id,
        details=changes,
    )
    await session.commit()
    return (await _with_counts(session, [source]))[0]


@router.post(
    "/discovery/run", response_model=DiscoveryRunResponse, status_code=status.HTTP_202_ACCEPTED
)
async def run_discovery(
    body: DiscoveryRunRequest,
    candidate: CandidateDep,
    session: SessionDep,
    actor: ActorDep,
    request: Request,
) -> DiscoveryRunResponse:
    stmt = select(SearchConfiguration).where(SearchConfiguration.candidate_id == candidate.id)
    if body.search_config_id:
        stmt = stmt.where(SearchConfiguration.id == body.search_config_id)
    else:
        stmt = stmt.where(SearchConfiguration.enabled.is_(True))
    configs = list(await session.scalars(stmt))
    if not configs:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No matching search configuration")

    from workers.tasks.discovery import run_search

    queued = []
    for cfg in configs:
        try:
            res = await asyncio.to_thread(run_search.apply_async, args=[str(cfg.id), "api"])
        except Exception as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, f"Broker unavailable: {type(exc).__name__}"
            ) from exc
        queued.append({"search_config_id": str(cfg.id), "name": cfg.name, "task_id": res.id})
    record_audit(
        session,
        request=request,
        actor=actor,
        action="discovery.run",
        entity_type="search_configuration",
        details={"queued": len(queued)},
    )
    await session.commit()
    return DiscoveryRunResponse(queued=queued)
