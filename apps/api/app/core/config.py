"""Application configuration.

Loaded from environment variables via pydantic-settings. Invalid
configuration must fail fast at startup (Master Prompt Section 58) —
this module deliberately has NO silent defaults for anything
connectivity- or security-relevant (database, redis). Missing them
raises at import/instantiation time, not at first use.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # "ignore" rather than "forbid": local dev uses ONE shared .env
        # for api/worker/scheduler (e.g. MINIO_* vars), so this process's
        # Settings will legitimately see keys it doesn't declare fields
        # for. Required fields (database_url, redis_url) still fail
        # fast if missing — this only relaxes rejecting *unknown* keys,
        # found necessary by actually running the app (see
        # PHASE_0_REPORT.md), not a blanket loosening of validation.
        extra="ignore",
    )

    environment: Literal["development", "test", "staging", "production"] = "development"
    service_name: str = "web-data-platform-api"

    database_url: PostgresDsn = Field(...)
    database_pool_size: int = 5
    database_max_overflow: int = 10

    redis_url: RedisDsn = Field(...)

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
