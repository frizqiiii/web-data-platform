"""Project request/response schemas."""

from pydantic import BaseModel, Field, field_validator

from app.models.project import ProjectStatus

SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]*[a-z0-9]$"


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255, pattern=SLUG_PATTERN)
    description: str | None = Field(default=None, max_length=10_000)


class ProjectUpdate(BaseModel):
    """`status` is validated against the state machine
    (app.models.project.PROJECT_STATUS_TRANSITIONS) in the service
    layer, not here — this schema only checks it's a recognized
    status value at all, not that the transition is legal from the
    project's current status."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)
    status: ProjectStatus | None = None

    @field_validator("name")
    @classmethod
    def _reject_blank_name(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("name cannot be blank")
        return value


class ProjectResponse(BaseModel):
    id: str
    organization_id: str
    name: str
    slug: str
    description: str | None
    status: str

    model_config = {"from_attributes": True}

    @field_validator("id", "organization_id", mode="before")
    @classmethod
    def _coerce_uuid_to_str(cls, value: object) -> str:
        # SQLAlchemy returns these as uuid.UUID; pydantic does not
        # auto-coerce UUID -> str for a plain `str` field (this exact
        # bug was found and fixed in Phase 1's UserResponse — applying
        # the same fix proactively here instead of waiting to
        # rediscover it).
        return str(value)
