import json

import httpx
import pytest
from pydantic import ValidationError

from common.enums import RemoteType
from connectors.adzuna import AdzunaConnector, AdzunaNotConfigured
from connectors.arbeitnow import ArbeitnowConnector
from connectors.base import SearchQuery
from connectors.greenhouse import GreenhouseConnector
from connectors.http import PoliteClient
from connectors.lever import LeverConnector
from connectors.rss import RssConnector

GREENHOUSE = {
    "jobs": [
        {
            "id": 101,
            "title": " Senior Cloud Architect ",
            "company_name": "Acme",
            "absolute_url": "https://acme.test/jobs/101",
            "updated_at": "2026-10-30T08:00:00-04:00",
            "first_published": "2026-10-01T09:00:00-04:00",
            "application_deadline": None,
            "location": {"name": "Berlin"},
            "offices": [{"name": "Berlin", "location": "Berlin, Berlin, Germany"}],
            "departments": [{"name": "Platform"}],
            "metadata": [{"name": "Time Type", "value": "Full time"}],
            "content": "&lt;p&gt;8+ years of experience with AWS.&lt;/p&gt;",
        }
    ],
    "meta": {"total": 1},
}

LEVER = [
    {
        "id": "abc-1",
        "text": "DevOps Architect",
        "hostedUrl": "https://jobs.lever.co/x/abc-1",
        "applyUrl": "https://jobs.lever.co/x/abc-1/apply",
        "createdAt": 1790000000000,
        "country": "NL",
        "workplaceType": "hybrid",
        "categories": {"location": "Amsterdam", "commitment": "Permanent", "team": "Infra"},
        "description": "<p>Kubernetes</p>",
        "lists": [{"text": "You", "content": "<li>Terraform</li>"}],
        "additional": "",
        "salaryRange": {
            "min": 90000,
            "max": 110000,
            "currency": "EUR",
            "interval": "per-year-salary",
        },
    }
]


def _transport(routes: dict[str, object]):
    def handler(req: httpx.Request):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        for prefix, body in routes.items():
            if str(req.url).startswith(prefix):
                if callable(body):
                    return body(req)
                if isinstance(body, str):
                    return httpx.Response(200, text=body)
                return httpx.Response(200, json=body)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


async def _collect(connector_cls, config, routes, query=None):
    async with PoliteClient(transport=_transport(routes), default_rate_per_minute=6000) as c:
        conn = connector_cls(config, c)
        return [j async for j in conn.fetch(query or SearchQuery())]


async def test_greenhouse_parsing():
    jobs = await _collect(
        GreenhouseConnector,
        {"board_token": "acme"},
        {"https://boards-api.greenhouse.io/v1/boards/acme/jobs": GREENHOUSE},
    )
    (j,) = jobs
    assert j.external_id == "101" and j.title == "Senior Cloud Architect"
    assert j.description == "8+ years of experience with AWS."
    assert "Berlin, Berlin, Germany" in j.location_raw
    assert j.posted_at.isoformat().startswith("2026-10-01")
    assert j.employment_type == "Full time" and j.tags == ["Platform"]
    assert "content" not in j.raw


def test_greenhouse_rejects_bad_token():
    with pytest.raises(ValidationError):
        GreenhouseConnector({"board_token": "../etc"}, client=None)  # type: ignore[arg-type]


async def test_lever_parsing_uses_country_workplace_and_real_salary():
    (j,) = await _collect(
        LeverConnector,
        {"site": "x", "company_name": "X"},
        {"https://api.lever.co/v0/postings/x": LEVER},
    )
    assert j.country == "NL" and j.remote_type == RemoteType.HYBRID
    assert (j.salary_min, j.salary_max, j.salary_currency, j.salary_period) == (
        90000,
        110000,
        "EUR",
        "year",
    )
    assert "Terraform" in j.description and j.company == "X"


async def test_arbeitnow_paginates_and_prefilters_titles():
    pages = {
        1: {
            "data": [
                {
                    "slug": "a",
                    "company_name": "C",
                    "title": "Cloud Architect (m/w/d)",
                    "description": "<p>x</p>",
                    "remote": True,
                    "url": "https://an.test/a",
                    "tags": [],
                    "job_types": [],
                    "location": "Berlin",
                    "created_at": 1790000000,
                },
                {
                    "slug": "b",
                    "company_name": "C",
                    "title": "Bäcker",
                    "description": "",
                    "remote": False,
                    "url": "https://an.test/b",
                    "tags": [],
                    "job_types": [],
                    "location": "Köln",
                    "created_at": 1790000000,
                },
            ],
            "links": {"next": "page2"},
        },
        2: {"data": [], "links": {"next": None}},
    }
    seen_pages = []

    def api(req: httpx.Request):
        page = int(req.url.params["page"])
        seen_pages.append(page)
        return httpx.Response(200, json=pages[page])

    jobs = await _collect(
        ArbeitnowConnector,
        {},
        {"https://www.arbeitnow.com/api": api},
        SearchQuery(keywords=["cloud architect"]),
    )
    assert [j.external_id for j in jobs] == ["a"]
    assert jobs[0].remote_type == RemoteType.REMOTE and jobs[0].raw["default_country"] == "DE"
    assert seen_pages == [1, 2]


async def test_adzuna_requires_keys(monkeypatch):
    from common import config

    monkeypatch.setattr(config.get_settings(), "adzuna_app_id", None)
    with pytest.raises(AdzunaNotConfigured):
        await _collect(AdzunaConnector, {}, {}, SearchQuery(countries=["DE"]))


async def test_adzuna_drops_predicted_salaries_and_skips_unsupported_countries(monkeypatch):
    from pydantic import SecretStr

    from common import config

    s = config.get_settings()
    monkeypatch.setattr(s, "adzuna_app_id", "id")
    monkeypatch.setattr(s, "adzuna_app_key", SecretStr("key"))
    requested = []

    def api(req: httpx.Request):
        requested.append(req.url.path)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": 1,
                        "title": "Cloud Architect",
                        "redirect_url": "https://adz.test/1",
                        "created": "2026-10-20T10:00:00Z",
                        "company": {"display_name": "A"},
                        "location": {
                            "display_name": "Berlin",
                            "area": ["Deutschland", "Berlin", "Berlin"],
                        },
                        "salary_min": 80000,
                        "salary_max": 90000,
                        "salary_is_predicted": "1",
                    },
                    {
                        "id": 2,
                        "title": "Cloud Architect",
                        "redirect_url": "https://adz.test/2",
                        "created": "2026-10-20T10:00:00Z",
                        "company": {"display_name": "B"},
                        "location": {"display_name": "Munich"},
                        "salary_min": 95000,
                        "salary_max": 99000,
                        "salary_is_predicted": "0",
                    },
                ]
            },
        )

    jobs = await _collect(
        AdzunaConnector,
        {"max_pages": 1, "results_per_page": 50},
        {"https://api.adzuna.com": api},
        SearchQuery(keywords=["cloud architect"], countries=["DE", "IE"]),
    )
    assert requested == ["/v1/api/jobs/de/search/1"]
    by_id = {j.external_id: j for j in jobs}
    assert by_id["1"].salary_min is None  # predicted: not advertised pay
    assert by_id["2"].salary_min == 95000 and by_id["2"].salary_currency == "EUR"


async def test_rss_feed():
    feed = """<?xml version="1.0"?><rss version="2.0"><channel><title>Jobs</title>
      <item><title>Infrastructure Architect</title><link>https://feed.test/j/1</link>
      <guid>job-1</guid><description>&lt;p&gt;Remote role&lt;/p&gt;</description>
      <pubDate>Mon, 26 Oct 2026 10:00:00 GMT</pubDate></item></channel></rss>"""
    (j,) = await _collect(
        RssConnector,
        {"feed_url": "https://feed.test/rss", "default_country": "IE"},
        {"https://feed.test/rss": feed},
    )
    assert j.external_id == "job-1" and j.description == "Remote role"
    assert j.raw["default_country"] == "IE" and j.posted_at.day == 26
    json.dumps(j.raw)  # raw payload must be JSON-serialisable for the JSONB column
