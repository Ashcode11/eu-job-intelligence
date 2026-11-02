"""Greenhouse public job board API: https://developers.greenhouse.io/job-board.html"""

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from pydantic import Field

from connectors.base import Connector, ConnectorConfig, RawJob, SearchQuery
from connectors.text import detect_remote_type, html_to_text


class GreenhouseConfig(ConnectorConfig):
    board_token: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    company_name: str | None = None


class GreenhouseConnector(Connector):
    name = "greenhouse"
    config_model = GreenhouseConfig
    complete_listing = True
    base_url = "https://boards-api.greenhouse.io/v1/boards"

    async def fetch(self, query: SearchQuery) -> AsyncIterator[RawJob]:
        cfg: GreenhouseConfig = self.config  # type: ignore[assignment]
        data = await self.client.get_json(f"{self.base_url}/{cfg.board_token}/jobs", content="true")
        for job in data.get("jobs", []):  # type: ignore[union-attr]
            yield self._parse(job, cfg)

    @staticmethod
    def _parse(job: dict[str, Any], cfg: GreenhouseConfig) -> RawJob:
        location = (job.get("location") or {}).get("name")
        office_locations = [o.get("location") or o.get("name") for o in job.get("offices") or []]
        description_html = job.get("content") or ""
        metadata = {
            m.get("name"): m.get("value") for m in job.get("metadata") or [] if isinstance(m, dict)
        }
        remote = detect_remote_type(location, *[o for o in office_locations if o])
        return RawJob(
            external_id=str(job["id"]),
            url=job["absolute_url"],
            apply_url=job["absolute_url"],
            title=job["title"].strip(),
            company=job.get("company_name") or cfg.company_name,
            description_html=description_html,
            description=html_to_text(description_html, escaped=True),
            location_raw="; ".join(filter(None, [location, *office_locations])) or None,
            remote_type=remote,
            employment_type=_str(metadata.get("Time Type") or metadata.get("Employment Type")),
            posted_at=_dt(job.get("first_published") or job.get("updated_at")),
            expires_at=_dt(job.get("application_deadline")),
            tags=[d["name"] for d in job.get("departments") or [] if d.get("name")],
            raw={k: v for k, v in job.items() if k != "content"},
        )


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _str(value: Any) -> str | None:
    return str(value) if isinstance(value, str | int | float) else None
