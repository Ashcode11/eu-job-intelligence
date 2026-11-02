"""Audit trail for every mutating action."""

from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import AuditLog


def record_audit(
    session: AsyncSession,
    *,
    request: Request | None,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: object | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Add an audit row to the current transaction (committed with the change it describes)."""
    session.add(
        AuditLog(
            occurred_at=datetime.now(UTC),
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            request_id=getattr(request.state, "request_id", None) if request else None,
            ip_address=request.client.host if request and request.client else None,
            details=_jsonable(details or {}),
        )
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_jsonable(v) for v in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)
