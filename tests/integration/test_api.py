"""End-to-end API tests against a real (migrated) PostgreSQL and Redis."""

import io

import pytest
from sqlalchemy import func, select

from database.models import AuditLog
from scripts.seed import seed_candidate, seed_jobs, seed_sources

pytestmark = pytest.mark.integration


async def _seed(session, jobs: bool = True):
    await seed_candidate(session)
    await seed_sources(session)
    if jobs:
        await seed_jobs(session)
    await session.commit()


async def test_health(client):
    assert (await client.get("/health/live")).json() == {"status": "ok"}
    r = await client.get("/health/ready")
    assert r.status_code == 200, r.text
    assert r.json()["checks"] == {"postgres": "ok", "redis": "ok"}


async def test_metrics_exposed(client):
    await client.get("/health/live")
    r = await client.get("/metrics")
    assert "eujobs_http_requests_total" in r.text


async def test_api_requires_key(client):
    r = await client.get("/api/v1/candidate", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401
    r = await client.get("/api/v1/candidate", headers={"X-API-Key": ""})
    assert r.status_code == 401


async def test_request_id_echoed(client):
    r = await client.get("/health/live", headers={"X-Request-ID": "abc123"})
    assert r.headers["X-Request-ID"] == "abc123"


async def test_candidate_missing_then_create(client):
    assert (await client.get("/api/v1/candidate")).status_code == 404
    r = await client.post("/api/v1/candidate", json={"full_name": "Test Person"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["has_eu_work_authorization"] is None
    assert "Existing EU work authorization" in body["profile_completeness"]
    assert (await client.post("/api/v1/candidate", json={"full_name": "Again"})).status_code == 409


async def test_seeded_profile_does_not_assume_authorization(client, session):
    await _seed(session, jobs=False)
    body = (await client.get("/api/v1/candidate")).json()
    assert body["current_organization"] == "Nagarro"
    assert body["preferred_countries"] == ["DE", "NL", "IE", "SE", "DK", "FI", "BE", "LU"]
    assert len(body["target_roles"]) == 10
    for field in (
        "citizenship",
        "has_eu_work_authorization",
        "requires_visa_sponsorship",
        "open_to_relocation",
    ):
        assert body[field] is None


async def test_update_profile_and_audit(client, session):
    await _seed(session, jobs=False)
    r = await client.patch(
        "/api/v1/candidate",
        json={
            "has_eu_work_authorization": False,
            "requires_visa_sponsorship": True,
            "open_to_relocation": True,
            "min_salary_eur": 80000,
            "preferred_countries": ["de", "at"],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["requires_visa_sponsorship"] is True
    assert body["preferred_countries"] == ["DE", "AT"]
    count = await session.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == "candidate.update")
    )
    assert count == 1


async def test_invalid_weights_rejected(client, session):
    await _seed(session, jobs=False)
    r = await client.patch("/api/v1/candidate", json={"match_weights": {"technical_skills": 1.0}})
    assert r.status_code == 422


async def test_skill_crud_and_case_insensitive_duplicate(client, session):
    await _seed(session, jobs=False)
    r = await client.post("/api/v1/candidate/skills", json={"name": "ArgoCD", "proficiency": 3})
    assert r.status_code == 201, r.text
    skill_id = r.json()["id"]
    assert (
        await client.post("/api/v1/candidate/skills", json={"name": "argocd"})
    ).status_code == 409
    r = await client.patch(f"/api/v1/candidate/skills/{skill_id}", json={"proficiency": 4})
    assert r.json()["proficiency"] == 4
    assert (await client.delete(f"/api/v1/candidate/skills/{skill_id}")).status_code == 204


async def test_resume_upload_validation(client, session):
    await _seed(session, jobs=False)
    pdf = b"%PDF-1.4\n%sample\n"
    r = await client.post(
        "/api/v1/candidate/resumes",
        files={"file": ("cv.pdf", io.BytesIO(pdf), "application/pdf")},
        data={"version_label": "v1"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["is_primary"] is True
    dup = await client.post(
        "/api/v1/candidate/resumes",
        files={"file": ("again.pdf", io.BytesIO(pdf), "application/pdf")},
    )
    assert dup.status_code == 409
    bad = await client.post(
        "/api/v1/candidate/resumes",
        files={"file": ("cv.pdf", io.BytesIO(b"not a pdf"), "application/pdf")},
    )
    assert bad.status_code == 415


async def test_jobs_list_filter_and_detail(client, session):
    await _seed(session)
    r = await client.get("/api/v1/jobs")
    assert r.status_code == 200, r.text
    page = r.json()
    assert page["total"] == 8
    r = await client.get("/api/v1/jobs", params={"country": ["de", "nl"]})
    assert {j["country"] for j in r.json()["items"]} == {"DE", "NL"}
    r = await client.get("/api/v1/jobs", params={"q": "migration"})
    assert any("Migration" in j["title"] for j in r.json()["items"])
    job_id = page["items"][0]["id"]
    detail = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    assert detail["description"]
    assert detail["match"] is None and detail["visa"] is None  # agents not run yet


async def test_seed_is_idempotent(client, session):
    await _seed(session)
    await _seed(session)
    assert (await client.get("/api/v1/jobs")).json()["total"] == 8


async def test_application_tracker_flow(client, session):
    await _seed(session)
    job_id = (await client.get("/api/v1/jobs")).json()["items"][0]["id"]
    r = await client.post("/api/v1/applications", json={"job_id": job_id})
    assert r.status_code == 201, r.text
    app_id = r.json()["id"]
    assert (await client.post("/api/v1/applications", json={"job_id": job_id})).status_code == 409

    for status_ in ("shortlisted", "prepared", "applied"):
        r = await client.patch(f"/api/v1/applications/{app_id}", json={"status": status_})
        assert r.status_code == 200, r.text
    body = r.json()
    assert body["applied_at"] is not None
    assert [h["to"] for h in body["status_history"]] == [
        "saved",
        "shortlisted",
        "prepared",
        "applied",
    ]
    assert body["job_title"]

    bookmarked = (await client.get("/api/v1/jobs", params={"bookmarked": True})).json()
    assert bookmarked["total"] == 1 and bookmarked["items"][0]["application_status"] == "applied"

    stats = (await client.get("/api/v1/stats/overview")).json()
    assert stats["total_jobs"] == 8 and stats["applications_submitted"] == 1


async def test_agent_summary_lists_known_agents(client, session):
    await _seed(session, jobs=False)
    names = [a["agent_name"] for a in (await client.get("/api/v1/agents/summary")).json()]
    assert "discovery" in names and "visa" in names


async def test_search_config_crud(client, session):
    await _seed(session, jobs=False)
    r = await client.post(
        "/api/v1/candidate/search-configs",
        json={
            "name": "Nordics",
            "keywords": ["cloud architect"],
            "countries": ["se", "dk", "fi"],
            "schedule_cron": "0 7 * * 1-5",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["countries"] == ["SE", "DK", "FI"]
    bad = await client.post(
        "/api/v1/candidate/search-configs", json={"name": "Bad", "schedule_cron": "every day"}
    )
    assert bad.status_code == 422


async def test_rate_limit(client, test_settings, monkeypatch):
    monkeypatch.setattr(test_settings, "rate_limit_default", "3/minute")
    codes = [(await client.get("/api/v1/agents/summary")).status_code for _ in range(5)]
    assert 429 in codes


async def test_sources_api(client, session):
    await _seed(session, jobs=False)
    sources = (await client.get("/api/v1/sources")).json()
    keys = {s["key"] for s in sources}
    assert {"greenhouse:n26", "lever:spotify", "arbeitnow", "adzuna"} <= keys
    adzuna = next(s for s in sources if s["key"] == "adzuna")
    assert adzuna["enabled"] is False

    r = await client.post(
        "/api/v1/sources",
        json={
            "key": "greenhouse:example",
            "name": "Example",
            "connector": "greenhouse",
            "config": {"board_token": "example"},
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["source_type"] == "ats_board"
    bad = await client.post(
        "/api/v1/sources",
        json={
            "key": "greenhouse:bad",
            "name": "Bad",
            "connector": "greenhouse",
            "config": {"board_token": "../../etc"},
        },
    )
    assert bad.status_code == 422
    unknown = await client.post(
        "/api/v1/sources",
        json={"key": "x", "name": "X", "connector": "linkedin-scraper", "config": {}},
    )
    assert unknown.status_code == 422

    sid = r.json()["id"]
    r = await client.patch(f"/api/v1/sources/{sid}", json={"enabled": False})
    assert r.json()["enabled"] is False

    connectors = (await client.get("/api/v1/discovery/connectors")).json()
    assert {c["name"] for c in connectors} == {"adzuna", "arbeitnow", "greenhouse", "lever", "rss"}


async def test_duplicates_hidden_from_job_list(client, session):
    await _seed(session)
    from sqlalchemy import update

    from database.models import Job

    jobs = (await client.get("/api/v1/jobs")).json()["items"]
    await session.execute(
        update(Job).where(Job.id == jobs[1]["id"]).values(canonical_job_id=jobs[0]["id"])
    )
    await session.commit()
    assert (await client.get("/api/v1/jobs")).json()["total"] == 7
    assert (await client.get("/api/v1/jobs", params={"include_duplicates": True})).json()[
        "total"
    ] == 8


async def test_pipeline_and_reprocess_endpoints_enqueue(client, session, queued_tasks):
    await _seed(session)
    r = await client.post("/api/v1/pipeline/run", json={})
    assert r.status_code == 202, r.text
    assert queued_tasks[-1]["task"] == "orchestrator.run_pipeline"
    assert queued_tasks[-1]["kwargs"]["search_config_id"]
    r = await client.post("/api/v1/pipeline/run", json={"analyse_only": True, "force": True})
    assert queued_tasks[-1]["kwargs"] == {"force": True, "trigger": "api"}
    job_id = (await client.get("/api/v1/jobs")).json()["items"][0]["id"]
    r = await client.post(f"/api/v1/jobs/{job_id}/reprocess")
    assert r.status_code == 202
    assert queued_tasks[-1]["kwargs"]["job_ids"] == [job_id]


async def test_resume_upload_enqueues_parse_and_apply_skills(client, session, queued_tasks):
    from sqlalchemy import select

    from database.models import CandidateResume

    await _seed(session, jobs=False)
    r = await client.post(
        "/api/v1/candidate/resumes",
        files={"file": ("cv.pdf", io.BytesIO(b"%PDF-1.4\nx\n"), "application/pdf")},
    )
    rid = r.json()["id"]
    assert queued_tasks[-1] == {"task": "matching.parse_resume", "args": [rid], "kwargs": {}}
    assert (await client.get(f"/api/v1/candidate/resumes/{rid}/analysis")).json() == {
        "status": "pending"
    }

    resume = await session.scalar(select(CandidateResume))
    from datetime import UTC, datetime

    resume.parsed_at = datetime.now(UTC)
    resume.parsed_data = {
        "suggested_skills": [
            {"name": "ArgoCD", "category": "ci_cd"},
            {"name": "Pulumi", "category": "iac"},
        ]
    }
    await session.commit()
    r = await client.post(
        f"/api/v1/candidate/resumes/{rid}/apply-skills", json={"skills": ["argocd"]}
    )
    assert r.status_code == 200, r.text
    assert [s["name"] for s in r.json()] == ["ArgoCD"] and r.json()[0]["source"] == "cv"
    bad = await client.post(
        f"/api/v1/candidate/resumes/{rid}/apply-skills", json={"skills": ["Kotlin"]}
    )
    assert bad.status_code == 422


async def test_application_drafts_approval_flow(client, session, queued_tasks):
    await _seed(session)
    job_id = (await client.get("/api/v1/jobs")).json()["items"][0]["id"]
    app_id = (await client.post("/api/v1/applications", json={"job_id": job_id})).json()["id"]
    assert (await client.post(f"/api/v1/applications/{app_id}/approve-drafts")).status_code == 409
    r = await client.post(f"/api/v1/applications/{app_id}/prepare")
    assert r.status_code == 202 and queued_tasks[-1]["task"] == "application.prepare"
    r = await client.patch(
        f"/api/v1/applications/{app_id}/drafts", json={"cover_letter_draft": "My letter"}
    )
    assert r.json()["cover_letter_draft"] == "My letter"
    r = await client.post(f"/api/v1/applications/{app_id}/approve-drafts")
    assert r.json()["drafts_approved_at"] is not None
    r = await client.patch(
        f"/api/v1/applications/{app_id}/drafts", json={"cover_letter_draft": "Edited again"}
    )
    assert r.json()["drafts_approved_at"] is None  # edits require re-approval
    assert (await client.get(f"/api/v1/applications/{app_id}/tailored-cv")).status_code == 404


async def test_notifications_api(client, session):
    from database.models import Candidate, Notification

    await _seed(session, jobs=False)
    from sqlalchemy import select

    cand = await session.scalar(select(Candidate))
    session.add(
        Notification(
            candidate_id=cand.id,
            channel="dashboard",
            kind="high_match",
            title="t",
            body="b",
            dedup_key="k1",
        )
    )
    await session.commit()
    items = (await client.get("/api/v1/notifications", params={"unread_only": True})).json()
    assert len(items) == 1 and items[0]["status"] == "pending"
    assert (await client.post("/api/v1/notifications/read")).status_code == 204
    assert (await client.get("/api/v1/notifications", params={"unread_only": True})).json() == []
