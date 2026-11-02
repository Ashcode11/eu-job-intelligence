"""Import every model so `Base.metadata` is complete for Alembic and the app."""

from database.models.analysis import JobMatch, SalaryAssessment, VisaAssessment
from database.models.candidate import (
    Candidate,
    CandidateExperience,
    CandidateResume,
    CandidateSkill,
    SearchConfiguration,
)
from database.models.job import Company, Job, JobSource
from database.models.ops import AgentExecution, Application, AuditLog, Notification

__all__ = [
    "AgentExecution",
    "Application",
    "AuditLog",
    "Candidate",
    "CandidateExperience",
    "CandidateResume",
    "CandidateSkill",
    "Company",
    "Job",
    "JobMatch",
    "JobSource",
    "Notification",
    "SalaryAssessment",
    "SearchConfiguration",
    "VisaAssessment",
]
