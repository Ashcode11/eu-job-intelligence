"""CV Intelligence Agent.

- Extracts text from PDF/DOCX and deterministic facts (skills, certifications, years).
- Compares CV skills with the skills inventory and with demand across active jobs.
- Optionally asks the local LLM for a short summary and notable projects.
- Embeds the CV for semantic matching.

It never edits the candidate profile: found skills are stored as *suggestions* that the
user accepts through the API.
"""

import asyncio
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents.cv_intelligence.parser import UnsupportedResume, analyse_text, extract_text
from agents.llm.ollama import LLMUnavailable, OllamaClient
from agents.skills import canonical
from common.enums import ExecutionStatus, JobStatus
from common.logging import get_logger
from database.models import AgentExecution, CandidateResume, CandidateSkill, Job

log = get_logger(__name__)
AGENT_NAME = "cv_intelligence"

_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "projects": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        "strengths": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
    },
    "required": ["summary", "projects", "strengths"],
}


class CVIntelligenceService:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], llm: OllamaClient | None = None
    ) -> None:
        self.session_factory = session_factory
        self.llm = llm

    async def process(self, resume_id: Any, *, trigger: str = "upload") -> dict[str, Any]:
        started, t0 = datetime.now(UTC), time.perf_counter()
        async with self.session_factory() as session:
            resume = await session.get(CandidateResume, resume_id)
            if resume is None:
                raise ValueError(f"Resume {resume_id} not found")
            execution = AgentExecution(
                agent_name=AGENT_NAME,
                trigger=trigger,
                status=ExecutionStatus.RUNNING,
                started_at=started,
                details={"resume_id": str(resume_id)},
            )
            session.add(execution)
            await session.flush()
            try:
                content = await asyncio.to_thread(Path(resume.storage_path).read_bytes)
                text = extract_text(content, resume.content_type)
            except (OSError, UnsupportedResume, Exception) as exc:  # pypdf raises many types
                resume.parse_error = f"{type(exc).__name__}: {exc}"[:500]
                resume.parsed_at = datetime.now(UTC)
                execution.status = ExecutionStatus.FAILED
                execution.error_type = type(exc).__name__
                execution.error_message = resume.parse_error
                _finish(execution, t0)
                await session.commit()
                return {"status": "failed", "error": resume.parse_error}

            facts = analyse_text(text, datetime.now(UTC).year)
            inventory = {
                canonical(s.name).lower()
                for s in await session.scalars(
                    select(CandidateSkill).where(CandidateSkill.candidate_id == resume.candidate_id)
                )
            }
            cv_skills = [s["name"] for s in facts["skills"]]
            facts["suggested_skills"] = [
                s for s in facts["skills"] if s["name"].lower() not in inventory
            ]
            facts["demand"] = await _skill_demand(session, set(cv_skills) | {n for n in inventory})

            decisions = [
                {"decision": "skills_found", "count": len(cv_skills)},
                {"decision": "suggestions", "count": len(facts["suggested_skills"])},
            ]
            if self.llm and await self.llm.available():
                try:
                    facts["llm"] = await self.llm.chat_json(
                        "You summarise CVs for a job-search tool. Use only facts present in "
                        "the CV text. Do not invent employers, dates or numbers.",
                        f"CV text:\n{text[:12000]}\n\nReturn a 3-sentence professional "
                        "summary, up to 6 notable projects, and up to 6 technical strengths.",
                        _SUMMARY_SCHEMA,
                    )
                    resume.embedding = (await self.llm.embed([text]))[0]
                except LLMUnavailable as exc:
                    decisions.append({"decision": "llm_skipped", "reason": str(exc)[:200]})
            else:
                decisions.append({"decision": "llm_skipped", "reason": "Ollama unavailable"})

            resume.parsed_text = text
            resume.parsed_data = facts
            resume.parsed_at = datetime.now(UTC)
            resume.parse_error = None
            execution.status = ExecutionStatus.SUCCEEDED
            execution.items_processed = 1
            execution.decisions = decisions
            if self.llm:
                execution.llm_model = self.llm.chat_model
                execution.llm_calls = self.llm.usage.calls
                execution.llm_prompt_tokens = self.llm.usage.prompt_tokens
                execution.llm_completion_tokens = self.llm.usage.completion_tokens
            _finish(execution, t0)
            await session.commit()
            log.info(
                "resume_parsed",
                resume_id=str(resume_id),
                skills=len(cv_skills),
                suggestions=len(facts["suggested_skills"]),
            )
            return {
                "status": "succeeded",
                "skills": len(cv_skills),
                "suggestions": len(facts["suggested_skills"]),
            }


async def _skill_demand(session: AsyncSession, have: set[str]) -> dict[str, Any]:
    """Which skills active jobs ask for that the candidate lacks (strengths vs gaps)."""
    rows = await session.scalars(
        select(Job.required_skills).where(
            Job.status == JobStatus.ACTIVE, Job.canonical_job_id.is_(None)
        )
    )
    counts: Counter[str] = Counter()
    total = 0
    for skills in rows:
        total += 1
        counts.update(set(skills or []))
    have_l = {h.lower() for h in have}
    return {
        "jobs_considered": total,
        "strengths": [
            {"skill": s, "jobs": n} for s, n in counts.most_common() if s.lower() in have_l
        ][:10],
        "missing_in_demand": [
            {"skill": s, "jobs": n} for s, n in counts.most_common() if s.lower() not in have_l
        ][:10],
    }


def _finish(execution: AgentExecution, t0: float) -> None:
    execution.finished_at = datetime.now(UTC)
    execution.duration_ms = int((time.perf_counter() - t0) * 1000)
