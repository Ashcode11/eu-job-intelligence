"""FastAPI dependencies: settings, DB session, Redis, current candidate."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from common.config import Settings, get_settings
from database.models import Candidate


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = request.app.state.session_factory
    # Routes commit explicitly, so a failed commit is reported to the client instead of
    # happening after the response has been sent.
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def get_redis(request: Request) -> Redis:
    return request.app.state.redis


SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
RedisDep = Annotated[Redis, Depends(get_redis)]


async def load_candidate(session: AsyncSession) -> Candidate | None:
    """Single-tenant: the platform manages one candidate (the oldest row)."""
    return await session.scalar(
        select(Candidate)
        .options(
            selectinload(Candidate.skills),
            selectinload(Candidate.experiences),
            selectinload(Candidate.resumes),
        )
        .order_by(Candidate.created_at)
        .limit(1)
        .execution_options(populate_existing=True)
    )


async def get_current_candidate(session: SessionDep) -> Candidate:
    candidate = await load_candidate(session)
    if candidate is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No candidate profile yet. Create one with POST /api/v1/candidate "
            "or run `python -m scripts.seed`.",
        )
    return candidate


CandidateDep = Annotated[Candidate, Depends(get_current_candidate)]
