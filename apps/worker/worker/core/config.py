"""Worker configuration.

A separate Settings class from the API's (apps/api/app/core/config.py)
on purpose: the API and worker are deployed and scaled independently
(Section 54), and the worker doesn't need database_pool_size etc.
Duplicated fields (redis_url) are intentional isolation, not laziness
— see ADR-002 for the reasoning.
"""
from functools import lru_cache

from pydantic import RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )

    redis_url: RedisDsn
    log_level: str = "INFO"


@lru_cache
def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()  # type: ignore[call-arg]
