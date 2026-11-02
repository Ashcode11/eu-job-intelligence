"""Lever public postings API: https://github.com/lever/postings-api"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import Field

from common.enums import RemoteType
from connectors.base import Connector, ConnectorConfig, RawJob, SearchQuery
from connectors.text import detect_remote_type, html_to_text

_WORKPLACE = {
    "remote": RemoteType.REMOTE,
    "hybrid": RemoteType.HYBRID,
    "on-site": RemoteType.ONSITE,
    "onsite": RemoteType.ONSITE,
}
_PERIOD = {
    "per-year-salary": "year",
    "per-month-salary": "month",
    "per-hour-wage": "hour",
    "per-day-wage": "day",
}


class LeverConfig(ConnectorConfig):
    site: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    company_name: str | None = None
    region: Literal["global", "eu"] = "global"  # EU-hosted Lever accounts use api.eu.lever.co


class LeverConnector(Connector):
    name = "lever"
    config_model = LeverConfig
    complete_listing = True

    async def fetch(self, query: SearchQuery) -> AsyncIterator[RawJob]:
        cfg: LeverConfig = self.config  # type: ignore[assignment]
        host = "api.eu.lever.co" if cfg.region == "eu" else "api.lever.co"
        data = await self.client.get_json(f"https://{host}/v0/postings/{cfg.site}", mode="json")
        if not isinstance(data, list):
            raise ValueError(f"Unexpected Lever response for {cfg.site!r}")
        for job in data:
            yield self._parse(job, cfg)

    @staticmethod
    def _parse(job: dict[str, Any], cfg: LeverConfig) -> RawJob:
        cats = job.get("categories") or {}
        sections = "".join(
            f"<h3>{s.get('text', '')}</h3><ul>{s.get('content', '')}</ul>"
            for s in job.get("lists") or []
        )
        description_html = (job.get("description") or "") + sections + (job.get("additional") or "")
        salary = job.get("salaryRange") or {}
        workplace = _WORKPLACE.get((job.get("workplaceType") or "").lower())
        locations = cats.get("allLocations") or [cats.get("location")]
        created = job.get("createdAt")
        return RawJob(
            external_id=job["id"],
            url=job["hostedUrl"],
            apply_url=job.get("applyUrl"),
            title=job["text"].strip(),
            company=cfg.company_name or cfg.site,
            description_html=description_html,
            description=html_to_text(description_html),
            location_raw="; ".join(filter(None, locations)) or None,
            country=(job.get("country") or None),
            remote_type=workplace or detect_remote_type(cats.get("location")),
            employment_type=cats.get("commitment"),
            salary_min=salary.get("min"),
            salary_max=salary.get("max"),
            salary_currency=salary.get("currency"),
            salary_period=_PERIOD.get(salary.get("interval", "")),
            salary_raw=job.get("salaryDescriptionPlain") or None,
            posted_at=datetime.fromtimestamp(int(created) / 1000, UTC) if created else None,
            tags=[v for v in (cats.get("team"), cats.get("department")) if v],
            raw={
                k: v
                for k, v in job.items()
                if k
                not in (
                    "description",
                    "descriptionPlain",
                    "lists",
                    "additional",
                    "additionalPlain",
                    "descriptionBody",
                    "descriptionBodyPlain",
                    "opening",
                    "openingPlain",
                )
            },
        )
