"""Auth request/response schemas.

RULE: no schema here ever includes a plaintext password field in a
RESPONSE (only in requests, where it's consumed once and discarded —
see app/modules/auth/router.py, which never echoes it back)."""

from pydantic import BaseModel, EmailStr, Field


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
