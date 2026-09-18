"""Auth request/response schemas.

RULE: no schema here ever includes a plaintext password field in a
RESPONSE (only in requests, where it's consumed once and discarded —
see app/modules/auth/router.py, which never echoes it back)."""

from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)
    name: str = Field(min_length=1, max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    status: str

    model_config = {"from_attributes": True}

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_uuid_to_str(cls, value: object) -> str:
        # app/modules/auth/router.py returns the SQLAlchemy `User`
        # object directly (id: uuid.UUID) and relies on
        # from_attributes to build this response — pydantic does NOT
        # auto-coerce UUID -> str for a plain `str` field (found by
        # actually running the integration tests: register/login/me
        # all failed FastAPI's response validation with "Input should
        # be a valid string"). Coercing here fixes all three call
        # sites at once rather than repeating `str(user.id)` in each.
        return str(value)
