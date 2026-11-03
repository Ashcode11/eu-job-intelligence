"""Shared fixtures. Integration tests need PostgreSQL and Redis from docker compose."""

import os
from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import make_url, text

from common.config import Settings, get_settings

TEST_API_KEY = "test-api-key"
ALEMBIC_INI = str(Path(__file__).resolve().parent.parent / "alembic.ini")


def _test_database_url() -> str:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit
    url = make_url(get_settings().database_url.get_secret_value())
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def test_settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    base = get_settings()
    redis_url = os.environ.get("TEST_REDIS_URL", base.redis_url.rsplit("/", 1)[0] + "/15")
    return Settings(
        environment="test",
        database_url=_test_database_url(),
        redis_url=redis_url,
        api_keys=TEST_API_KEY,
        upload_dir=tmp_path_factory.mktemp("uploads"),
        rate_limit_default="10000/minute",
        log_json=False,
        log_level="WARNING",
    )


@pytest.fixture(scope="session")
async def migrated_db(test_settings: Settings) -> AsyncIterator[str]:
    """Create the test database if needed and migrate it to head with Alembic."""
    url = make_url(test_settings.database_url.get_secret_value())
    admin_dsn = url.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False
    )
    try:
        conn = await asyncpg.connect(admin_dsn, timeout=5)
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"PostgreSQL not reachable ({exc}); run `docker compose up -d postgres redis`")
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", url.database)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{url.database}"')
    finally:
        await conn.close()

    from alembic import command
    from alembic.config import Config

    os.environ["DATABASE_URL"] = test_settings.database_url.get_secret_value()
    get_settings.cache_clear()
    cfg = Config(ALEMBIC_INI)
    # env.py calls asyncio.run(); run it outside this event loop.
    import asyncio

    await asyncio.to_thread(command.upgrade, cfg, "head")
    yield test_settings.database_url.get_secret_value()


@pytest.fixture
async def engine(migrated_db: str, test_settings: Settings):
    from database.session import create_engine

    eng = create_engine(test_settings, null_pool=True)
    async with eng.begin() as conn:
        tables = (
            (
                await conn.execute(
                    text(
                        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                        "AND tablename <> 'alembic_version'"
                    )
                )
            )
            .scalars()
            .all()
        )
        await conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine):
    from database.session import create_session_factory

    async with create_session_factory(engine)() as s:
        yield s


@pytest.fixture
async def client(engine, test_settings: Settings) -> AsyncIterator[AsyncClient]:
    from backend.main import create_app

    app = create_app(test_settings, engine=engine)
    async with app.router.lifespan_context(app):
        try:
            await app.state.redis.ping()
        except Exception as exc:
            pytest.skip(f"Redis not reachable ({exc})")
        await app.state.redis.flushdb()
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", headers={"X-API-Key": TEST_API_KEY}
        ) as c:
            yield c


class _FakeAsyncResult:
    def __init__(self, task_name: str) -> None:
        import uuid

        self.id = str(uuid.uuid4())
        self.task_name = task_name


@pytest.fixture(autouse=True)
def queued_tasks(monkeypatch):
    """Never send real Celery tasks from tests; record them instead."""
    from celery.app.task import Task

    calls: list[dict] = []

    def fake_apply_async(self, args=None, kwargs=None, **options):
        calls.append({"task": self.name, "args": list(args or []), "kwargs": dict(kwargs or {})})
        return _FakeAsyncResult(self.name)

    monkeypatch.setattr(Task, "apply_async", fake_apply_async)
    return calls
