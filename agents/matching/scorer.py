"""Job Matching Agent: deterministic component scores + semantic similarity.

Each component is scored 0-100 by explicit rules. Embedding similarity feeds only the
"responsibilities" component and is optional. The LLM never decides the score. Weights come
from the candidate profile (default 30/25/15/10/10/10).
"""

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any

from agents.skills import by_name, canonical, extract_skills
from common.enums import DEFAULT_MATCH_WEIGHTS, InterviewLikelihood, RemoteType
from common.enums import VisaClassification as VC
from connectors.text import title_matches

SCORER_VERSION = "match-1.0"
_PROFICIENCY_FACTOR = {1: 0.5, 2: 0.65, 3: 0.8, 4: 0.92, 5: 1.0}
_SPECIFIC_CATEGORIES = {"cloud", "iac", "containers", "ci_cd", "database", "config_mgmt"}


@dataclass
class CandidateFacts:
    years_experience: float | None
    skills: dict[str, int | None]  # canonical name -> proficiency (1-5 or None)
    target_roles: list[str]
    preferred_countries: list[str]
    current_country: str | None
    open_to_relocation: bool | None
    requires_visa_sponsorship: bool | None
    has_eu_work_authorization: bool | None
    min_salary_eur: int | None
    designation: str | None
    weights: dict[str, float]
    embedding: list[float] | None = None

    def fingerprint(self) -> str:
        data = {k: v for k, v in self.__dict__.items() if k != "embedding"}
        data["has_embedding"] = self.embedding is not None
        return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


@dataclass
class JobFacts:
    title: str
    description: str
    required_skills: list[str]
    experience_min_years: float | None
    seniority: str | None
    country: str | None
    remote_type: RemoteType
    content_hash: str
    embedding: list[float] | None = None


@dataclass
class VisaFacts:
    classification: VC | None
    local_language_required: bool = False
    input_hash: str = ""


@dataclass
class SalaryFacts:
    has_actual: bool
    actual_max_eur: float | None
    estimated_max_eur: float | None
    input_hash: str = ""


@dataclass
class MatchResult:
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
    interview_likelihood: InterviewLikelihood
    input_hash: str
    notes: dict[str, Any] = field(default_factory=dict)


def job_skills(job: JobFacts) -> dict[str, float]:
    """Skill -> importance. Skills in the title count double, repeated mentions 1.5x."""
    found = extract_skills(f"{job.description}")
    in_title = extract_skills(job.title)
    for s in job.required_skills:
        found.setdefault(canonical(s), 1)
    weights: dict[str, float] = {}
    for name, mentions in found.items():
        w = 1.0 + (0.5 if mentions > 1 else 0.0)
        if name in in_title:
            w *= 2
        weights[name] = w
    for name in in_title:
        weights.setdefault(name, 2.0)
    return weights


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def input_hash(cand: CandidateFacts, job: JobFacts, visa: VisaFacts, sal: SalaryFacts) -> str:
    return hashlib.sha256(
        "|".join(
            [
                SCORER_VERSION,
                cand.fingerprint(),
                job.content_hash,
                str(job.embedding is not None),
                visa.input_hash,
                str(visa.classification),
                sal.input_hash,
            ]
        ).encode()
    ).hexdigest()


def score(cand: CandidateFacts, job: JobFacts, visa: VisaFacts, sal: SalaryFacts) -> MatchResult:
    weights = cand.weights or dict(DEFAULT_MATCH_WEIGHTS)
    pros: list[str] = []
    cons: list[str] = []
    notes: dict[str, Any] = {}
    cand_skills = {canonical(k).lower(): v for k, v in cand.skills.items()}
    cand_categories = {s.category for k in cand_skills if (s := by_name().get(k))}

    # 1. Technical skills
    js = job_skills(job)
    matched, missing, transferable = [], [], []
    got = total = 0.0
    for name, w in js.items():
        total += w
        if name.lower() in cand_skills:
            got += w * _PROFICIENCY_FACTOR.get(cand_skills[name.lower()] or 0, 0.8)
            matched.append(name)
        else:
            cat = by_name().get(name.lower())
            if cat and cat.category in _SPECIFIC_CATEGORIES and cat.category in cand_categories:
                got += w * 0.4  # e.g. job wants GCP, candidate knows AWS + Azure
                transferable.append(name)
            missing.append(name)
    semantic = (
        cosine(cand.embedding, job.embedding)
        if cand.embedding is not None and job.embedding is not None
        else None
    )
    if total:
        tech = 100 * got / total
    else:
        tech = 50.0
        notes["technical_skills"] = "no recognisable skills in the posting; neutral score"
    if matched:
        pros.append(
            f"Matches {len(matched)} of {len(js)} skills the job mentions "
            f"({', '.join(sorted(matched, key=lambda n: -js[n])[:6])})."
        )
    key_missing = [m for m in sorted(missing, key=lambda n: -js[n]) if js[m] >= 2][:5]
    if key_missing:
        cons.append(f"Key skills not in your profile: {', '.join(key_missing)}.")
    if transferable:
        notes["transferable"] = transferable

    # 2. Experience
    gaps: list[str] = []
    if cand.years_experience is None:
        exp = 50.0
        gaps.append("Your years of experience are not set in your profile.")
    elif job.experience_min_years is None:
        exp = 80.0
    elif cand.years_experience >= job.experience_min_years:
        exp = 100.0
        pros.append(
            f"{cand.years_experience:g} years of experience meets the "
            f"{job.experience_min_years:g}+ years asked."
        )
    else:
        deficit = job.experience_min_years - cand.years_experience
        exp = max(0.0, 100 - 20 * deficit)
        gaps.append(
            f"Asks for {job.experience_min_years:g}+ years; you have {cand.years_experience:g}."
        )
        cons.append(gaps[-1])

    # 3. Responsibilities: semantic similarity when available, else skill-category coverage
    if semantic is not None:
        resp = _clamp((semantic - 0.45) / (0.85 - 0.45) * 100)
        notes["responsibilities_method"] = "embedding similarity"
    else:
        job_cats = {s.category for n in js if (s := by_name().get(n.lower()))}
        resp = 100 * len(job_cats & cand_categories) / len(job_cats) if job_cats else 50.0
        notes["responsibilities_method"] = "skill-category coverage (no embeddings available)"
    if resp >= 75:
        pros.append("The role's responsibilities closely resemble your experience.")

    # 4. Seniority
    sen = _seniority_score(cand, job)
    if sen < 60:
        cons.append(f"Seniority mismatch: role is '{job.seniority or 'unspecified'}'.")
    role_aligned = title_matches(job.title, cand.target_roles) if cand.target_roles else None
    if role_aligned:
        pros.append("Title matches one of your target roles.")

    # 5. Location, relocation and work authorization
    loc, blocker = _location_score(cand, job, visa, pros, cons)

    # 6. Compensation
    comp = _compensation_score(cand, sal, pros, cons)

    components = {
        "technical_skills": tech,
        "experience": exp,
        "responsibilities": resp,
        "seniority": sen,
        "location": loc,
        "compensation": comp,
    }
    overall = sum(weights.get(k, 0) * v for k, v in components.items())
    if blocker == "hard":
        overall = min(overall, 20.0)
    elif blocker == "authorization":
        overall = min(overall, 35.0)
    overall = round(_clamp(overall), 2)

    recommended = overall >= 60 and blocker is None
    if not blocker and overall >= 75 and tech >= 70:
        likelihood = InterviewLikelihood.HIGH
    elif not blocker and overall >= 55:
        likelihood = InterviewLikelihood.MEDIUM
    else:
        likelihood = InterviewLikelihood.LOW

    return MatchResult(
        overall_score=overall,
        component_scores={k: round(v, 1) for k, v in components.items()},
        weights_used=weights,
        semantic_similarity=round(semantic, 4) if semantic is not None else None,
        matched_skills=sorted(matched),
        missing_skills=sorted(missing, key=lambda n: -js[n]),
        experience_gaps=gaps,
        reasons_for=pros,
        reasons_against=cons,
        recommended=recommended,
        interview_likelihood=likelihood,
        input_hash=input_hash(cand, job, visa, sal),
        notes=notes,
    )


def _seniority_score(cand: CandidateFacts, job: JobFacts) -> float:
    years = cand.years_experience
    wants_mgmt = any("manager" in r.lower() or "head" in r.lower() for r in cand.target_roles)
    s = (job.seniority or "").lower()
    if years is None:
        return 60.0
    if s == "junior":
        return 30.0
    if s in ("", "mid"):
        return 70.0 if years >= 8 else 85.0
    if s == "senior":
        return 100.0 if years >= 6 else 60.0
    if s in ("lead", "staff", "principal"):
        return 100.0 if years >= 10 else 70.0 if years >= 7 else 45.0
    if s in ("manager", "head", "director"):
        base = 90.0 if wants_mgmt else 65.0
        return base if years >= 10 else base - 25
    return 70.0


def _location_score(
    cand: CandidateFacts, job: JobFacts, visa: VisaFacts, pros: list[str], cons: list[str]
) -> tuple[float, str | None]:
    blocker: str | None = None
    if job.country and job.country in cand.preferred_countries:
        score = 100.0
    elif job.country is None:
        score = 85.0  # Europe-wide remote
    else:
        score = 40.0
        cons.append(f"{job.country} is not one of your preferred countries.")
    abroad = job.country is not None and job.country != cand.current_country
    if abroad and job.remote_type != RemoteType.REMOTE and cand.open_to_relocation is False:
        score = min(score, 20.0)
        cons.append("Requires relocation, and your profile says you are not open to it.")

    cls = visa.classification
    if cls == VC.NOT_SUITABLE and not cand.has_eu_work_authorization:
        blocker = "hard"
        cons.append("Requires a specific citizenship or security clearance.")
        score = 0.0
    elif cls == VC.NOT_SUITABLE:
        score *= 0.5
        cons.append("May require a specific citizenship or security clearance.")
    elif cand.requires_visa_sponsorship:
        factor = {
            VC.EXPLICIT_SPONSORSHIP: 1.0,
            VC.POTENTIAL_SPONSORSHIP: 0.8,
            VC.NOT_MENTIONED: 0.55,
            VC.EU_AUTHORIZATION_REQUIRED: 0.05,
        }.get(cls, 0.6)
        score *= factor
        if cls == VC.EXPLICIT_SPONSORSHIP:
            pros.append("The posting explicitly offers visa sponsorship.")
        elif cls == VC.POTENTIAL_SPONSORSHIP:
            pros.append(
                "Some signs of sponsorship or relocation support. Confirm with the recruiter."
            )
        elif cls == VC.EU_AUTHORIZATION_REQUIRED:
            blocker = "authorization"
            cons.append(
                "Requires existing EU work authorization, which your profile says you don't have."
            )
        else:
            cons.append("Sponsorship is not mentioned. Ask before investing time.")
    elif cand.requires_visa_sponsorship is None and cls == VC.EU_AUTHORIZATION_REQUIRED:
        cons.append(
            "Requires existing EU work authorization. Set your authorization in "
            "your profile for an accurate score."
        )
    if visa.local_language_required:
        score *= 0.6
        cons.append("Asks for fluency in a local language.")
    return _clamp(score), blocker


def _compensation_score(
    cand: CandidateFacts, sal: SalaryFacts, pros: list[str], cons: list[str]
) -> float:
    minimum = cand.min_salary_eur
    if sal.has_actual and sal.actual_max_eur is not None:
        if minimum is None:
            return 75.0
        if sal.actual_max_eur >= minimum:
            pros.append(
                f"Advertised salary (up to {sal.actual_max_eur:,.0f} EUR) meets your minimum."
            )
            return 100.0
        if sal.actual_max_eur >= 0.9 * minimum:
            return 70.0
        cons.append(
            f"Advertised salary (up to {sal.actual_max_eur:,.0f} EUR) is below your minimum."
        )
        return 25.0
    if sal.estimated_max_eur is not None:
        if minimum is None:
            return 65.0
        return 75.0 if sal.estimated_max_eur >= minimum else 40.0
    return 60.0


def _clamp(v: float) -> float:
    return max(0.0, min(100.0, v))
