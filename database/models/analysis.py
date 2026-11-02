"""Agent outputs: match scores, visa assessments, salary assessments."""

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from common.enums import InterviewLikelihood, VisaClassification
from database.base import Base, Timestamps, UUIDPk, str_enum

if TYPE_CHECKING:
    from database.models.job import Job


class JobMatch(UUIDPk, Timestamps, Base):
    __tablename__ = "job_matches"
    __table_args__ = (
        UniqueConstraint("job_id", "candidate_id"),
        CheckConstraint("overall_score >= 0 AND overall_score <= 100", name="score_range"),
        Index("ix_job_matches_candidate_score", "candidate_id", "overall_score"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    resume_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("candidate_resumes.id", ondelete="SET NULL")
    )

    overall_score: Mapped[float] = mapped_column(Numeric(5, 2))
    # {"technical_skills": 82.5, "experience": 90, ...}, each component on a 0-100 scale
    component_scores: Mapped[dict[str, float]] = mapped_column(JSONB, default=dict)
    weights_used: Mapped[dict[str, float]] = mapped_column(JSONB, default=dict)
    semantic_similarity: Mapped[float | None] = mapped_column(Numeric(5, 4))

    matched_skills: Mapped[list[str]] = mapped_column(ARRAY(String(100)), default=list)
    missing_skills: Mapped[list[str]] = mapped_column(ARRAY(String(100)), default=list)
    experience_gaps: Mapped[list[str]] = mapped_column(JSONB, default=list)
    reasons_for: Mapped[list[str]] = mapped_column(JSONB, default=list)
    reasons_against: Mapped[list[str]] = mapped_column(JSONB, default=list)
    recommended: Mapped[bool] = mapped_column(Boolean, default=False)

    # Heuristic estimate only, labelled as such in the API and UI.
    interview_likelihood: Mapped[InterviewLikelihood | None] = mapped_column(
        str_enum(InterviewLikelihood, "interview_likelihood")
    )

    scorer_version: Mapped[str] = mapped_column(String(20))
    input_hash: Mapped[str] = mapped_column(String(64))  # skip recompute when unchanged
    llm_model: Mapped[str | None] = mapped_column(String(100))

    job: Mapped["Job"] = relationship(back_populates="matches")


class VisaAssessment(UUIDPk, Timestamps, Base):
    __tablename__ = "visa_assessments"

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), unique=True
    )
    classification: Mapped[VisaClassification] = mapped_column(
        str_enum(VisaClassification, "visa_classification"), index=True
    )
    # Tri-state signals: True/False when the text says so, NULL when it says nothing.
    mentions_sponsorship: Mapped[bool | None] = mapped_column(Boolean)
    relocation_support: Mapped[bool | None] = mapped_column(Boolean)
    non_eu_applicants_accepted: Mapped[bool | None] = mapped_column(Boolean)
    eu_authorization_required: Mapped[bool | None] = mapped_column(Boolean)
    employer_documented_sponsor: Mapped[bool | None] = mapped_column(Boolean)

    # [{"url": ..., "quote": ..., "signal": "sponsorship_positive"}]
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # [{"name": "EU Blue Card", "country": "DE", "notes": ..., "reference_url": ...}]
    country_pathways: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2))
    rationale: Mapped[str | None] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(20))  # rules | rules+llm
    analyzer_version: Mapped[str] = mapped_column(String(20))
    input_hash: Mapped[str] = mapped_column(String(64))
    llm_model: Mapped[str | None] = mapped_column(String(100))

    job: Mapped["Job"] = relationship(back_populates="visa_assessment")


class SalaryAssessment(UUIDPk, Timestamps, Base):
    __tablename__ = "salary_assessments"

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), unique=True
    )

    # Actual: derived only from what the posting states, normalised to gross annual EUR.
    has_actual_salary: Mapped[bool] = mapped_column(Boolean, default=False)
    actual_min_eur: Mapped[float | None] = mapped_column(Numeric(12, 2))
    actual_max_eur: Mapped[float | None] = mapped_column(Numeric(12, 2))
    source_currency: Mapped[str | None] = mapped_column(String(3))
    fx_rate_to_eur: Mapped[float | None] = mapped_column(Numeric(12, 6))

    # Estimated: from benchmarks when no salary is posted. Kept strictly separate.
    estimated_min_eur: Mapped[float | None] = mapped_column(Numeric(12, 2))
    estimated_max_eur: Mapped[float | None] = mapped_column(Numeric(12, 2))
    benchmark_median_eur: Mapped[float | None] = mapped_column(Numeric(12, 2))
    benchmark_source: Mapped[str | None] = mapped_column(String(300))

    est_net_annual_eur: Mapped[float | None] = mapped_column(Numeric(12, 2))
    est_living_cost_annual_eur: Mapped[float | None] = mapped_column(Numeric(12, 2))
    est_savings_annual_eur: Mapped[float | None] = mapped_column(Numeric(12, 2))
    meets_candidate_minimum: Mapped[bool | None] = mapped_column(Boolean)
    # Every estimate lists its inputs: tax model, household, rent band, FX date, ...
    assumptions: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    analyzer_version: Mapped[str] = mapped_column(String(20))
    input_hash: Mapped[str] = mapped_column(String(64))

    job: Mapped["Job"] = relationship(back_populates="salary_assessment")
