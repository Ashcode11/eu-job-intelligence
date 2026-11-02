"""Candidate aggregate: profile, skills, experience, resumes, search configuration."""

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from common.enums import DEFAULT_MATCH_WEIGHTS, SkillSource
from database.base import EMBEDDING_DIM, Base, Timestamps, UUIDPk, str_enum

if TYPE_CHECKING:
    from database.models.job import Job


class Candidate(UUIDPk, Timestamps, Base):
    __tablename__ = "candidates"

    full_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(50))
    current_designation: Mapped[str | None] = mapped_column(String(200))
    years_experience: Mapped[float | None] = mapped_column(Numeric(4, 1))
    current_organization: Mapped[str | None] = mapped_column(String(200))
    previous_organizations: Mapped[list[str]] = mapped_column(ARRAY(String(200)), default=list)
    summary: Mapped[str | None] = mapped_column(Text)
    current_country: Mapped[str | None] = mapped_column(String(2))  # ISO 3166-1 alpha-2

    # Work authorization: every field is nullable, and NULL means "not provided yet".
    # Agents must treat NULL as unknown and must never infer a value.
    citizenship: Mapped[list[str] | None] = mapped_column(ARRAY(String(2)))
    has_eu_work_authorization: Mapped[bool | None] = mapped_column(Boolean)
    eu_work_authorization_details: Mapped[str | None] = mapped_column(Text)
    requires_visa_sponsorship: Mapped[bool | None] = mapped_column(Boolean)
    open_to_relocation: Mapped[bool | None] = mapped_column(Boolean)
    relocation_notes: Mapped[str | None] = mapped_column(Text)
    notice_period_weeks: Mapped[int | None] = mapped_column(SmallInteger)

    # Preferences
    target_roles: Mapped[list[str]] = mapped_column(ARRAY(String(200)), default=list)
    preferred_countries: Mapped[list[str]] = mapped_column(ARRAY(String(2)), default=list)
    preferred_cities: Mapped[list[str]] = mapped_column(ARRAY(String(100)), default=list)
    remote_preference: Mapped[str | None] = mapped_column(String(20))
    min_salary_eur: Mapped[int | None] = mapped_column(Integer)
    target_salary_eur: Mapped[int | None] = mapped_column(Integer)
    match_weights: Mapped[dict[str, float]] = mapped_column(
        JSONB, default=lambda: dict(DEFAULT_MATCH_WEIGHTS)
    )
    notification_preferences: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    profile_embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))

    skills: Mapped[list["CandidateSkill"]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan", order_by="CandidateSkill.name"
    )
    experiences: Mapped[list["CandidateExperience"]] = relationship(
        back_populates="candidate",
        cascade="all, delete-orphan",
        order_by="CandidateExperience.start_date.desc()",
    )
    resumes: Mapped[list["CandidateResume"]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan"
    )


class CandidateSkill(UUIDPk, Timestamps, Base):
    __tablename__ = "candidate_skills"
    __table_args__ = (
        Index(
            "uq_candidate_skills_candidate_lower_name",
            "candidate_id",
            text("lower(name)"),
            unique=True,
        ),
    )

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    category: Mapped[str | None] = mapped_column(String(50))  # cloud, iac, container, ci_cd, ...
    proficiency: Mapped[int | None] = mapped_column(SmallInteger)  # 1..5
    years: Mapped[float | None] = mapped_column(Numeric(4, 1))
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String(100)), default=list)
    source: Mapped[SkillSource] = mapped_column(
        str_enum(SkillSource, "skill_source"), default=SkillSource.MANUAL
    )

    candidate: Mapped[Candidate] = relationship(back_populates="skills")


class CandidateExperience(UUIDPk, Timestamps, Base):
    __tablename__ = "candidate_experiences"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )
    organization: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(200))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str | None] = mapped_column(Text)
    highlights: Mapped[list[str]] = mapped_column(JSONB, default=list)
    technologies: Mapped[list[str]] = mapped_column(ARRAY(String(100)), default=list)

    candidate: Mapped[Candidate] = relationship(back_populates="experiences")


class CandidateResume(UUIDPk, Timestamps, Base):
    __tablename__ = "candidate_resumes"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )
    version_label: Mapped[str] = mapped_column(String(100))
    original_filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    storage_path: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)

    # Tailored versions point at the resume they were derived from and the target job.
    parent_resume_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("candidate_resumes.id", ondelete="SET NULL")
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))

    parsed_text: Mapped[str | None] = mapped_column(Text)
    parsed_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parse_error: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))

    candidate: Mapped[Candidate] = relationship(back_populates="resumes")
    job: Mapped["Job | None"] = relationship()

    __table_args__ = (
        UniqueConstraint("candidate_id", "sha256"),
        Index(
            "ix_candidate_resumes_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class SearchConfiguration(UUIDPk, Timestamps, Base):
    __tablename__ = "search_configurations"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    keywords: Mapped[list[str]] = mapped_column(ARRAY(String(200)), default=list)
    excluded_keywords: Mapped[list[str]] = mapped_column(ARRAY(String(200)), default=list)
    countries: Mapped[list[str]] = mapped_column(ARRAY(String(2)), default=list)
    source_keys: Mapped[list[str]] = mapped_column(ARRAY(String(50)), default=list)  # [] = all
    schedule_cron: Mapped[str] = mapped_column(String(100), default="0 6 * * *")
    max_results_per_source: Mapped[int] = mapped_column(Integer, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("candidate_id", "name"),)
