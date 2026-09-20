"""Target request/response schemas.

`url` validation (SSRF check) happens in app/services/target_service.py
via app.core.url_safety.validate_target_url — NOT here. Pydantic
field validators run in-process with no natural place to inject a
fake resolver for unit testing, and the SSRF check needs to be
reusable identically from both create and update paths in the
service layer. Keeping it there also keeps this schema fast/pure.
"""

from pydantic import BaseModel, Field, field_validator


class TargetCreate(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    name: str | None = Field(default=None, max_length=255)
    enabled: bool = True
    priority: int = Field(default=0, ge=0, le=1000)


class TargetUpdate(BaseModel):
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    name: str | None = Field(default=None, max_length=255)
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=1000)


class TargetResponse(BaseModel):
    id: str
    scraper_id: str
    url: str
    name: str | None
    enabled: bool
    priority: int

    model_config = {"from_attributes": True}

    @field_validator("id", "scraper_id", mode="before")
    @classmethod
    def _coerce_uuid_to_str(cls, value: object) -> str:
        return str(value)
