"""Organization request/response schemas."""

from pydantic import BaseModel, Field


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)


class OrganizationResponse(BaseModel):
    id: str
    name: str
    slug: str
    status: str
    role: str  # the CALLER's role in this org — never another user's

    model_config = {"from_attributes": True}
