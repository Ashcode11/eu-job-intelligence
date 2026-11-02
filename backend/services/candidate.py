"""Candidate profile helpers."""

from database.models import Candidate

# Fields the matching and visa agents rely on. Missing values are reported to the user
# so they can be filled in rather than guessed.
_REQUIRED_FOR_AGENTS: dict[str, str] = {
    "citizenship": "Citizenship (needed for visa analysis)",
    "has_eu_work_authorization": "Existing EU work authorization",
    "requires_visa_sponsorship": "Whether you need visa sponsorship",
    "open_to_relocation": "Relocation availability",
    "current_country": "Current country of residence",
    "min_salary_eur": "Minimum acceptable salary (EUR)",
    "preferred_countries": "Preferred countries",
    "target_roles": "Target roles",
}


def missing_profile_fields(candidate: Candidate) -> list[str]:
    missing = []
    for attr, label in _REQUIRED_FOR_AGENTS.items():
        value = getattr(candidate, attr)
        if value is None or value == []:
            missing.append(label)
    if not candidate.skills:
        missing.append("Skills inventory")
    if not candidate.resumes:
        missing.append("At least one resume (PDF or DOCX)")
    return missing
