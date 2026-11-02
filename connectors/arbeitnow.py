"""Arbeitnow free public job API: https://www.arbeitnow.com/blog/job-board-api

Terms: free public API, "please do not abuse", link back appreciated. We fetch a small
number of pages per run (jobs are refreshed hourly; we run daily).
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from pydantic import Field

from common.enums import RemoteType
from connectors.base import Connector, ConnectorConfig, RawJob, SearchQuery
from connectors.text import detect_remote_type, html_to_text, title_matches


class ArbeitnowConfig(ConnectorConfig):
    max_pages: int = Field(default=3, ge=1, le=10)
    default_country: str = "DE"  # Arbeitnow is a Germany-focused board


class ArbeitnowConnector(Connector):
    name = "arbeitnow"
    config_model = ArbeitnowConfig
    url = "https://www.arbeitnow.com/api/job-board-api"

    async def fetch(self, query: SearchQuery) -> AsyncIterator[RawJob]:
        cfg: ArbeitnowConfig = self.config  # type: ignore[assignment]
        for page in range(1, cfg.max_pages + 1):
            data = await self.client.get_json(self.url, page=page)
            for job in data.get("data", []):  # type: ignore[union-attr]
                # The API has no search parameter: skip irrelevant titles before parsing.
                if query.keywords and not title_matches(job.get("title", ""), query.keywords):
                    continue
                yield self._parse(job, cfg)
            if not (data.get("links") or {}).get("next"):  # type: ignore[union-attr]
                break

    @staticmethod
    def _parse(job: dict[str, Any], cfg: ArbeitnowConfig) -> RawJob:
        created = job.get("created_at")
        remote = RemoteType.REMOTE if job.get("remote") else detect_remote_type(job.get("location"))
        return RawJob(
            external_id=job["slug"],
            url=job["url"],
            apply_url=job["url"],
            title=job["title"].strip(),
            company=job.get("company_name"),
            description_html=job.get("description"),
            description=html_to_text(job.get("description")),
            location_raw=job.get("location"),
            remote_type=remote,
            employment_type=", ".join(job.get("job_types") or []) or None,
            posted_at=datetime.fromtimestamp(int(created), UTC) if created else None,
            tags=list(job.get("tags") or []),
            raw={
                "default_country": cfg.default_country,
                **{k: v for k, v in job.items() if k != "description"},
            },
        )
