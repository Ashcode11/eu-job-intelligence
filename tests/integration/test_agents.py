"""Phase 3 agents end to end against a real database (LLM faked or absent)."""

import asyncio
import io
import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select, update

from agents.application.service import ApplicationPrepService
from agents.cv_intelligence.service import CVIntelligenceService
from agents.llm.ollama import OllamaClient
from agents.orchestrator.pipeline import Pipeline
from common.config import Settings
from common.enums import ApplicationStatus, ExecutionStatus, NotificationKind
from common.enums import VisaClassification as VC
from database.models import (
    AgentExecution,
    Application,
    Candidate,
    CandidateResume,
    Job,
    JobMatch,
    Notification,
    SalaryAssessment,
    VisaAssessment,
)
from database.session import create_session_factory
from scripts.seed import seed_candidate, seed_jobs
from tests.unit.test_cv_and_llm import CV_TEXT, make_docx

pytestmark = pytest.mark.integration


def fake_llm(calls: list[str] | None = None) -> OllamaClient:
    """A fake Ollama: models present, deterministic embeddings, canned chat answers."""

    def handler(req: httpx.Request):
        if calls is not None:
            calls.append(req.url.path)
        if req.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "llama3.2:3b"}, {"name": "nomic-embed-text:latest"}]}
            )
        body = json.loads(req.content)
        if req.url.path == "/api/embed":
            vecs = [
                [1.0 if (i + len(t)) % 7 == 0 else 0.1 for i in range(768)] for t in body["input"]
            ]
            return httpx.Response(200, json={"embeddings": vecs})
        if body.get("format"):
            content = json.dumps(
                {
                    "summary": "s",
                    "projects": [],
                    "strengths": [],
                    "questions": ["How would you migrate X?"],
                    "classification": "not_mentioned",
                    "quote": "",
                    "rationale": "",
                }
            )
        else:
            content = "A drafted text based on the facts provided."
        return httpx.Response(
            200, json={"message": {"content": content}, "prompt_eval_count": 50, "eval_count": 10}
        )

    return OllamaClient(Settings(_env_file=None), transport=httpx.MockTransport(handler))


@pytest.fixture
async def seeded(engine):
    factory = create_session_factory(engine)
    async with factory() as s:
        await seed_candidate(s)
        await seed_jobs(s)
        cand = await s.scalar(select(Candidate))
        cand.requires_visa_sponsorship = True
        cand.has_eu_work_authorization = False
        cand.open_to_relocation = True
        cand.current_country = "IN"
        cand.min_salary_eur = 80000
        await s.commit()
    return factory


async def _count(factory, model) -> int:
    async with factory() as s:
        return await s.scalar(select(func.count()).select_from(model))


async def test_pipeline_analyses_all_jobs_without_llm(seeded):
    state = await Pipeline(seeded, llm=None).run(trigger="test")
    assert len(state["selected"]) == 8
    assert await _count(seeded, VisaAssessment) == 8
    assert await _count(seeded, SalaryAssessment) == 8
    assert await _count(seeded, JobMatch) == 8

    async with seeded() as s:
        rows = (
            await s.execute(
                select(
                    Job.external_id,
                    VisaAssessment.classification,
                    JobMatch.overall_score,
                    JobMatch.recommended,
                )
                .join(VisaAssessment, VisaAssessment.job_id == Job.id)
                .join(JobMatch, JobMatch.job_id == Job.id)
            )
        ).all()
        by_id = {r[0]: r for r in rows}
        # Visa stance from the fictional sample texts
        assert by_id["sample-001"][1] == VC.EXPLICIT_SPONSORSHIP
        assert by_id["sample-003"][1] == VC.EU_AUTHORIZATION_REQUIRED
        assert by_id["sample-004"][1] == VC.POTENTIAL_SPONSORSHIP
        # Sponsorship-seeking candidate: explicit-sponsor DE migration role beats IE "no visa"
        assert by_id["sample-001"][2] > 70 and by_id["sample-001"][3] is True
        assert by_id["sample-003"][2] <= 35 and by_id["sample-003"][3] is False
        execs = {e.agent_name: e for e in await s.scalars(select(AgentExecution))}
    assert {
        "orchestrator",
        "selection",
        "embedding",
        "matching",
        "visa",
        "salary",
        "ranking",
        "notifications",
    } <= set(execs)
    assert execs["orchestrator"].status == ExecutionStatus.SUCCEEDED
    assert execs["embedding"].decisions[0]["decision"] == "skip"
    assert len({e.workflow_run_id for e in execs.values()}) == 1


async def test_second_run_skips_unchanged_jobs(seeded):
    await Pipeline(seeded, llm=None).run()
    state = await Pipeline(seeded, llm=None).run()
    assert state["selected"] == []
    assert state["counters"]["selection"]["skipped"] == 8


async def test_profile_change_triggers_rescoring(seeded):
    await Pipeline(seeded, llm=None).run()
    async with seeded() as s:
        await s.execute(update(Candidate).values(min_salary_eur=200000))
        await s.commit()
    state = await Pipeline(seeded, llm=None).run()
    assert len(state["selected"]) == 8
    async with seeded() as s:
        sal = await s.scalar(
            select(SalaryAssessment).join(Job).where(Job.external_id == "sample-001")
        )
    assert sal.meets_candidate_minimum is False


async def test_force_reprocess_single_job(seeded):
    await Pipeline(seeded, llm=None).run()
    async with seeded() as s:
        job_id = await s.scalar(select(Job.id).where(Job.external_id == "sample-002"))
    state = await Pipeline(seeded, llm=None).run(job_ids=[job_id], force=True, trigger="reprocess")
    assert state["selected"] == [str(job_id)]
    assert state["counters"]["ranking"]["created"] == 1


async def test_llm_path_embeds_once_and_caches(seeded):
    calls: list[str] = []
    llm = fake_llm(calls)
    await Pipeline(seeded, llm=llm).run()
    embeds_first = calls.count("/api/embed")
    async with seeded() as s:
        assert (
            await s.scalar(select(func.count()).select_from(Job).where(Job.embedding.is_not(None)))
            == 8
        )
        m = await s.scalar(select(JobMatch).limit(1))
        assert m.semantic_similarity is not None
    calls.clear()
    second = await Pipeline(seeded, llm=llm).run()
    assert second["selected"] == []
    assert "/api/chat" not in calls  # nothing re-analysed, no LLM calls
    assert embeds_first >= 2  # profile + job batch
    await llm.aclose()


async def test_notifications_created_once(seeded):
    await Pipeline(seeded, llm=None).run()
    async with seeded() as s:
        kinds = [n.kind for n in await s.scalars(select(Notification))]
    assert NotificationKind.VISA_SPONSORSHIP in kinds
    first = len(kinds)
    await Pipeline(seeded, llm=None).run(force=True)  # same alerts must not repeat
    assert await _count(seeded, Notification) == first


async def test_failing_job_is_isolated(seeded, monkeypatch):
    from agents.matching import scorer

    real = scorer.score

    def flaky(cand, job, visa, sal):
        if "Luxembourg" in job.description or job.country == "LU":
            raise RuntimeError("boom")
        return real(cand, job, visa, sal)

    monkeypatch.setattr(scorer, "score", flaky)
    state = await Pipeline(seeded, llm=None).run()
    assert state["counters"]["ranking"]["failed"] == 1
    assert await _count(seeded, JobMatch) == 7


async def test_cv_agent_parses_and_suggests_without_editing_profile(seeded, tmp_path):
    path = tmp_path / "cv.docx"
    path.write_bytes(make_docx(CV_TEXT + " ArgoCD and Pulumi for GitOps."))
    async with seeded() as s:
        cand = await s.scalar(select(Candidate))
        skills_before = len(
            (
                await s.execute(
                    select(func.count()).select_from(Candidate).where(Candidate.id == cand.id)
                )
            ).all()
        )
        resume = CandidateResume(
            candidate_id=cand.id,
            version_label="v1",
            original_filename="cv.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            storage_path=str(path),
            sha256="x" * 64,
            size_bytes=path.stat().st_size,
            is_primary=True,
        )
        s.add(resume)
        await s.commit()
        rid, cid = resume.id, cand.id
    out = await CVIntelligenceService(seeded, llm=None).process(rid)
    assert out["status"] == "succeeded"
    async with seeded() as s:
        r = await s.get(CandidateResume, rid)
        from database.models import CandidateSkill

        n_skills = await s.scalar(
            select(func.count())
            .select_from(CandidateSkill)
            .where(CandidateSkill.candidate_id == cid)
        )
    suggestions = {x["name"] for x in r.parsed_data["suggested_skills"]}
    assert {"ArgoCD", "Pulumi"} <= suggestions
    assert "Terraform" not in suggestions  # already in the inventory
    assert n_skills == 28  # profile untouched until the user approves
    assert skills_before == 1


async def test_cv_agent_records_parse_failure(seeded, tmp_path):
    path = tmp_path / "bad.pdf"
    path.write_bytes(b"%PDF-1.4 broken")
    async with seeded() as s:
        cand = await s.scalar(select(Candidate))
        resume = CandidateResume(
            candidate_id=cand.id,
            version_label="bad",
            original_filename="bad.pdf",
            content_type="application/pdf",
            storage_path=str(path),
            sha256="y" * 64,
            size_bytes=15,
        )
        s.add(resume)
        await s.commit()
        rid = resume.id
    out = await CVIntelligenceService(seeded, llm=None).process(rid)
    assert out["status"] == "failed"
    async with seeded() as s:
        ex = await s.scalar(
            select(AgentExecution).where(AgentExecution.agent_name == "cv_intelligence")
        )
    assert ex.status == ExecutionStatus.FAILED


@pytest.mark.parametrize("with_llm", [False, True])
async def test_application_prep_drafts_only(seeded, test_settings, monkeypatch, with_llm):
    from common import config

    monkeypatch.setattr(config.get_settings(), "upload_dir", test_settings.upload_dir)
    await Pipeline(seeded, llm=None).run()
    async with seeded() as s:
        cand = await s.scalar(select(Candidate))
        job_id = await s.scalar(select(Job.id).where(Job.external_id == "sample-002"))
        app = Application(candidate_id=cand.id, job_id=job_id, status_history=[])
        s.add(app)
        await s.commit()
        app_id = app.id
    llm = fake_llm() if with_llm else None
    out = await ApplicationPrepService(seeded, llm=llm).prepare(app_id)
    assert out["method"] == ("llm" if with_llm else "template")
    async with seeded() as s:
        app = await s.get(Application, app_id)
        cv = await s.get(CandidateResume, app.tailored_resume_id)
    assert app.status == ApplicationStatus.PREPARED and app.drafts_approved_at is None
    assert app.cover_letter_draft and app.outreach_message_draft
    assert app.interview_prep["technical_questions"]
    # sample-002 explicitly sponsors, so the agent must not suggest asking about it
    assert not any("sponsorship" in q for q in app.interview_prep["questions_to_ask"])
    assert cv.job_id == job_id and cv.content_type.endswith("document")
    from docx import Document

    doc = Document(io.BytesIO(await asyncio.to_thread(Path(cv.storage_path).read_bytes)))
    assert "Key skills for this role" in [p.text for p in doc.paragraphs]
    if llm:
        await llm.aclose()


async def test_application_prep_asks_about_sponsorship_when_posting_is_silent(
    seeded, test_settings, monkeypatch
):
    from common import config

    monkeypatch.setattr(config.get_settings(), "upload_dir", test_settings.upload_dir)
    await Pipeline(seeded, llm=None).run()
    async with seeded() as s:
        cand = await s.scalar(select(Candidate))
        job_id = await s.scalar(select(Job.id).where(Job.external_id == "sample-007"))
        app = Application(candidate_id=cand.id, job_id=job_id, status_history=[])
        s.add(app)
        await s.commit()
        app_id = app.id
    await ApplicationPrepService(seeded, llm=None).prepare(app_id)
    async with seeded() as s:
        app = await s.get(Application, app_id)
    assert "sponsorship" in app.interview_prep["questions_to_ask"][0]
    assert "What is the salary range for this role?" in app.interview_prep["questions_to_ask"]
    assert "sponsorship" in app.outreach_message_draft
