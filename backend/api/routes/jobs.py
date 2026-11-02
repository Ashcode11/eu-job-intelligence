"""Job explorer and job details."""

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import selectinload

from backend.deps import CandidateDep, SessionDep
from backend.schemas.jobs import (
    CompanyRead,
    JobDetail,
    JobSort,
    JobSummary,
    MatchRead,
    Page,
    SalaryRead,
    VisaRead,
)
from common.enums import JobStatus, VisaClassification
from database.models import (
    Application,
    Company,
    Job,
    JobMatch,
    JobSource,
    SalaryAssessment,
    VisaAssessment,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _base_query(candidate_id: uuid.UUID) -> Select:
    return (
        select(
            Job,
            Company.name,
            JobSource.key,
            JobMatch,
            VisaAssessment.classification,
            Application.status,
        )
        .join(JobSource, JobSource.id == Job.source_id)
        .outerjoin(Company, Company.id == Job.company_id)
        .outerjoin(JobMatch, and_(JobMatch.job_id == Job.id, JobMatch.candidate_id == candidate_id))
        .outerjoin(VisaAssessment, VisaAssessment.job_id == Job.id)
        .outerjoin(
            Application,
            and_(Application.job_id == Job.id, Application.candidate_id == candidate_id),
        )
    )


def _summary(row) -> dict:
    job, company_name, source_key, match, visa_cls, app_status = row
    return dict(
        id=job.id,
        title=job.title,
        company_name=company_name,
        country=job.country,
        city=job.city,
        remote_type=job.remote_type,
        posted_at=job.posted_at,
        status=job.status,
        url=job.url,
        source_key=source_key,
        salary_min=job.salary_min,
        salary_max=job.salary_max,
        salary_currency=job.salary_currency,
        match_score=float(match.overall_score) if match else None,
        visa_classification=visa_cls,
        application_status=app_status,
    )


@router.get("", response_model=Page[JobSummary])
async def list_jobs(
    candidate: CandidateDep,
    session: SessionDep,
    q: Annotated[
        str | None, Query(max_length=200, description="Search title/company/description")
    ] = None,
    country: Annotated[list[str] | None, Query(description="ISO country codes")] = None,
    company: Annotated[str | None, Query(max_length=200)] = None,
    visa: Annotated[list[VisaClassification] | None, Query()] = None,
    min_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    min_salary_eur: Annotated[int | None, Query(ge=0)] = None,
    job_status: Annotated[JobStatus | None, Query(alias="status")] = JobStatus.ACTIVE,
    bookmarked: bool | None = None,
    sort: JobSort = "match_score",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> Page[JobSummary]:
    stmt = _base_query(candidate.id)
    if job_status is not None:
        stmt = stmt.where(Job.status == job_status)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(Job.title.ilike(like), Company.name.ilike(like), Job.description.ilike(like))
        )
    if country:
        stmt = stmt.where(Job.country.in_([c.upper() for c in country]))
    if company:
        stmt = stmt.where(Company.name.ilike(f"%{company}%"))
    if visa:
        stmt = stmt.where(VisaAssessment.classification.in_(visa))
    if min_score is not None:
        stmt = stmt.where(JobMatch.overall_score >= min_score)
    if min_salary_eur is not None:
        stmt = stmt.outerjoin(SalaryAssessment, SalaryAssessment.job_id == Job.id).where(
            func.coalesce(SalaryAssessment.actual_max_eur, SalaryAssessment.estimated_max_eur)
            >= min_salary_eur
        )
    if bookmarked is True:
        stmt = stmt.where(Application.id.is_not(None))
    elif bookmarked is False:
        stmt = stmt.where(Application.id.is_(None))

    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))

    order = {
        "match_score": [
            JobMatch.overall_score.desc().nulls_last(),
            Job.posted_at.desc().nulls_last(),
        ],
        "posted_at": [Job.posted_at.desc().nulls_last()],
        "discovered_at": [Job.discovered_at.desc()],
        "salary": [Job.salary_max.desc().nulls_last()],
    }[sort]
    rows = await session.execute(
        stmt.order_by(*order, Job.id).offset((page - 1) * page_size).limit(page_size)
    )
    return Page[JobSummary](
        items=[JobSummary(**_summary(r)) for r in rows.all()],
        total=total or 0,
        page=page,
        page_size=page_size,
    )


@router.get("/{job_id}", response_model=JobDetail)
async def get_job(job_id: uuid.UUID, candidate: CandidateDep, session: SessionDep) -> JobDetail:
    row = (
        await session.execute(
            _base_query(candidate.id)
            .where(Job.id == job_id)
            .options(
                selectinload(Job.company),
                selectinload(Job.visa_assessment),
                selectinload(Job.salary_assessment),
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    job, match = row[0], row[3]
    return JobDetail(
        **_summary(row),
        apply_url=job.apply_url,
        description=job.description,
        location_raw=job.location_raw,
        employment_type=job.employment_type,
        seniority=job.seniority,
        experience_min_years=job.experience_min_years,
        required_skills=job.required_skills,
        salary_raw=job.salary_raw,
        salary_period=job.salary_period,
        discovered_at=job.discovered_at,
        last_seen_at=job.last_seen_at,
        expires_at=job.expires_at,
        company=CompanyRead.model_validate(job.company) if job.company else None,
        match=MatchRead.model_validate(match) if match else None,
        visa=VisaRead.model_validate(job.visa_assessment) if job.visa_assessment else None,
        salary=SalaryRead.model_validate(job.salary_assessment) if job.salary_assessment else None,
    )
