"""Candidate profile request/response models."""

import uuid
from datetime import date, datetime
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
)

from common.enums import DEFAULT_MATCH_WEIGHTS, SkillSource

CountryCode = Annotated[
    str,
    BeforeValidator(lambda v: v.strip().upper() if isinstance(v, str) else v),
    StringConstraints(pattern=r"^[A-Z]{2}$"),
]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _validate_weights(v: dict[str, float] | None) -> dict[str, float] | None:
    if v is None:
        return v
    unknown = set(v) - set(DEFAULT_MATCH_WEIGHTS)
    missing = set(DEFAULT_MATCH_WEIGHTS) - set(v)
    if unknown or missing:
        raise ValueError(
            f"weights must have exactly the keys {sorted(DEFAULT_MATCH_WEIGHTS)}; "
            f"unknown={sorted(unknown)} missing={sorted(missing)}"
        )
    if any(w < 0 for w in v.values()):
        raise ValueError("weights must be non-negative")
    if abs(sum(v.values()) - 1.0) > 0.001:
        raise ValueError(f"weights must sum to 1.0 (got {sum(v.values()):.3f})")
    return v


class CandidateBase(BaseModel):
    full_name: ShortText | None = None
    email: EmailStr | None = None
    phone: Annotated[str, StringConstraints(max_length=50)] | None = None
    current_designation: ShortText | None = None
    years_experience: float | None = Field(default=None, ge=0, le=60)
    current_organization: ShortText | None = None
    previous_organizations: list[ShortText] | None = None
    summary: Annotated[str, StringConstraints(max_length=5000)] | None = None
    current_country: CountryCode | None = None

    citizenship: list[CountryCode] | None = None
    has_eu_work_authorization: bool | None = None
    eu_work_authorization_details: Annotated[str, StringConstraints(max_length=2000)] | None = None
    requires_visa_sponsorship: bool | None = None
    open_to_relocation: bool | None = None
    relocation_notes: Annotated[str, StringConstraints(max_length=2000)] | None = None
    notice_period_weeks: int | None = Field(default=None, ge=0, le=52)

    target_roles: list[ShortText] | None = None
    preferred_countries: list[CountryCode] | None = None
    preferred_cities: list[ShortText] | None = None
    remote_preference: (
        Annotated[str, StringConstraints(pattern=r"^(onsite|hybrid|remote|any)$")] | None
    ) = None
    min_salary_eur: int | None = Field(default=None, ge=0, le=1_000_000)
    target_salary_eur: int | None = Field(default=None, ge=0, le=1_000_000)
    match_weights: dict[str, float] | None = None
    notification_preferences: dict[str, Any] | None = None

    _weights = field_validator("match_weights")(_validate_weights)


class CandidateCreate(CandidateBase):
    full_name: ShortText


class CandidateUpdate(CandidateBase):
    """PATCH semantics: only fields present in the request body are changed."""


class SkillBase(BaseModel):
    name: ShortText
    category: Annotated[str, StringConstraints(max_length=50)] | None = None
    proficiency: int | None = Field(default=None, ge=1, le=5)
    years: float | None = Field(default=None, ge=0, le=60)
    aliases: list[ShortText] = Field(default_factory=list)


class SkillCreate(SkillBase):
    pass


class SkillUpdate(BaseModel):
    name: ShortText | None = None
    category: Annotated[str, StringConstraints(max_length=50)] | None = None
    proficiency: int | None = Field(default=None, ge=1, le=5)
    years: float | None = Field(default=None, ge=0, le=60)
    aliases: list[ShortText] | None = None


class SkillRead(SkillBase, ORMModel):
    id: uuid.UUID
    source: SkillSource


class ExperienceBase(BaseModel):
    organization: ShortText
    title: ShortText
    location: ShortText | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool = False
    description: Annotated[str, StringConstraints(max_length=10000)] | None = None
    highlights: list[Annotated[str, StringConstraints(max_length=1000)]] = Field(
        default_factory=list
    )
    technologies: list[ShortText] = Field(default_factory=list)


class ExperienceCreate(ExperienceBase):
    pass


class ExperienceRead(ExperienceBase, ORMModel):
    id: uuid.UUID


class ResumeRead(ORMModel):
    id: uuid.UUID
    version_label: str
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    is_primary: bool
    parent_resume_id: uuid.UUID | None
    job_id: uuid.UUID | None
    parsed_at: datetime | None
    parse_error: str | None
    created_at: datetime


class CandidateRead(ORMModel):
    id: uuid.UUID
    full_name: str
    email: str | None
    phone: str | None
    current_designation: str | None
    years_experience: float | None
    current_organization: str | None
    previous_organizations: list[str]
    summary: str | None
    current_country: str | None
    citizenship: list[str] | None
    has_eu_work_authorization: bool | None
    eu_work_authorization_details: str | None
    requires_visa_sponsorship: bool | None
    open_to_relocation: bool | None
    relocation_notes: str | None
    notice_period_weeks: int | None
    target_roles: list[str]
    preferred_countries: list[str]
    preferred_cities: list[str]
    remote_preference: str | None
    min_salary_eur: int | None
    target_salary_eur: int | None
    match_weights: dict[str, float]
    notification_preferences: dict[str, Any]
    skills: list[SkillRead]
    experiences: list[ExperienceRead]
    resumes: list[ResumeRead]
    profile_completeness: list[str] = Field(
        default_factory=list,
        description="Fields the agents need but that have not been provided yet.",
    )
    created_at: datetime
    updated_at: datetime


class SearchConfigBase(BaseModel):
    name: ShortText
    keywords: list[ShortText] = Field(default_factory=list)
    excluded_keywords: list[ShortText] = Field(default_factory=list)
    countries: list[CountryCode] = Field(default_factory=list)
    source_keys: list[Annotated[str, StringConstraints(max_length=50)]] = Field(
        default_factory=list
    )
    schedule_cron: Annotated[
        str, StringConstraints(pattern=r"^(\S+\s+){4}\S+$", max_length=100)
    ] = "0 6 * * *"
    max_results_per_source: int = Field(default=100, ge=1, le=1000)
    enabled: bool = True


class SearchConfigCreate(SearchConfigBase):
    pass


class SearchConfigUpdate(BaseModel):
    name: ShortText | None = None
    keywords: list[ShortText] | None = None
    excluded_keywords: list[ShortText] | None = None
    countries: list[CountryCode] | None = None
    source_keys: list[Annotated[str, StringConstraints(max_length=50)]] | None = None
    schedule_cron: (
        Annotated[str, StringConstraints(pattern=r"^(\S+\s+){4}\S+$", max_length=100)] | None
    ) = None
    max_results_per_source: int | None = Field(default=None, ge=1, le=1000)
    enabled: bool | None = None


class SearchConfigRead(SearchConfigBase, ORMModel):
    id: uuid.UUID
    last_run_at: datetime | None
