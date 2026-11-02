"""Job, analysis, application and monitoring response models."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from common.enums import (
    ApplicationStatus,
    ExecutionStatus,
    InterviewLikelihood,
    JobStatus,
    RemoteType,
    VisaClassification,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CompanyRead(ORMModel):
    id: uuid.UUID
    name: str
    website: str | None
    careers_url: str | None
    documented_sponsor: bool | None


class MatchRead(ORMModel):
    overall_score: float
    component_scores: dict[str, float]
    weights_used: dict[str, float]
    semantic_similarity: float | None
    matched_skills: list[str]
    missing_skills: list[str]
    experience_gaps: list[str]
    reasons_for: list[str]
    reasons_against: list[str]
    recommended: bool
    interview_likelihood: InterviewLikelihood | None
    interview_likelihood_note: str = (
        "Heuristic estimate from profile overlap. Not a prediction based on hiring data."
    )
    scorer_version: str
    updated_at: datetime


class VisaRead(ORMModel):
    classification: VisaClassification
    mentions_sponsorship: bool | None
    relocation_support: bool | None
    non_eu_applicants_accepted: bool | None
    eu_authorization_required: bool | None
    employer_documented_sponsor: bool | None
    evidence: list[dict[str, Any]]
    country_pathways: list[dict[str, Any]]
    confidence: float | None
    rationale: str | None
    method: str
    updated_at: datetime


class SalaryRead(ORMModel):
    has_actual_salary: bool
    actual_min_eur: float | None
    actual_max_eur: float | None
    source_currency: str | None
    estimated_min_eur: float | None
    estimated_max_eur: float | None
    benchmark_median_eur: float | None
    benchmark_source: str | None
    est_net_annual_eur: float | None
    est_living_cost_annual_eur: float | None
    est_savings_annual_eur: float | None
    meets_candidate_minimum: bool | None
    assumptions: dict[str, Any]
    updated_at: datetime


class JobSummary(ORMModel):
    id: uuid.UUID
    title: str
    company_name: str | None
    country: str | None
    city: str | None
    remote_type: RemoteType
    posted_at: datetime | None
    status: JobStatus
    url: str
    source_key: str
    salary_min: float | None
    salary_max: float | None
    salary_currency: str | None
    match_score: float | None
    visa_classification: VisaClassification | None
    application_status: ApplicationStatus | None


class JobDetail(JobSummary):
    apply_url: str | None
    description: str
    location_raw: str | None
    employment_type: str | None
    seniority: str | None
    experience_min_years: float | None
    required_skills: list[str]
    salary_raw: str | None
    salary_period: str | None
    discovered_at: datetime
    last_seen_at: datetime
    expires_at: datetime | None
    company: CompanyRead | None
    match: MatchRead | None
    visa: VisaRead | None
    salary: SalaryRead | None


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


JobSort = Literal["match_score", "posted_at", "salary", "discovered_at"]


class ApplicationCreate(BaseModel):
    job_id: uuid.UUID
    status: ApplicationStatus = ApplicationStatus.SAVED
    notes: Annotated[str, StringConstraints(max_length=10000)] | None = None


class ApplicationUpdate(BaseModel):
    status: ApplicationStatus | None = None
    notes: Annotated[str, StringConstraints(max_length=10000)] | None = None
    interview_at: datetime | None = None
    status_note: Annotated[str, StringConstraints(max_length=1000)] | None = None


class ApplicationRead(ORMModel):
    id: uuid.UUID
    job_id: uuid.UUID
    status: ApplicationStatus
    status_history: list[dict[str, Any]]
    notes: str | None
    tailored_resume_id: uuid.UUID | None
    cover_letter_draft: str | None
    outreach_message_draft: str | None
    interview_prep: dict[str, Any] | None
    drafts_approved_at: datetime | None
    applied_at: datetime | None
    interview_at: datetime | None
    created_at: datetime
    updated_at: datetime
    job_title: str | None = None
    company_name: str | None = None
    country: str | None = None


class AgentExecutionRead(ORMModel):
    id: uuid.UUID
    workflow_run_id: uuid.UUID | None
    agent_name: str
    trigger: str
    status: ExecutionStatus
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    items_processed: int
    items_created: int
    items_failed: int
    retry_count: int
    error_type: str | None
    error_message: str | None
    llm_model: str | None
    llm_prompt_tokens: int | None
    llm_completion_tokens: int | None
    llm_calls: int
    llm_cache_hits: int


class AgentSummary(BaseModel):
    agent_name: str
    last_status: ExecutionStatus | None
    last_started_at: datetime | None
    last_duration_ms: int | None
    runs_24h: int
    failures_24h: int
    items_created_24h: int
    llm_tokens_24h: int


class OverviewStats(BaseModel):
    total_jobs: int
    active_jobs: int
    matching_jobs: int = Field(description="Active jobs scoring >= the match threshold")
    high_match_jobs: int
    visa_sponsorship_jobs: int = Field(description="Explicit or potential sponsorship")
    applications_submitted: int
    applications_pending: int
    match_threshold: float
    high_match_threshold: float
