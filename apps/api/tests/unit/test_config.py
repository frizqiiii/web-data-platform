"""Unit tests for Settings loading/validation.

These do NOT require a live database or Redis connection — they only
verify that required env vars are enforced and documented defaults
behave as claimed. This is what CAN be executed and verified inside
the sandbox this repository was authored in, unlike the integration
tests in ../integration/.
"""
import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_requires_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_settings_requires_redis_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/db"
    )
    monkeypatch.delenv("REDIS_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_settings_loads_with_required_vars_and_sane_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/db"
    )
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.environment == "development"
    assert settings.database_pool_size == 5


def test_settings_rejects_unknown_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/db"
    )
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SOME_TYPO_VAR", "oops")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]
