"""Scraper request/response schemas."""

from pydantic import BaseModel, Field, field_validator

from app.models.scraper import ScraperEngine, ScraperStatus
from app.schemas.project import SLUG_PATTERN
from app.schemas.scraper_configuration import ScraperConfiguration


class ScraperCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255, pattern=SLUG_PATTERN)
    engine: ScraperEngine
    # Optional at create time — app/services/scraper_service.py fills
    # in engine defaults (scraper_configuration.default_configuration_for_engine)
    # when omitted, so a scraper always has a valid, complete config.
    configuration: ScraperConfiguration | None = None
    credential_reference: str | None = Field(default=None, max_length=255)


class ScraperUpdate(BaseModel):
    """Same pattern as ProjectUpdate: `status` here is only checked
    against the enum of recognized values — the actual state-machine
    transition legality check happens in app/services/scraper_service.py."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    configuration: ScraperConfiguration | None = None
    credential_reference: str | None = Field(default=None, max_length=255)
    status: ScraperStatus | None = None

    @field_validator("name")
    @classmethod
    def _reject_blank_name(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("name cannot be blank")
        return value


class ScraperResponse(BaseModel):
    id: str
    project_id: str
    name: str
    slug: str
    engine: str
    configuration: dict
    credential_reference: str | None
    status: str
    version: int

    model_config = {"from_attributes": True}

    @field_validator("id", "project_id", mode="before")
    @classmethod
    def _coerce_uuid_to_str(cls, value: object) -> str:
        return str(value)
