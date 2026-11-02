"""Job source and discovery request/response models."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from common.enums import SourceType

SourceKey = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_.:-]{0,49}$")]


class SourceCreate(BaseModel):
    key: SourceKey = Field(description="Unique id, e.g. 'greenhouse:acme'")
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    connector: Annotated[str, StringConstraints(max_length=50)]
    config: dict[str, Any] = Field(default_factory=dict)
    terms_url: Annotated[str, StringConstraints(pattern=r"^https://", max_length=500)] | None = None
    enabled: bool = True
    rate_limit_per_minute: int = Field(default=30, ge=1, le=120)


class SourceUpdate(BaseModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)] | None = None
    config: dict[str, Any] | None = None
    enabled: bool | None = None
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=120)


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    name: str
    source_type: SourceType
    connector: str
    config: dict[str, Any]
    terms_url: str | None
    enabled: bool
    respects_robots_txt: bool
    rate_limit_per_minute: int
    last_run_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None
    active_jobs: int = 0


class DiscoveryRunRequest(BaseModel):
    search_config_id: uuid.UUID | None = Field(
        default=None, description="Run one search; omit to run every enabled search."
    )


class DiscoveryRunResponse(BaseModel):
    queued: list[dict[str, str]]


class ConnectorInfo(BaseModel):
    name: str
    complete_listing: bool
    config_schema: dict[str, Any]
