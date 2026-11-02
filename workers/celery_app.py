"""Celery application shared by every worker. Each worker container subscribes to its own queue."""

from celery import Celery
from celery.signals import setup_logging

from common.config import get_settings
from common.logging import configure_logging

settings = get_settings()

celery_app = Celery(
    "eujobs",
    broker=settings.broker_url,
    backend=settings.result_backend,
    include=["workers.tasks.system"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,  # redeliver if a worker dies mid-task
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # long LLM tasks: don't hoard work
    result_expires=60 * 60 * 24,
    broker_connection_retry_on_startup=True,
    task_default_queue="system",
    task_routes={
        "system.*": {"queue": "system"},
        "discovery.*": {"queue": "discovery"},
        "matching.*": {"queue": "matching"},
        "visa.*": {"queue": "visa"},
        "application.*": {"queue": "application"},
        "orchestrator.*": {"queue": "orchestrator"},
    },
    beat_schedule={},  # populated from search_configurations in Phase 2
)


@setup_logging.connect
def _configure_celery_logging(**_: object) -> None:
    configure_logging(settings.log_level, settings.log_json)
