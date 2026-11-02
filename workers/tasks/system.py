"""Infrastructure tasks used for health checks and smoke tests."""

from datetime import UTC, datetime

from workers.celery_app import celery_app


@celery_app.task(name="system.ping")
def ping() -> dict[str, str]:
    return {"pong": datetime.now(UTC).isoformat()}
