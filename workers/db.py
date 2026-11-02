"""Database access for Celery tasks. Each task runs its own event loop, so no pooling."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from database.session import create_engine, create_session_factory


def task_session_factory() -> tuple[async_sessionmaker[AsyncSession], object]:
    engine = create_engine(null_pool=True)
    return create_session_factory(engine), engine
