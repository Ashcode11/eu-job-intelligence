"""Load the sample candidate profile and fictional sample jobs. Safe to run repeatedly.

python -m scripts.seed                # candidate + sample jobs
python -m scripts.seed --no-jobs      # candidate only
"""

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from common.enums import RemoteType, SkillSource, SourceType
from common.logging import configure_logging, get_logger
from connectors.normalize import content_hash, dedup_hash, normalize_company_name, normalize_title
from database.models import (
    Candidate,
    CandidateExperience,
    CandidateSkill,
    Company,
    Job,
    JobSource,
    SearchConfiguration,
)
from database.session import create_engine, create_session_factory

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SAMPLE_DIR = DATA_DIR / "sample"
log = get_logger("seed")


async def seed_candidate(session) -> Candidate:
    existing = await session.scalar(select(Candidate).order_by(Candidate.created_at).limit(1))
    if existing:
        log.info("candidate_exists", candidate_id=str(existing.id))
        return existing
    data = json.loads((SAMPLE_DIR / "candidate.json").read_text())
    skills = data.pop("skills")
    experiences = data.pop("experiences")
    configs = data.pop("search_configurations")
    profile = {k: v for k, v in data.items() if not k.startswith("_") and v is not None}
    candidate = Candidate(**profile)
    session.add(candidate)
    await session.flush()
    for s in skills:
        session.add(CandidateSkill(candidate_id=candidate.id, source=SkillSource.MANUAL, **s))
    for e in experiences:
        session.add(CandidateExperience(candidate_id=candidate.id, **e))
    for c in configs:
        session.add(SearchConfiguration(candidate_id=candidate.id, **c))
    log.info("candidate_created", candidate_id=str(candidate.id), skills=len(skills))
    return candidate


async def seed_sources(session) -> int:
    """Insert default sources that don't exist yet. Never overwrites your edits."""
    from connectors.registry import get_connector_class

    data = json.loads((DATA_DIR / "sources.json").read_text())
    existing = set(await session.scalars(select(JobSource.key)))
    created = 0
    for src in data["sources"]:
        if src["key"] in existing:
            continue
        get_connector_class(src["connector"]).config_model.model_validate(src["config"])
        session.add(
            JobSource(
                key=src["key"],
                name=src["name"],
                connector=src["connector"],
                config=src["config"],
                source_type=SourceType.ATS_BOARD
                if src["connector"] in ("greenhouse", "lever")
                else SourceType.API,
                terms_url=src.get("terms_url"),
                enabled=src["enabled"],
                rate_limit_per_minute=src["rate_limit_per_minute"],
                respects_robots_txt=True,
            )
        )
        created += 1
    log.info("sources_loaded", created=created, total=len(data["sources"]))
    return created


async def seed_jobs(session) -> int:
    data = json.loads((SAMPLE_DIR / "jobs.json").read_text())
    src = data["source"]
    source = await session.scalar(select(JobSource).where(JobSource.key == src["key"]))
    if source is None:
        source = JobSource(
            key=src["key"],
            name=src["name"],
            source_type=SourceType(src["source_type"]),
            connector=src["connector"],
            enabled=False,
        )  # sample data is never "discovered" on a schedule
        session.add(source)
        await session.flush()

    now = datetime.now(UTC)
    created = 0
    for j in data["jobs"]:
        norm_company = normalize_company_name(j["company"])
        company = await session.scalar(
            select(Company).where(Company.normalized_name == norm_company)
        )
        if company is None:
            company = Company(name=j["company"], normalized_name=norm_company)
            session.add(company)
            await session.flush()

        job = await session.scalar(
            select(Job).where(Job.source_id == source.id, Job.external_id == j["external_id"])
        )
        fields = dict(
            company_id=company.id,
            url=j["url"],
            apply_url=j["url"],
            title=j["title"],
            normalized_title=normalize_title(j["title"]),
            description=j["description"],
            country=j["country"],
            city=j["city"],
            location_raw=f"{j['city']}, {j['country']}",
            remote_type=RemoteType(j["remote_type"]),
            employment_type=j.get("employment_type"),
            seniority=j.get("seniority"),
            experience_min_years=j.get("experience_min_years"),
            required_skills=j.get("required_skills", []),
            salary_min=j.get("salary_min"),
            salary_max=j.get("salary_max"),
            salary_currency=j.get("salary_currency"),
            salary_period=j.get("salary_period"),
            salary_raw=j.get("salary_raw"),
            posted_at=now - timedelta(days=j.get("posted_days_ago", 0)),
            last_seen_at=now,
            dedup_hash=dedup_hash(j["company"], j["title"], j["country"], j["city"]),
            content_hash=content_hash(j["title"], j["description"], j.get("salary_raw")),
            raw_payload=j,
        )
        if job is None:
            session.add(
                Job(source_id=source.id, external_id=j["external_id"], discovered_at=now, **fields)
            )
            created += 1
        else:
            for k, v in fields.items():
                setattr(job, k, v)
    log.info("sample_jobs_loaded", created=created, total=len(data["jobs"]))
    return created


async def main(with_jobs: bool) -> None:
    configure_logging(json=False)
    engine = create_engine(null_pool=True)
    factory = create_session_factory(engine)
    async with factory() as session:
        await seed_candidate(session)
        await seed_sources(session)
        if with_jobs:
            await seed_jobs(session)
        await session.commit()
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-jobs", action="store_true")
    asyncio.run(main(with_jobs=not parser.parse_args().no_jobs))
