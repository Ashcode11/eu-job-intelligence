"""Discovery tasks: per-search runs, the scheduler tick, and job expiry."""

import asyncio
import time
import uuid
from datetime import UTC, datetime

import redis
from croniter import croniter
from sqlalchemy import select

from agents.discovery.service import DiscoveryService, expire_stale_jobs
from common.config import get_settings
from common.enums import ExecutionStatus
from common.logging import get_logger
from database.models import AgentExecution, SearchConfiguration
from workers.celery_app import celery_app
from workers.db import task_session_factory

log = get_logger(__name__)
LOCK_TTL_SECONDS = 60 * 60


@celery_app.task(name="discovery.run_search", bind=True, max_retries=2, default_retry_delay=120)
def run_search(self, search_config_id: str, trigger: str = "manual") -> dict:
    """Run one search configuration. A Redis lock stops overlapping runs of the same search."""
    r = redis.Redis.from_url(get_settings().redis_url)
    lock = r.lock(f"lock:discovery:{search_config_id}", timeout=LOCK_TTL_SECONDS)
    if not lock.acquire(blocking=False):
        log.info("discovery_already_running", search_config_id=search_config_id)
        return {"skipped": "already running"}
    try:
        return asyncio.run(_run(search_config_id, trigger, self.request.id))
    except Exception as exc:
        log.exception("discovery_task_failed", search_config_id=search_config_id)
        raise self.retry(exc=exc) from exc
    finally:
        try:
            lock.release()
        except redis.exceptions.LockError:
            pass


async def _run(search_config_id: str, trigger: str, task_id: str | None) -> dict:
    factory, engine = task_session_factory()
    try:
        result = await DiscoveryService(factory).run(
            uuid.UUID(search_config_id), trigger=trigger, task_id=task_id
        )
        return {
            "execution_id": str(result.execution_id),
            "status": result.status.value,
            "created": result.created,
            "per_source": {k: v.as_dict() for k, v in result.per_source.items()},
        }
    finally:
        await engine.dispose()


@celery_app.task(name="discovery.dispatch_due")
def dispatch_due() -> list[str]:
    """Scheduler tick (every few minutes): enqueue searches whose cron schedule is due."""
    return asyncio.run(_dispatch_due())


async def _dispatch_due() -> list[str]:
    factory, engine = task_session_factory()
    now = datetime.now(UTC)
    due: list[str] = []
    try:
        async with factory() as session:
            configs = await session.scalars(
                select(SearchConfiguration).where(SearchConfiguration.enabled.is_(True))
            )
            for cfg in configs:
                if is_due(cfg.schedule_cron, cfg.last_run_at or cfg.created_at, now):
                    due.append(str(cfg.id))
    finally:
        await engine.dispose()
    for config_id in due:
        run_search.apply_async(args=[config_id, "schedule"])
    if due:
        log.info("discovery_dispatched", count=len(due))
    return due


def is_due(cron: str, last_run: datetime, now: datetime) -> bool:
    """True if a scheduled time fell between the last run and now."""
    if not croniter.is_valid(cron):
        log.warning("invalid_cron", cron=cron)
        return False
    return croniter(cron, last_run).get_next(datetime) <= now


@celery_app.task(name="discovery.expire_jobs")
def expire_jobs() -> int:
    return asyncio.run(_expire())


async def _expire() -> int:
    factory, engine = task_session_factory()
    started, t0 = datetime.now(UTC), time.perf_counter()
    try:
        count = await expire_stale_jobs(factory)
        async with factory() as session:
            session.add(
                AgentExecution(
                    agent_name="job_expiry",
                    trigger="schedule",
                    status=ExecutionStatus.SUCCEEDED,
                    started_at=started,
                    finished_at=datetime.now(UTC),
                    duration_ms=int((time.perf_counter() - t0) * 1000),
                    items_processed=count,
                    details={"expired": count},
                )
            )
            await session.commit()
        log.info("jobs_expired", count=count)
        return count
    finally:
        await engine.dispose()
