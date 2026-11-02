"""Applications, agent executions, notifications and the audit log."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from common.enums import (
    ApplicationStatus,
    ExecutionStatus,
    NotificationChannel,
    NotificationKind,
    NotificationStatus,
)
from database.base import Base, Timestamps, UUIDPk, str_enum

if TYPE_CHECKING:
    from database.models.job import Job


class Application(UUIDPk, Timestamps, Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("candidate_id", "job_id"),)

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    status: Mapped[ApplicationStatus] = mapped_column(
        str_enum(ApplicationStatus, "application_status"),
        default=ApplicationStatus.SAVED,
        index=True,
    )
    # [{"from": "saved", "to": "shortlisted", "at": "...", "note": "..."}]
    status_history: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    notes: Mapped[str | None] = mapped_column(Text)

    # Agent-prepared drafts. Nothing here is ever sent automatically.
    tailored_resume_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("candidate_resumes.id", ondelete="SET NULL")
    )
    cover_letter_draft: Mapped[str | None] = mapped_column(Text)
    outreach_message_draft: Mapped[str | None] = mapped_column(Text)
    interview_prep: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    drafts_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    interview_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    job: Mapped["Job"] = relationship()


class AgentExecution(UUIDPk, Base):
    __tablename__ = "agent_executions"
    __table_args__ = (Index("ix_agent_executions_agent_started", "agent_name", "started_at"),)

    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    agent_name: Mapped[str] = mapped_column(String(50))
    task_id: Mapped[str | None] = mapped_column(String(255))
    trigger: Mapped[str] = mapped_column(String(30), default="manual")  # schedule|manual|api
    status: Mapped[ExecutionStatus] = mapped_column(
        str_enum(ExecutionStatus, "execution_status"), default=ExecutionStatus.PENDING
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    items_processed: Mapped[int] = mapped_column(Integer, default=0)
    items_created: Mapped[int] = mapped_column(Integer, default=0)
    items_failed: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_type: Mapped[str | None] = mapped_column(String(200))
    error_message: Mapped[str | None] = mapped_column(Text)
    llm_model: Mapped[str | None] = mapped_column(String(100))
    llm_prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    llm_completion_tokens: Mapped[int | None] = mapped_column(Integer)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    llm_cache_hits: Mapped[int] = mapped_column(Integer, default=0)
    # Agent decision log: [{"job_id": ..., "decision": ..., "reason": ...}]
    decisions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class Notification(UUIDPk, Timestamps, Base):
    __tablename__ = "notifications"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[NotificationChannel] = mapped_column(
        str_enum(NotificationChannel, "notification_channel")
    )
    kind: Mapped[NotificationKind] = mapped_column(str_enum(NotificationKind, "notification_kind"))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    status: Mapped[NotificationStatus] = mapped_column(
        str_enum(NotificationStatus, "notification_status"),
        default=NotificationStatus.PENDING,
        index=True,
    )
    # Prevents the same alert being sent twice, e.g. "high_match:<job_id>:telegram".
    dedup_key: Mapped[str] = mapped_column(String(300), unique=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    actor: Mapped[str] = mapped_column(String(100))  # api key fingerprint, "system", agent name
    action: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str | None] = mapped_column(String(100))
    request_id: Mapped[str | None] = mapped_column(String(64))
    ip_address: Mapped[str | None] = mapped_column(INET)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
