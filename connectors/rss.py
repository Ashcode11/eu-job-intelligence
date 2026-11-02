"""Generic RSS/Atom job feed connector (for boards that publish feeds)."""

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from time import struct_time

import feedparser
from pydantic import Field, HttpUrl

from connectors.base import Connector, ConnectorConfig, RawJob, SearchQuery
from connectors.text import detect_remote_type, html_to_text


class RssConfig(ConnectorConfig):
    feed_url: HttpUrl
    company_name: str | None = None  # when the feed belongs to one employer
    default_country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")


class RssConnector(Connector):
    name = "rss"
    config_model = RssConfig

    async def fetch(self, query: SearchQuery) -> AsyncIterator[RawJob]:
        cfg: RssConfig = self.config  # type: ignore[assignment]
        resp = await self.client.get(str(cfg.feed_url))
        feed = feedparser.parse(resp.content)
        if feed.bozo and not feed.entries:
            raise ValueError(f"Unparseable feed: {feed.bozo_exception}")
        for entry in feed.entries:
            link = entry.get("link")
            if not link or not entry.get("title"):
                continue
            summary = entry.get("summary") or ""
            location = entry.get("location") or entry.get("job_location")
            yield RawJob(
                external_id=entry.get("id") or hashlib.sha256(link.encode()).hexdigest()[:32],
                url=link,
                apply_url=link,
                title=entry["title"].strip(),
                company=entry.get("author") or cfg.company_name,
                description_html=summary,
                description=html_to_text(summary),
                location_raw=location,
                remote_type=detect_remote_type(entry["title"], location),
                posted_at=_dt(entry.get("published_parsed") or entry.get("updated_parsed")),
                tags=[t.get("term") for t in entry.get("tags", []) if t.get("term")],
                raw={"default_country": cfg.default_country, "id": entry.get("id"), "link": link},
            )


def _dt(value: struct_time | None) -> datetime | None:
    return datetime(*value[:6], tzinfo=UTC) if value else None
