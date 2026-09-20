"""Unit tests for engine-specific scraper configuration validation
(ADR-005) — pure Pydantic validation, no database needed."""

import pytest
from app.models.scraper import ScraperEngine
from app.schemas.scraper_configuration import (
    BrowserEngineConfig,
    HttpEngineConfig,
    ScraperConfiguration,
    default_configuration_for_engine,
)
from pydantic import TypeAdapter, ValidationError

_adapter: TypeAdapter = TypeAdapter(ScraperConfiguration)


def test_http_config_applies_sane_defaults() -> None:
    config = HttpEngineConfig()
    assert config.timeout_seconds == 30
    assert config.concurrency == 1
    assert config.headers == {}


def test_http_config_rejects_unknown_fields() -> None:
    """extra="forbid" — untrusted external input must not silently
    accept fields we don't recognize."""
    with pytest.raises(ValidationError):
        HttpEngineConfig(this_field_does_not_exist="oops")  # type: ignore[call-arg]


def test_http_config_rejects_timeout_out_of_range() -> None:
    with pytest.raises(ValidationError):
        HttpEngineConfig(timeout_seconds=0)
    with pytest.raises(ValidationError):
        HttpEngineConfig(timeout_seconds=10_000)


def test_http_config_rejects_excessive_concurrency() -> None:
    with pytest.raises(ValidationError):
        HttpEngineConfig(concurrency=1000)


def test_browser_config_rejects_invalid_wait_until() -> None:
    with pytest.raises(ValidationError):
        BrowserEngineConfig(wait_until="not-a-real-option")  # type: ignore[arg-type]


def test_discriminated_union_picks_correct_schema_by_engine_field() -> None:
    parsed = _adapter.validate_python({"engine": "HTTP", "timeout_seconds": 45})
    assert isinstance(parsed, HttpEngineConfig)
    assert parsed.timeout_seconds == 45

    parsed_browser = _adapter.validate_python({"engine": "BROWSER", "viewport_width": 1920})
    assert isinstance(parsed_browser, BrowserEngineConfig)
    assert parsed_browser.viewport_width == 1920


def test_discriminated_union_rejects_unknown_engine() -> None:
    with pytest.raises(ValidationError):
        _adapter.validate_python({"engine": "NOT_A_REAL_ENGINE"})


def test_default_configuration_for_engine_matches_schema_defaults() -> None:
    defaults = default_configuration_for_engine(ScraperEngine.HTTP.value)
    assert defaults["timeout_seconds"] == 30
    assert defaults["engine"] == "HTTP"
