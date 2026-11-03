"""Agent tasks, one Celery queue per worker type.

- orchestrator: the full LangGraph pipeline (discovery + analysis) and reprocessing
- matching:     CV parsing (CV Intelligence agent)
- visa:         visa re-assessment, e.g. after a company's sponsor evidence changes
- application:  application drafts (never sent or submitted)
"""

import asyncio
import uuid

import redis

from agents.application.service import ApplicationPrepService
from agents.cv_intelligence.service import CVIntelligenceService
from agents.llm.ollama import OllamaClient
from agents.orchestrator.pipeline import Pipeline
from common.config import get_settings
from common.logging import get_logger
from workers.celery_app import celery_app
from workers.db import task_session_factory

log = get_logger(__name__)


@celery_app.task(
    name="orchestrator.run_pipeline", bind=True, max_retries=2, default_retry_delay=300
)
def run_pipeline(
    self,
    search_config_id: str | None = None,
    job_ids: list[str] | None = None,
    force: bool = False,
    trigger: str = "manual",
) -> dict:
    lock_key = f"lock:pipeline:{search_config_id or 'analysis'}"
    lock = redis.Redis.from_url(get_settings().redis_url).lock(lock_key, timeout=2 * 3600)
    # Reprocessing specific jobs may run alongside; whole-pipeline runs never overlap.
    if not job_ids and not lock.acquire(blocking=False):
        return {"skipped": "already running"}
    try:
        return asyncio.run(_pipeline(search_config_id, job_ids, force, trigger))
    except Exception as exc:
        raise self.retry(exc=exc) from exc
    finally:
        if not job_ids:
            try:
                lock.release()
            except redis.exceptions.LockError:
                pass


async def _pipeline(config_id, job_ids, force, trigger) -> dict:
    factory, engine = task_session_factory()
    try:
        async with OllamaClient() as llm:
            state = await Pipeline(factory, llm=llm).run(
                search_config_id=uuid.UUID(config_id) if config_id else None,
                job_ids=[uuid.UUID(j) for j in job_ids] if job_ids else None,
                force=force,
                trigger=trigger,
            )
        return {
            "workflow_run_id": state["workflow_run_id"],
            "discovered": state.get("discovered", 0),
            "analysed": len(state.get("selected") or []),
            "high_matches": len(state.get("high_matches") or []),
            "llm_available": state.get("llm_available"),
            "counters": state.get("counters"),
        }
    finally:
        await engine.dispose()


@celery_app.task(name="matching.parse_resume", bind=True, max_retries=1)
def parse_resume(self, resume_id: str, trigger: str = "upload") -> dict:
    async def _run() -> dict:
        factory, engine = task_session_factory()
        try:
            async with OllamaClient() as llm:
                return await CVIntelligenceService(factory, llm).process(
                    uuid.UUID(resume_id), trigger=trigger
                )
        finally:
            await engine.dispose()

    return asyncio.run(_run())


@celery_app.task(name="visa.reassess")
def reassess_visa(job_ids: list[str] | None = None) -> dict:
    """Re-run analysis (visa first) for the given jobs, or every active job."""
    return asyncio.run(_pipeline(None, job_ids, True, "visa_reassess"))


@celery_app.task(name="application.prepare", bind=True, max_retries=1)
def prepare_application(self, application_id: str) -> dict:
    async def _run() -> dict:
        factory, engine = task_session_factory()
        try:
            async with OllamaClient() as llm:
                return await ApplicationPrepService(factory, llm).prepare(uuid.UUID(application_id))
        finally:
            await engine.dispose()

    return asyncio.run(_run())
