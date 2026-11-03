"""Enqueue Celery tasks from async routes without blocking the event loop."""

import asyncio
from typing import Any

from fastapi import HTTPException, status


async def enqueue(task: Any, *args: Any, **kwargs: Any) -> str:
    try:
        result = await asyncio.to_thread(task.apply_async, args=list(args), kwargs=kwargs)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Task queue unavailable: {type(exc).__name__}"
        ) from exc
    return result.id
