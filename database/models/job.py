"""Job aggregate: sources, companies, job postings."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from common.enums import JobStatus, RemoteType, SourceType
from database.base import EMBEDDING_DIM, Base, Timestamps, UUIDPk, str_enum

if TYPE_CHECKING:
    from database.models.analysis import JobMatch, SalaryAssessment, VisaAssessment


class JobSource(UUIDPk, Timestamps, Base):
    __tablename__ = "job_sources"

    key: Mapped[str] = mapped_column(String(50), unique=True)  # e.g. "greenhouse:acme"
    name: Mapped[str] = mapped_column(String(200))
    source_type: Mapped[SourceType] = mapped_column(str_enum(SourceType, "source_type"))
    connector: Mapped[str] = mapped_column(String(50))  # connector implementation name
    base_url: Mapped[str | None] = mapped_column(String(500))
    terms_url: Mapped[str | None] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    respects_robots_txt: Mapped[bool] = mapped_column(Boolean, default=True)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=30)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # non-secret settings
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class Company(UUIDPk, Timestamps, Base):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(200))
    normalized_name: Mapped[str] = mapped_column(String(200), unique=True)
    website: Mapped[str | None] = mapped_column(String(500))
    careers_url: Mapped[str | None] = mapped_column(String(500))
    headquarters_country: Mapped[str | None] = mapped_column(String(2))
    industry: Mapped[str | None] = mapped_column(String(100))
    size_band: Mapped[str | None] = mapped_column(String(50))
    ats_type: Mapped[str | None] = mapped_column(String(50))  # greenhouse, lever, ...
    ats_identifier: Mapped[str | None] = mapped_column(String(200))
    # Publicly documented sponsorship evidence (e.g. listed as a recognised sponsor in
    # the Dutch IND public register). Never inferred from employee nationality.
    documented_sponsor: Mapped[bool | None] = mapped_column(Boolean)
    sponsorship_evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    jobs: Mapped[list["Job"]] = relationship(back_populates="company")


class Job(UUIDPk, Timestamps, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id"),
        Index("ix_jobs_status_country", "status", "country"),
        Index("ix_jobs_posted_at", "posted_at"),
        Index(
            "ix_jobs_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job_sources.id", ondelete="RESTRICT"))
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    external_id: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(String(1000))
    apply_url: Mapped[str | None] = mapped_column(String(1000))

    title: Mapped[str] = mapped_column(String(300))
    normalized_title: Mapped[str] = mapped_column(String(300), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    description_html: Mapped[str | None] = mapped_column(Text)

    country: Mapped[str | None] = mapped_column(String(2))
    city: Mapped[str | None] = mapped_column(String(100))
    location_raw: Mapped[str | None] = mapped_column(String(300))
    remote_type: Mapped[RemoteType] = mapped_column(
        str_enum(RemoteType, "remote_type"), default=RemoteType.UNKNOWN
    )
    employment_type: Mapped[str | None] = mapped_column(String(50))
    seniority: Mapped[str | None] = mapped_column(String(50))
    experience_min_years: Mapped[float | None] = mapped_column(Numeric(4, 1))
    required_skills: Mapped[list[str]] = mapped_column(ARRAY(String(100)), default=list)

    # Salary exactly as advertised. Normalised / estimated values live in salary_assessments.
    salary_min: Mapped[float | None] = mapped_column(Numeric(12, 2))
    salary_max: Mapped[float | None] = mapped_column(Numeric(12, 2))
    salary_currency: Mapped[str | None] = mapped_column(String(3))
    salary_period: Mapped[str | None] = mapped_column(String(20))  # year, month, day, hour
    salary_raw: Mapped[str | None] = mapped_column(String(300))

    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[JobStatus] = mapped_column(
        str_enum(JobStatus, "job_status"), default=JobStatus.ACTIVE
    )

    # Cross-source duplicate detection and change detection.
    dedup_hash: Mapped[str] = mapped_column(String(64), index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    canonical_job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL")
    )

    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    source: Mapped[JobSource] = relationship()
    company: Mapped[Company | None] = relationship(back_populates="jobs")
    matches: Mapped[list["JobMatch"]] = relationship(back_populates="job")
    visa_assessment: Mapped["VisaAssessment | None"] = relationship(
        back_populates="job", uselist=False
    )
    salary_assessment: Mapped["SalaryAssessment | None"] = relationship(
        back_populates="job", uselist=False
    )
