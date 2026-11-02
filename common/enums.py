"""Domain enums shared by the database, API and agents."""

from enum import StrEnum


class JobStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CLOSED = "closed"


class RemoteType(StrEnum):
    ONSITE = "onsite"
    HYBRID = "hybrid"
    REMOTE = "remote"
    UNKNOWN = "unknown"


class SourceType(StrEnum):
    API = "api"
    RSS = "rss"
    ATS_BOARD = "ats_board"  # Greenhouse / Lever public boards
    CAREER_PAGE = "career_page"
    MANUAL = "manual"


class VisaClassification(StrEnum):
    """The five visa categories, in order of how favourable they are to the candidate."""

    EXPLICIT_SPONSORSHIP = "explicit_sponsorship"
    POTENTIAL_SPONSORSHIP = "potential_sponsorship"
    EU_AUTHORIZATION_REQUIRED = "eu_authorization_required"
    NOT_MENTIONED = "not_mentioned"
    NOT_SUITABLE = "not_suitable"


class InterviewLikelihood(StrEnum):
    """A heuristic estimate, explicitly not a prediction backed by hiring data."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ApplicationStatus(StrEnum):
    SAVED = "saved"
    SHORTLISTED = "shortlisted"
    PREPARED = "prepared"
    APPLIED = "applied"
    INTERVIEW_SCHEDULED = "interview_scheduled"
    REJECTED = "rejected"
    OFFER_RECEIVED = "offer_received"
    WITHDRAWN = "withdrawn"


class ExecutionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRYING = "retrying"
    SKIPPED = "skipped"


class NotificationChannel(StrEnum):
    DASHBOARD = "dashboard"
    EMAIL = "email"
    TELEGRAM = "telegram"


class NotificationKind(StrEnum):
    NEW_JOBS = "new_jobs"
    HIGH_MATCH = "high_match"
    VISA_SPONSORSHIP = "visa_sponsorship"
    DAILY_DIGEST = "daily_digest"
    SYSTEM = "system"


class NotificationStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    READ = "read"


class SkillSource(StrEnum):
    MANUAL = "manual"
    CV = "cv"
    INFERRED = "inferred"


DEFAULT_MATCH_WEIGHTS: dict[str, float] = {
    "technical_skills": 0.30,
    "experience": 0.25,
    "responsibilities": 0.15,
    "seniority": 0.10,
    "location": 0.10,
    "compensation": 0.10,
}
