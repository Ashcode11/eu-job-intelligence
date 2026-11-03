"""Application Preparation Agent.

Produces drafts only: a tailored CV (DOCX), a cover letter, a short recruiter message and
interview preparation notes. It never submits applications or sends messages; drafts wait
for the user's explicit approval (`drafts_approved_at`).

With Ollama available the texts are written by the local LLM from facts we pass in, with an
instruction not to invent anything. Without it, clear templates are used.
"""

import asyncio
import hashlib
import io
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from agents.llm.ollama import LLMUnavailable, OllamaClient
from common.config import get_settings
from common.enums import ApplicationStatus, ExecutionStatus
from common.logging import get_logger
from database.models import AgentExecution, Application, Candidate, CandidateResume, Job

log = get_logger(__name__)
AGENT_NAME = "application"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

QUESTION_BANK: dict[str, list[str]] = {
    "AWS": [
        "Walk through a multi-account AWS landing zone you designed. How did you handle "
        "guardrails and networking?",
        "How do you choose between ECS, EKS and Lambda for a new workload?",
    ],
    "Microsoft Azure": [
        "How would you design an Azure landing zone for a regulated customer?",
        "Compare Azure Policy and management groups with AWS SCPs and OUs.",
    ],
    "Terraform": [
        "How do you structure Terraform state and modules across many teams and environments?",
        "How do you detect and handle drift?",
    ],
    "Terragrunt": [
        "What problems does Terragrunt solve over plain Terraform, and when would you avoid it?"
    ],
    "Kubernetes": [
        "How would you run multi-tenant Kubernetes safely?",
        "Explain how you would troubleshoot pods stuck in CrashLoopBackOff.",
    ],
    "Cloud Migration": [
        "Describe a migration you led: the 6R decision, cut-over plan and rollback strategy.",
        "How do you estimate and de-risk a large migration wave?",
    ],
    "AWS DMS": [
        "How do you minimise downtime when migrating a large SQL Server database with DMS and CDC?",
        "What DMS limitations have you hit, and how did you work around them?",
    ],
    "Amazon RDS": ["How do you choose between RDS, Aurora and self-managed databases on EC2?"],
    "CI/CD": ["Design a CI/CD pipeline for 50 microservices with safe production releases."],
    "Cloud Security": [
        "How do you implement least privilege at scale?",
        "How would you design secrets management across environments?",
    ],
    "Networking": [
        "Design hybrid connectivity between on-premises data centres and multiple VPCs/VNets."
    ],
    "High Availability": ["How do you define RTO/RPO with the business and design for them?"],
    "FinOps": ["How have you reduced cloud cost without hurting reliability?"],
    "Microservices": ["When would you not use microservices?"],
    "Stakeholder Management": ["Tell me about a time you had to say no to a senior stakeholder."],
    "People Management": ["How do you grow engineers and handle under-performance?"],
}
GENERIC_QUESTIONS = [
    "Walk me through the most complex architecture you have designed end to end.",
    "How do you document and communicate architecture decisions (ADRs)?",
    "What trade-offs did you make in your last major design, and would you change any?",
]


class ApplicationPrepService:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], llm: OllamaClient | None = None
    ) -> None:
        self.sf = session_factory
        self.llm = llm

    async def prepare(self, application_id: uuid.UUID, *, trigger: str = "api") -> dict[str, Any]:
        t0, started = time.perf_counter(), datetime.now(UTC)
        async with self.sf() as s:
            app = await s.get(
                Application,
                application_id,
                options=[
                    selectinload(Application.job).selectinload(Job.company),
                    selectinload(Application.job).selectinload(Job.visa_assessment),
                    selectinload(Application.job).selectinload(Job.salary_assessment),
                    selectinload(Application.job).selectinload(Job.matches),
                ],
            )
            if app is None:
                raise ValueError(f"Application {application_id} not found")
            cand = await s.get(
                Candidate,
                app.candidate_id,
                options=[
                    selectinload(Candidate.skills),
                    selectinload(Candidate.experiences),
                    selectinload(Candidate.resumes),
                ],
            )
            ex = AgentExecution(
                agent_name=AGENT_NAME,
                trigger=trigger,
                started_at=started,
                status=ExecutionStatus.RUNNING,
                details={"application_id": str(application_id)},
            )
            s.add(ex)
            await s.flush()

            job = app.job
            match = next((m for m in job.matches if m.candidate_id == cand.id), None)
            facts = _facts(cand, job, match)
            use_llm = bool(self.llm and await self.llm.available())
            method = "llm" if use_llm else "template"
            try:
                if use_llm:
                    summary, cover, outreach, extra_q = await self._llm_texts(facts)
                else:
                    raise LLMUnavailable("Ollama unavailable")
            except LLMUnavailable as exc:
                method = "template"
                ex.decisions = [{"decision": "template", "reason": str(exc)[:200]}]
                summary, cover, outreach, extra_q = _template_texts(facts)

            prep = _interview_prep(facts, job, extra_q)
            resume = await _write_tailored_cv(s, cand, job, facts, summary)

            app.cover_letter_draft = cover
            app.outreach_message_draft = outreach
            app.interview_prep = {
                **prep,
                "generated_with": method,
                "generated_at": datetime.now(UTC).isoformat(),
            }
            app.tailored_resume_id = resume.id
            app.drafts_approved_at = None  # new drafts always need fresh approval
            if app.status in (ApplicationStatus.SAVED, ApplicationStatus.SHORTLISTED):
                app.status_history = [
                    *app.status_history,
                    {
                        "from": app.status.value,
                        "to": ApplicationStatus.PREPARED.value,
                        "at": datetime.now(UTC).isoformat(),
                        "note": "drafts prepared by agent",
                    },
                ]
                app.status = ApplicationStatus.PREPARED

            ex.status = ExecutionStatus.SUCCEEDED
            ex.items_processed = ex.items_created = 1
            ex.finished_at = datetime.now(UTC)
            ex.duration_ms = int((time.perf_counter() - t0) * 1000)
            if self.llm and use_llm:
                u = self.llm.usage
                ex.llm_model, ex.llm_calls = self.llm.chat_model, u.calls
                ex.llm_prompt_tokens, ex.llm_completion_tokens = (
                    u.prompt_tokens,
                    u.completion_tokens,
                )
            await s.commit()
            log.info("application_prepared", application_id=str(application_id), method=method)
            return {"status": "succeeded", "method": method, "tailored_resume_id": str(resume.id)}

    async def _llm_texts(self, f: dict[str, Any]) -> tuple[str, str, str, list[str]]:
        assert self.llm is not None
        system = (
            "You write job-application drafts for a candidate. Use ONLY the facts "
            "provided. Never invent employers, dates, numbers, certifications or "
            "achievements. Plain, confident, professional English. No placeholders."
        )
        facts = "\n".join(f"{k}: {v}" for k, v in f.items() if v)
        summary = await self.llm.chat_text(
            system,
            f"{facts}\n\nWrite a 3-sentence CV profile summary tailored to this job.",
            max_tokens=220,
        )
        cover = await self.llm.chat_text(
            system,
            f"{facts}\n\nWrite a cover letter of at most 250 words. Mention 2-3 matched "
            "skills and why the role fits. If the candidate needs visa sponsorship, do not "
            "mention it in the letter.",
            max_tokens=500,
        )
        outreach = await self.llm.chat_text(
            system,
            f"{facts}\n\nWrite a LinkedIn message to a recruiter, under 450 "
            "characters, asking about the role. If sponsorship is needed and not stated in "
            "the posting, politely ask whether it is possible.",
            max_tokens=200,
        )
        q = await self.llm.chat_json(
            system,
            f"{facts}\n\nList 5 technical interview questions specific to this job.",
            {
                "type": "object",
                "properties": {
                    "questions": {"type": "array", "items": {"type": "string"}, "maxItems": 5}
                },
                "required": ["questions"],
            },
            max_tokens=400,
        )
        return summary, cover, outreach[:600], [str(x) for x in q.get("questions", [])][:5]


def _facts(cand: Candidate, job: Job, match) -> dict[str, Any]:
    matched = list(match.matched_skills) if match else []
    missing = list(match.missing_skills)[:6] if match else []
    visa = job.visa_assessment
    return {
        "Candidate": cand.full_name,
        "Current role": f"{cand.current_designation or ''} at {cand.current_organization or ''}",
        "Years of experience": f"{float(cand.years_experience):g}"
        if cand.years_experience
        else None,
        "Previous employers": ", ".join(cand.previous_organizations or []),
        "Candidate summary": cand.summary,
        "Job title": job.title,
        "Company": job.company.name if job.company else None,
        "Location": ", ".join(filter(None, [job.city, job.country])),
        "Matched skills": ", ".join(matched[:10]),
        "Skills to address": ", ".join(missing),
        "Needs visa sponsorship": {True: "yes", False: "no"}.get(cand.requires_visa_sponsorship),
        "Posting's visa stance": visa.classification.value if visa else None,
        "Job description (excerpt)": job.description[:2500],
    }


def _template_texts(f: dict[str, Any]) -> tuple[str, str, str, list[str]]:
    skills = f.get("Matched skills") or "cloud architecture"
    first_skills = ", ".join(skills.split(", ")[:3])
    years = f.get("Years of experience") or "several"
    company = f.get("Company") or "your company"
    summary = (
        f"{f.get('Current role', '').strip(' at')} with {years} years of experience. "
        f"Hands-on depth in {skills}. Focused on secure, scalable cloud platforms and "
        "migrations."
    )
    cover = (
        f"Dear Hiring Team at {company},\n\n"
        f"I am applying for the {f['Job title']} position. I have {years} years of experience "
        f"and currently work as {f.get('Current role', '').strip()}. My background in "
        f"{first_skills} matches what you describe in the role.\n\n"
        "[Add one concrete example from your experience that shows impact on a similar "
        "problem.]\n\n"
        f"I would welcome the chance to discuss how I can contribute to {company}.\n\n"
        f"Kind regards,\n{f['Candidate']}"
    )
    ask_visa = (
        " Could you also confirm whether visa sponsorship is possible for this role?"
        if f.get("Needs visa sponsorship") == "yes"
        and f.get("Posting's visa stance") != "explicit_sponsorship"
        else ""
    )
    outreach = (
        f"Hi, I came across the {f['Job title']} role at {company}. With {years} years "
        f"in {first_skills}, I think I'd be a strong fit. Would you be open to a short "
        f"chat?{ask_visa} Thanks, {f['Candidate']}"
    )
    return summary, cover, outreach[:600], []


def _interview_prep(f: dict[str, Any], job: Job, extra: list[str]) -> dict[str, Any]:
    skills = [s for s in (f.get("Matched skills") or "").split(", ") if s]
    questions = [q for s in skills for q in QUESTION_BANK.get(s, [])][:10] or GENERIC_QUESTIONS
    gaps = [s for s in (f.get("Skills to address") or "").split(", ") if s]
    visa = job.visa_assessment
    sal = job.salary_assessment
    ask = [
        "What does success look like in the first 6 months?",
        "How are architecture decisions made and reviewed?",
    ]
    if f.get("Needs visa sponsorship") == "yes" and (
        not visa or visa.classification.value != "explicit_sponsorship"
    ):
        ask.insert(
            0, "Is visa / work-permit sponsorship possible for this role, and who covers the costs?"
        )
    if sal and not sal.has_actual_salary:
        ask.append("What is the salary range for this role?")
    return {
        "technical_questions": questions + [q for q in extra if q not in questions],
        "prepare_for_gaps": [
            f"Be ready to discuss {g}: related experience or how you would ramp up." for g in gaps
        ],
        "strengths_to_highlight": skills[:6],
        "questions_to_ask": ask,
    }


async def _write_tailored_cv(
    s: AsyncSession, cand: Candidate, job: Job, f: dict[str, Any], summary: str
) -> CandidateResume:
    from docx import Document

    doc = Document()
    doc.add_heading(cand.full_name, 0)
    doc.add_paragraph(cand.current_designation or "")
    doc.add_heading("Profile", level=1)
    doc.add_paragraph(summary)
    matched = [x for x in (f.get("Matched skills") or "").split(", ") if x]
    others = [sk.name for sk in cand.skills if sk.name not in matched]
    doc.add_heading("Key skills for this role", level=1)
    doc.add_paragraph(", ".join(matched) or "—")
    doc.add_heading("Other skills", level=1)
    doc.add_paragraph(", ".join(others) or "—")
    primary = next((r for r in cand.resumes if r.is_primary), None)
    certs = (primary.parsed_data or {}).get("certifications") if primary else None
    if certs:
        doc.add_heading("Certifications", level=1)
        for c in certs:
            doc.add_paragraph(c, style="List Bullet")
    doc.add_heading("Experience", level=1)
    for e in cand.experiences:
        when = " – ".join(
            filter(
                None,
                [str(e.start_date or ""), "present" if e.is_current else str(e.end_date or "")],
            )
        )
        doc.add_heading(f"{e.title}, {e.organization}" + (f" ({when})" if when else ""), level=2)
        if e.description:
            doc.add_paragraph(e.description)
        for h in e.highlights or []:
            doc.add_paragraph(h, style="List Bullet")
    buf = io.BytesIO()
    doc.save(buf)
    content = buf.getvalue()

    rid = uuid.uuid4()
    path = Path(get_settings().upload_dir) / str(cand.id) / f"{rid}.docx"
    await asyncio.to_thread(_write, path, content)
    company = job.company.name if job.company else "job"
    resume = CandidateResume(
        id=rid,
        candidate_id=cand.id,
        version_label=f"Tailored: {company}"[:100],
        original_filename=f"CV - {company} - {job.title}"[:250] + ".docx",
        content_type=DOCX_MIME,
        storage_path=str(path),
        sha256=hashlib.sha256(content + rid.bytes).hexdigest(),
        size_bytes=len(content),
        is_primary=False,
        parent_resume_id=primary.id if primary else None,
        job_id=job.id,
        parsed_at=datetime.now(UTC),
        parsed_data={"generated": True},
    )
    s.add(resume)
    await s.flush()
    return resume


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
