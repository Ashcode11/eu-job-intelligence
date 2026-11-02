"""Connector contract: every job source yields `RawJob`s and never touches the database."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from common.enums import RemoteType
from connectors.http import PoliteClient


class RawJob(BaseModel):
    """A job exactly as one source describes it, lightly structured."""

    external_id: str
    url: str
    apply_url: str | None = None
    title: str
    company: str | None = None
    description_html: str | None = None
    description: str = ""
    location_raw: str | None = None
    country: str | None = None  # ISO 3166-1 alpha-2 if the source states it
    city: str | None = None
    remote_type: RemoteType = RemoteType.UNKNOWN
    employment_type: str | None = None
    # Only salary the posting itself advertises. Source-side *predictions* must not go here.
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    salary_raw: str | None = None
    posted_at: datetime | None = None
    expires_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class SearchQuery(BaseModel):
    keywords: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    max_results: int = 100


class ConnectorConfig(BaseModel):
    """Per-source, non-secret settings stored in `job_sources.config`."""

    model_config = ConfigDict(extra="forbid")


class Connector(ABC):
    name: ClassVar[str]
    config_model: ClassVar[type[ConnectorConfig]] = ConnectorConfig
    # True when one fetch returns *every* open posting of the source (an ATS board).
    # Jobs missing from a complete listing can then be marked closed.
    complete_listing: ClassVar[bool] = False

    def __init__(self, config: dict[str, Any], client: PoliteClient) -> None:
        self.config = self.config_model.model_validate(config or {})
        self.client = client

    @abstractmethod
    def fetch(self, query: SearchQuery) -> AsyncIterator[RawJob]:
        """Yield raw jobs. Raise on failure; partial results are discarded for closure checks."""
