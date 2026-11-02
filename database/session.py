"""Async engine and session factory."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from common.config import Settings, get_settings


def create_engine(settings: Settings | None = None, *, null_pool: bool = False) -> AsyncEngine:
    settings = settings or get_settings()
    kwargs: dict = {"echo": settings.db_echo, "pool_pre_ping": True}
    if null_pool:
        # Celery prefork workers and tests run their own event loops; never share connections.
        kwargs["poolclass"] = NullPool
    else:
        kwargs["pool_size"] = settings.db_pool_size
    return create_async_engine(settings.database_url.get_secret_value(), **kwargs)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def session_scope(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
