"""Candidate profile, skills, experience, resumes and search configurations."""

import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from backend.deps import CandidateDep, SessionDep, SettingsDep, load_candidate
from backend.schemas.candidate import (
    CandidateCreate,
    CandidateRead,
    CandidateUpdate,
    ExperienceCreate,
    ExperienceRead,
    ResumeRead,
    SearchConfigCreate,
    SearchConfigRead,
    SearchConfigUpdate,
    SkillCreate,
    SkillRead,
    SkillUpdate,
)
from backend.security import ActorDep, read_validated_resume
from backend.services.audit import record_audit
from backend.services.candidate import missing_profile_fields
from backend.services.tasks import enqueue
from common.enums import SkillSource
from database.models import (
    Candidate,
    CandidateExperience,
    CandidateResume,
    CandidateSkill,
    SearchConfiguration,
)

router = APIRouter(prefix="/candidate", tags=["candidate"])


def _to_read(candidate: Candidate) -> CandidateRead:
    data = CandidateRead.model_validate(candidate)
    data.profile_completeness = missing_profile_fields(candidate)
    return data


async def _reloaded(session: SessionDep) -> CandidateRead:
    candidate = await load_candidate(session)
    assert candidate is not None
    return _to_read(candidate)


@router.get("", response_model=CandidateRead)
async def get_candidate(candidate: CandidateDep) -> CandidateRead:
    return _to_read(candidate)


@router.post("", response_model=CandidateRead, status_code=status.HTTP_201_CREATED)
async def create_candidate(
    body: CandidateCreate, session: SessionDep, actor: ActorDep, request: Request
) -> CandidateRead:
    if await load_candidate(session) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A candidate profile already exists")
    candidate = Candidate(**body.model_dump(exclude_none=True))
    session.add(candidate)
    await session.flush()
    record_audit(
        session,
        request=request,
        actor=actor,
        action="candidate.create",
        entity_type="candidate",
        entity_id=candidate.id,
    )
    await session.commit()
    return await _reloaded(session)


@router.patch("", response_model=CandidateRead)
async def update_candidate(
    body: CandidateUpdate,
    candidate: CandidateDep,
    session: SessionDep,
    actor: ActorDep,
    request: Request,
) -> CandidateRead:
    changes = body.model_dump(exclude_unset=True)
    if "full_name" in changes and changes["full_name"] is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "full_name cannot be null")
    for field, value in changes.items():
        setattr(candidate, field, value)
    record_audit(
        session,
        request=request,
        actor=actor,
        action="candidate.update",
        entity_type="candidate",
        entity_id=candidate.id,
        details={"fields": sorted(changes)},
    )
    await session.commit()
    return await _reloaded(session)


# --- Skills -------------------------------------------------------------------------


@router.get("/skills", response_model=list[SkillRead])
async def list_skills(candidate: CandidateDep) -> list[CandidateSkill]:
    return candidate.skills


@router.post("/skills", response_model=SkillRead, status_code=status.HTTP_201_CREATED)
async def add_skill(
    body: SkillCreate,
    candidate: CandidateDep,
    session: SessionDep,
    actor: ActorDep,
    request: Request,
) -> CandidateSkill:
    if any(s.name.lower() == body.name.lower() for s in candidate.skills):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Skill '{body.name}' already exists")
    skill = CandidateSkill(
        candidate_id=candidate.id, source=SkillSource.MANUAL, **body.model_dump()
    )
    session.add(skill)
    await session.flush()
    record_audit(
        session,
        request=request,
        actor=actor,
        action="skill.create",
        entity_type="candidate_skill",
        entity_id=skill.id,
        details={"name": skill.name},
    )
    await session.commit()
    return skill


@router.patch("/skills/{skill_id}", response_model=SkillRead)
async def update_skill(
    skill_id: uuid.UUID,
    body: SkillUpdate,
    candidate: CandidateDep,
    session: SessionDep,
    actor: ActorDep,
    request: Request,
) -> CandidateSkill:
    skill = next((s for s in candidate.skills if s.id == skill_id), None)
    if skill is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Skill not found")
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if "name" in changes and any(
        s.id != skill_id and s.name.lower() == changes["name"].lower() for s in candidate.skills
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Skill '{changes['name']}' already exists")
    for field, value in changes.items():
        setattr(skill, field, value)
    record_audit(
        session,
        request=request,
        actor=actor,
        action="skill.update",
        entity_type="candidate_skill",
        entity_id=skill.id,
        details=changes,
    )
    await session.commit()
    return skill


@router.delete("/skills/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(
    skill_id: uuid.UUID,
    candidate: CandidateDep,
    session: SessionDep,
    actor: ActorDep,
    request: Request,
) -> None:
    skill = next((s for s in candidate.skills if s.id == skill_id), None)
    if skill is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Skill not found")
    await session.delete(skill)
    record_audit(
        session,
        request=request,
        actor=actor,
        action="skill.delete",
        entity_type="candidate_skill",
        entity_id=skill_id,
        details={"name": skill.name},
    )
    await session.commit()


# --- Experience ---------------------------------------------------------------------


@router.post("/experiences", response_model=ExperienceRead, status_code=status.HTTP_201_CREATED)
async def add_experience(
    body: ExperienceCreate,
    candidate: CandidateDep,
    session: SessionDep,
    actor: ActorDep,
    request: Request,
) -> CandidateExperience:
    if body.start_date and body.end_date and body.end_date < body.start_date:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "end_date is before start_date")
    exp = CandidateExperience(candidate_id=candidate.id, **body.model_dump())
    session.add(exp)
    await session.flush()
    record_audit(
        session,
        request=request,
        actor=actor,
        action="experience.create",
        entity_type="candidate_experience",
        entity_id=exp.id,
    )
    await session.commit()
    return exp


@router.put("/experiences/{experience_id}", response_model=ExperienceRead)
async def replace_experience(
    experience_id: uuid.UUID,
    body: ExperienceCreate,
    candidate: CandidateDep,
    session: SessionDep,
    actor: ActorDep,
    request: Request,
) -> CandidateExperience:
    exp = next((e for e in candidate.experiences if e.id == experience_id), None)
    if exp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Experience not found")
    for field, value in body.model_dump().items():
        setattr(exp, field, value)
    record_audit(
        session,
        request=request,
        actor=actor,
        action="experience.update",
        entity_type="candidate_experience",
        entity_id=exp.id,
    )
    await session.commit()
    return exp


@router.delete("/experiences/{experience_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_experience(
    experience_id: uuid.UUID,
    candidate: CandidateDep,
    session: SessionDep,
    actor: ActorDep,
    request: Request,
) -> None:
    exp = next((e for e in candidate.experiences if e.id == experience_id), None)
    if exp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Experience not found")
    await session.delete(exp)
    record_audit(
        session,
        request=request,
        actor=actor,
        action="experience.delete",
        entity_type="candidate_experience",
        entity_id=experience_id,
    )
    await session.commit()


# --- Resumes ------------------------------------------------------------------------


@router.get("/resumes", response_model=list[ResumeRead])
async def list_resumes(candidate: CandidateDep) -> list[CandidateResume]:
    return sorted(candidate.resumes, key=lambda r: r.created_at, reverse=True)


@router.post("/resumes", response_model=ResumeRead, status_code=status.HTTP_201_CREATED)
async def upload_resume(
    candidate: CandidateDep,
    session: SessionDep,
    settings: SettingsDep,
    actor: ActorDep,
    request: Request,
    file: UploadFile = File(...),
    version_label: str = Form("default", min_length=1, max_length=100),
    make_primary: bool = Form(False),
) -> CandidateResume:
    upload = await read_validated_resume(file, settings.max_upload_bytes)
    if any(r.sha256 == upload.sha256 for r in candidate.resumes):
        raise HTTPException(status.HTTP_409_CONFLICT, "This exact file was already uploaded")

    resume_id = uuid.uuid4()
    # Stored under a generated name; the client-supplied filename is never used as a path.
    target = Path(settings.upload_dir) / str(candidate.id) / f"{resume_id}.{upload.extension}"
    await asyncio.to_thread(_write_file, target, upload.content)

    is_primary = make_primary or not candidate.resumes
    if is_primary:
        await session.execute(
            update(CandidateResume)
            .where(CandidateResume.candidate_id == candidate.id)
            .values(is_primary=False)
        )
    resume = CandidateResume(
        id=resume_id,
        candidate_id=candidate.id,
        version_label=version_label,
        original_filename=(file.filename or f"resume.{upload.extension}")[:255],
        content_type=upload.content_type,
        storage_path=str(target),
        sha256=upload.sha256,
        size_bytes=len(upload.content),
        is_primary=is_primary,
    )
    session.add(resume)
    await session.flush()
    record_audit(
        session,
        request=request,
        actor=actor,
        action="resume.upload",
        entity_type="candidate_resume",
        entity_id=resume.id,
        details={"size": resume.size_bytes, "type": upload.extension},
    )
    try:
        await session.commit()
    except Exception:
        target.unlink(missing_ok=True)
        raise
    from workers.tasks.agents import parse_resume

    try:
        await enqueue(parse_resume, str(resume.id))
    except HTTPException:
        pass  # the upload succeeded; parsing can be re-run with POST .../parse
    return resume


@router.post("/resumes/{resume_id}/parse", status_code=status.HTTP_202_ACCEPTED)
async def parse_resume_again(resume_id: uuid.UUID, candidate: CandidateDep) -> dict:
    from workers.tasks.agents import parse_resume

    if not any(r.id == resume_id for r in candidate.resumes):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume not found")
    return {"task_id": await enqueue(parse_resume, str(resume_id), "manual")}


@router.get("/resumes/{resume_id}/analysis")
async def resume_analysis(resume_id: uuid.UUID, candidate: CandidateDep) -> dict:
    """What the CV agent found: skills, certifications, suggestions, strengths and gaps."""
    resume = next((r for r in candidate.resumes if r.id == resume_id), None)
    if resume is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume not found")
    if resume.parsed_at is None:
        return {"status": "pending"}
    if resume.parse_error:
        return {"status": "failed", "error": resume.parse_error}
    return {
        "status": "parsed",
        "parsed_at": resume.parsed_at,
        "has_embedding": resume.embedding is not None,
        **(resume.parsed_data or {}),
    }


class ApplySkills(BaseModel):
    skills: list[str] = Field(min_length=1, max_length=100)


@router.post("/resumes/{resume_id}/apply-skills", response_model=list[SkillRead])
async def apply_suggested_skills(
    resume_id: uuid.UUID,
    body: ApplySkills,
    candidate: CandidateDep,
    session: SessionDep,
    actor: ActorDep,
    request: Request,
) -> list[CandidateSkill]:
    """Add skills the CV agent suggested. Only the ones you list are added (your approval)."""
    resume = next((r for r in candidate.resumes if r.id == resume_id), None)
    if resume is None or not resume.parsed_data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No parsed resume with that id")
    suggested = {s["name"].lower(): s for s in resume.parsed_data.get("suggested_skills", [])}
    unknown = [n for n in body.skills if n.lower() not in suggested]
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Not among this resume's suggestions: {unknown}"
        )
    have = {s.name.lower() for s in candidate.skills}
    added = []
    for name in body.skills:
        sug = suggested[name.lower()]
        if sug["name"].lower() in have:
            continue
        skill = CandidateSkill(
            candidate_id=candidate.id,
            name=sug["name"],
            category=sug.get("category"),
            source=SkillSource.CV,
        )
        session.add(skill)
        added.append(skill)
        have.add(sug["name"].lower())
    await session.flush()
    record_audit(
        session,
        request=request,
        actor=actor,
        action="skill.apply_from_cv",
        entity_type="candidate_resume",
        entity_id=resume_id,
        details={"added": [s.name for s in added]},
    )
    await session.commit()
    return added


@router.post("/resumes/{resume_id}/primary", response_model=ResumeRead)
async def set_primary_resume(
    resume_id: uuid.UUID,
    candidate: CandidateDep,
    session: SessionDep,
    actor: ActorDep,
    request: Request,
) -> CandidateResume:
    resume = next((r for r in candidate.resumes if r.id == resume_id), None)
    if resume is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume not found")
    for r in candidate.resumes:
        r.is_primary = r.id == resume_id
    record_audit(
        session,
        request=request,
        actor=actor,
        action="resume.set_primary",
        entity_type="candidate_resume",
        entity_id=resume_id,
    )
    await session.commit()
    return resume


@router.delete("/resumes/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume(
    resume_id: uuid.UUID,
    candidate: CandidateDep,
    session: SessionDep,
    actor: ActorDep,
    request: Request,
) -> None:
    resume = next((r for r in candidate.resumes if r.id == resume_id), None)
    if resume is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume not found")
    path = Path(resume.storage_path)
    await session.delete(resume)
    record_audit(
        session,
        request=request,
        actor=actor,
        action="resume.delete",
        entity_type="candidate_resume",
        entity_id=resume_id,
    )
    await session.commit()
    await asyncio.to_thread(path.unlink, missing_ok=True)


def _write_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


# --- Search configurations ----------------------------------------------------------


@router.get("/search-configs", response_model=list[SearchConfigRead])
async def list_search_configs(candidate: CandidateDep, session: SessionDep):
    rows = await session.scalars(
        select(SearchConfiguration)
        .where(SearchConfiguration.candidate_id == candidate.id)
        .order_by(SearchConfiguration.name)
    )
    return list(rows)


@router.post(
    "/search-configs", response_model=SearchConfigRead, status_code=status.HTTP_201_CREATED
)
async def create_search_config(
    body: SearchConfigCreate,
    candidate: CandidateDep,
    session: SessionDep,
    actor: ActorDep,
    request: Request,
) -> SearchConfiguration:
    exists = await session.scalar(
        select(SearchConfiguration.id).where(
            SearchConfiguration.candidate_id == candidate.id,
            SearchConfiguration.name == body.name,
        )
    )
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Search '{body.name}' already exists")
    cfg = SearchConfiguration(candidate_id=candidate.id, **body.model_dump())
    session.add(cfg)
    await session.flush()
    record_audit(
        session,
        request=request,
        actor=actor,
        action="search_config.create",
        entity_type="search_configuration",
        entity_id=cfg.id,
    )
    await session.commit()
    return cfg


@router.patch("/search-configs/{config_id}", response_model=SearchConfigRead)
async def update_search_config(
    config_id: uuid.UUID,
    body: SearchConfigUpdate,
    candidate: CandidateDep,
    session: SessionDep,
    actor: ActorDep,
    request: Request,
) -> SearchConfiguration:
    cfg = await session.get(SearchConfiguration, config_id)
    if cfg is None or cfg.candidate_id != candidate.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Search configuration not found")
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    for field, value in changes.items():
        setattr(cfg, field, value)
    record_audit(
        session,
        request=request,
        actor=actor,
        action="search_config.update",
        entity_type="search_configuration",
        entity_id=cfg.id,
        details=changes,
    )
    await session.commit()
    return cfg


@router.delete("/search-configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_search_config(
    config_id: uuid.UUID,
    candidate: CandidateDep,
    session: SessionDep,
    actor: ActorDep,
    request: Request,
) -> None:
    cfg = await session.get(SearchConfiguration, config_id)
    if cfg is None or cfg.candidate_id != candidate.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Search configuration not found")
    await session.delete(cfg)
    record_audit(
        session,
        request=request,
        actor=actor,
        action="search_config.delete",
        entity_type="search_configuration",
        entity_id=config_id,
    )
    await session.commit()
