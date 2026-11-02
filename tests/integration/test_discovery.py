"""Discovery pipeline against a real database, with in-memory fake connectors."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from agents.discovery.service import DiscoveryService, expire_stale_jobs
from common.enums import ExecutionStatus, JobStatus, SourceType
from connectors.base import Connector, RawJob, SearchQuery
from connectors.http import PoliteClient
from database.models import AgentExecution, Candidate, Job, JobSource, SearchConfiguration
from database.session import create_session_factory

pytestmark = pytest.mark.integration

FEEDS: dict[str, list[RawJob] | Exception] = {}


class FakeConnector(Connector):
    name = "fake"
    complete_listing = True

    def __init__(self, key: str):
        self.key = key

    async def fetch(self, query: SearchQuery) -> AsyncIterator[RawJob]:
        feed = FEEDS[self.key]
        if isinstance(feed, Exception):
            raise feed
        for job in feed:
            yield job


def raw(
    ext: str,
    title: str = "Senior Cloud Architect",
    company: str = "Acme GmbH",
    location: str = "Berlin, Germany",
    **kw,
) -> RawJob:
    return RawJob(
        external_id=ext,
        url=f"https://jobs.test/{ext}",
        title=title,
        company=company,
        location_raw=location,
        description=kw.pop("description", "8+ years of experience"),
        **kw,
    )


@pytest.fixture
async def setup(engine):
    FEEDS.clear()
    factory = create_session_factory(engine)
    async with factory() as s:
        cand = Candidate(
            full_name="T", target_roles=["Cloud Architect"], preferred_countries=["DE", "NL"]
        )
        s.add(cand)
        await s.flush()
        for key in ("a", "b"):
            s.add(JobSource(key=key, name=key, connector="fake", source_type=SourceType.API))
        cfg = SearchConfiguration(
            candidate_id=cand.id,
            name="main",
            keywords=["cloud architect"],
            countries=["DE", "NL"],
            excluded_keywords=["intern"],
        )
        s.add(cfg)
        await s.commit()
        config_id = cfg.id
    service = DiscoveryService(
        factory,
        connector_factory=lambda src, client: FakeConnector(src.key),
        client_factory=lambda: PoliteClient(),
    )
    return service, factory, config_id


async def _jobs(factory) -> list[Job]:
    async with factory() as s:
        return list(await s.scalars(select(Job).order_by(Job.external_id)))


async def test_filters_and_creates(setup):
    service, factory, cfg = setup
    FEEDS["a"] = [
        raw("1"),
        raw("2", title="Cloud Support Engineer"),  # title not relevant
        raw("3", location="Paris, France"),  # country not targeted
        raw("4", title="Cloud Architect Intern"),  # excluded keyword
        raw("5", location="Remote - EMEA", company="Other"),  # Europe-wide remote: kept
        raw("6", location="Atlantis"),  # unknown location
        raw("1"),  # repeated in feed
    ]
    FEEDS["b"] = []
    result = await service.run(cfg)
    stats = result.per_source["a"]
    assert result.status == ExecutionStatus.SUCCEEDED
    assert (stats.fetched, stats.relevant, stats.created) == (7, 2, 2)
    assert stats.skipped == {
        "title_not_relevant": 2,
        "country_not_targeted": 1,
        "repeated_in_feed": 1,
        "country_unknown": 1,
    }
    # the excluded keyword is applied by title_matches, so it counts as not relevant
    jobs = await _jobs(factory)
    assert [j.external_id for j in jobs] == ["1", "5"]
    j1 = jobs[0]
    assert (j1.country, j1.city, j1.seniority, float(j1.experience_min_years)) == (
        "DE",
        "Berlin",
        "senior",
        8.0,
    )
    assert jobs[1].country is None


async def test_rerun_updates_without_duplicating_and_closes_missing(setup):
    service, factory, cfg = setup
    FEEDS["a"] = [raw("1"), raw("2", title="Cloud Architect AWS")]
    FEEDS["b"] = []
    await service.run(cfg)

    FEEDS["a"] = [raw("1", description="Now 10+ years of experience")]  # 2 disappeared
    second = await service.run(cfg)
    s = second.per_source["a"]
    assert (s.created, s.updated, s.closed) == (0, 1, 1)
    jobs = {j.external_id: j for j in await _jobs(factory)}
    assert len(jobs) == 2
    assert jobs["1"].status == JobStatus.ACTIVE and float(jobs["1"].experience_min_years) == 10
    assert jobs["2"].status == JobStatus.CLOSED

    FEEDS["a"] = [raw("1"), raw("2", title="Cloud Architect AWS")]  # reposted
    third = await service.run(cfg)
    assert third.per_source["a"].reactivated == 1


async def test_cross_source_duplicate_points_to_canonical(setup):
    service, factory, cfg = setup
    FEEDS["a"] = [raw("1", title="Sr. Cloud Architect (m/w/d)", company="Acme GmbH")]
    FEEDS["b"] = [raw("x9", title="Senior Cloud Architect", company="ACME")]
    result = await service.run(cfg)
    assert result.per_source["a"].created == 1
    assert result.per_source["b"].duplicates == 1
    jobs = {j.external_id: j for j in await _jobs(factory)}
    assert jobs["x9"].canonical_job_id == jobs["1"].id


async def test_failing_source_is_isolated_and_recorded(setup):
    service, factory, cfg = setup
    FEEDS["a"] = [raw("1")]
    FEEDS["b"] = RuntimeError("board offline")
    result = await service.run(cfg, trigger="schedule")
    assert result.status == ExecutionStatus.SUCCEEDED and result.created == 1
    async with factory() as s:
        ex = await s.get(AgentExecution, result.execution_id)
        src_b = await s.scalar(select(JobSource).where(JobSource.key == "b"))
        src_a = await s.scalar(select(JobSource).where(JobSource.key == "a"))
    assert ex.items_failed == 1 and "board offline" in ex.error_message
    assert ex.details["per_source"]["a"]["created"] == 1
    assert ex.decisions[0]["decision"] == "created"
    assert src_b.last_error and src_b.last_success_at is None
    assert src_a.last_success_at is not None and src_a.last_error is None


async def test_failed_source_does_not_close_jobs(setup):
    service, factory, cfg = setup
    FEEDS["a"], FEEDS["b"] = [raw("1")], []
    await service.run(cfg)
    FEEDS["a"] = RuntimeError("timeout")
    result = await service.run(cfg)
    assert result.per_source["a"].closed == 0
    assert (await _jobs(factory))[0].status == JobStatus.ACTIVE


async def test_all_sources_failing_marks_run_failed(setup):
    service, _, cfg = setup
    FEEDS["a"] = FEEDS["b"] = RuntimeError("down")
    assert (await service.run(cfg)).status == ExecutionStatus.FAILED


async def test_expiry(setup):
    service, factory, cfg = setup
    FEEDS["a"] = [
        raw("old"),
        raw("deadline", expires_at=datetime.now(UTC) - timedelta(days=1)),
        raw("fresh"),
    ]
    FEEDS["b"] = []
    await service.run(cfg)
    async with factory() as s:
        old = await s.scalar(select(Job).where(Job.external_id == "old"))
        old.last_seen_at = datetime.now(UTC) - timedelta(days=30)
        await s.commit()
    assert await expire_stale_jobs(factory, expiry_days=21) == 2
    status = {j.external_id: j.status for j in await _jobs(factory)}
    assert status == {
        "deadline": JobStatus.EXPIRED,
        "fresh": JobStatus.ACTIVE,
        "old": JobStatus.EXPIRED,
    }


async def test_max_results_per_source(setup):
    service, factory, cfg = setup
    async with factory() as s:
        (await s.get(SearchConfiguration, cfg)).max_results_per_source = 2
        await s.commit()
    FEEDS["a"] = [raw(str(i), title=f"Cloud Architect {i}") for i in range(5)]
    FEEDS["b"] = []
    result = await service.run(cfg)
    assert result.per_source["a"].created == 2
    assert result.per_source["a"].skipped["max_results_reached"] == 3
    async with factory() as s:
        assert await s.scalar(select(func.count()).select_from(Job)) == 2
