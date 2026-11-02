"""Adzuna job search API: https://developer.adzuna.com/ (free key required).

Adzuna returns *predicted* salaries for many listings (`salary_is_predicted == "1"`).
Those are Adzuna's estimates, not advertised pay, so they are kept out of the salary fields.
"""

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from pydantic import Field

from common.config import get_settings
from connectors.base import Connector, ConnectorConfig, RawJob, SearchQuery
from connectors.text import detect_remote_type

# Adzuna country endpoints in Europe (no IE, SE, DK, FI or LU endpoint exists).
SUPPORTED = {"AT", "BE", "CH", "DE", "ES", "FR", "GB", "IT", "NL", "PL"}
CURRENCY = {"CH": "CHF", "GB": "GBP", "PL": "PLN"}


class AdzunaConfig(ConnectorConfig):
    results_per_page: int = Field(default=50, ge=1, le=50)
    max_pages: int = Field(default=2, ge=1, le=10)
    max_days_old: int = Field(default=30, ge=1, le=90)


class AdzunaNotConfigured(Exception):
    pass


class AdzunaConnector(Connector):
    name = "adzuna"
    config_model = AdzunaConfig
    base_url = "https://api.adzuna.com/v1/api/jobs"

    async def fetch(self, query: SearchQuery) -> AsyncIterator[RawJob]:
        cfg: AdzunaConfig = self.config  # type: ignore[assignment]
        settings = get_settings()
        if not (settings.adzuna_app_id and settings.adzuna_app_key):
            raise AdzunaNotConfigured("Set ADZUNA_APP_ID and ADZUNA_APP_KEY to use Adzuna")
        countries = [c for c in query.countries if c in SUPPORTED]
        keywords = query.keywords or [""]
        for country in countries:
            for kw in keywords:
                for page in range(1, cfg.max_pages + 1):
                    data = await self.client.get_json(
                        f"{self.base_url}/{country.lower()}/search/{page}",
                        app_id=settings.adzuna_app_id,
                        app_key=settings.adzuna_app_key.get_secret_value(),
                        what_phrase=kw or None,
                        results_per_page=cfg.results_per_page,
                        max_days_old=cfg.max_days_old,
                        **{"content-type": "application/json"},
                    )
                    results = data.get("results", [])  # type: ignore[union-attr]
                    for job in results:
                        yield self._parse(job, country)
                    if len(results) < cfg.results_per_page:
                        break

    @staticmethod
    def _parse(job: dict[str, Any], country: str) -> RawJob:
        predicted = str(job.get("salary_is_predicted", "0")) == "1"
        loc = job.get("location") or {}
        area = loc.get("area") or []
        created = job.get("created")
        return RawJob(
            external_id=str(job["id"]),
            url=job["redirect_url"],
            apply_url=job["redirect_url"],
            title=job["title"].strip(),
            company=(job.get("company") or {}).get("display_name"),
            description=job.get("description") or "",  # Adzuna returns a snippet only
            location_raw=loc.get("display_name"),
            country=country,
            city=area[-1] if len(area) >= 3 else None,
            remote_type=detect_remote_type(job.get("title"), loc.get("display_name")),
            employment_type=job.get("contract_time"),
            salary_min=None if predicted else job.get("salary_min"),
            salary_max=None if predicted else job.get("salary_max"),
            salary_currency=None if predicted else CURRENCY.get(country, "EUR"),
            salary_period=None if predicted else "year",
            posted_at=datetime.fromisoformat(created.replace("Z", "+00:00")) if created else None,
            raw=job,
        )
