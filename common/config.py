"""Application settings, loaded from environment variables (and `.env` in development)."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_json: bool = True

    # Database
    database_url: SecretStr = SecretStr("postgresql+asyncpg://eujobs:eujobs@localhost:5433/eujobs")
    db_pool_size: int = 10
    db_echo: bool = False

    # Redis / Celery
    redis_url: str = "redis://localhost:6380/0"
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None

    # API security
    api_keys: Annotated[list[SecretStr], NoDecode] = Field(default_factory=list)
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3001"]
    )
    rate_limit_default: str = "120/minute"
    rate_limit_storage_url: str | None = None  # defaults to redis_url

    # Uploads
    upload_dir: Path = Path("./var/uploads")
    max_upload_mb: int = 10

    # LLM
    ollama_base_url: str = "http://localhost:11434"
    llm_chat_model: str = "llama3.2:3b"
    llm_embedding_model: str = "nomic-embed-text"
    embedding_dimensions: int = 768

    # Discovery
    job_expiry_days: int = 21
    adzuna_app_id: str | None = None
    adzuna_app_key: SecretStr | None = None

    @field_validator("api_keys", mode="before")
    @classmethod
    def _split_keys(cls, v: object) -> object:
        if isinstance(v, str):
            return [SecretStr(k.strip()) for k in v.split(",") if k.strip()]
        return v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
