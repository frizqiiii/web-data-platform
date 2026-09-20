"""Engine-specific scraper configuration schemas (ADR-005).

`configuration` is stored as JSONB precisely so new engines can be
added without a migration — but that only works if every write is
validated against a strict, engine-specific schema first. This module
is that validation boundary. `extra="forbid"` on every config here is
deliberate and different from Phase 1's Settings classes: this is
untrusted external input (an API caller's JSON body), not an internal
shared .env — unknown fields here should be rejected, not ignored.

Adding a 4th engine later means adding one more class + one more
branch in `parse_configuration` — it does NOT touch Scraper, the
migration, or any existing engine's schema (this is what Section 6's
"Domain -> Scraper Definition -> Execution Command -> Engine Adapter"
separation is for).
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.models.scraper import ScraperEngine


class HttpEngineConfig(BaseModel):
    model_config = {"extra": "forbid"}

    engine: Literal[ScraperEngine.HTTP] = ScraperEngine.HTTP
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_redirects: int = Field(default=5, ge=0, le=10)
    concurrency: int = Field(default=1, ge=1, le=50)
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=10_000)
    user_agent: str | None = Field(default=None, max_length=255)
    headers: dict[str, str] = Field(default_factory=dict)


class BrowserEngineConfig(BaseModel):
    model_config = {"extra": "forbid"}

    engine: Literal[ScraperEngine.BROWSER] = ScraperEngine.BROWSER
    timeout_seconds: int = Field(default=60, ge=1, le=300)
    concurrency: int = Field(default=1, ge=1, le=10)
    user_agent: str | None = Field(default=None, max_length=255)
    viewport_width: int = Field(default=1280, ge=320, le=3840)
    viewport_height: int = Field(default=720, ge=240, le=2160)
    wait_until: Literal["load", "domcontentloaded", "networkidle"] = "load"


class ScrapyEngineConfig(BaseModel):
    model_config = {"extra": "forbid"}

    engine: Literal[ScraperEngine.SCRAPY] = ScraperEngine.SCRAPY
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    concurrency: int = Field(default=1, ge=1, le=50)
    obey_robots_txt: bool = True


ScraperConfiguration = Annotated[
    HttpEngineConfig | BrowserEngineConfig | ScrapyEngineConfig,
    Field(discriminator="engine"),
]


def default_configuration_for_engine(engine: str) -> dict:
    """Used when a scraper is created without an explicit
    `configuration` body — returns the engine's defaults as a plain
    dict, ready to store in the JSONB column."""
    defaults: dict[str, type[BaseModel]] = {
        ScraperEngine.HTTP.value: HttpEngineConfig,
        ScraperEngine.BROWSER.value: BrowserEngineConfig,
        ScraperEngine.SCRAPY.value: ScrapyEngineConfig,
    }
    schema_cls = defaults[engine]
    return schema_cls().model_dump(mode="json")
