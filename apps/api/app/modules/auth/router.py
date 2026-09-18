"""Authentication endpoints (Decision I).

RULE enforced throughout this file: request/response schemas never
echo the plaintext password back, structlog calls never include it,
and audit records never include it — see apps/api/tests/unit/
test_no_password_leakage.py for the test that checks this against
captured log output.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.api.deps import (
    ACCESS_COOKIE_NAME,
    REFRESH_COOKIE_NAME,
    get_current_user,
    get_session_store,
)
from app.core.config import get_settings
from app.core.csrf import CSRF_COOKIE_NAME
from app.core.database import get_db
from app.core.sessions import REFRESH_TTL_SECONDS, SessionPair, SessionReuseDetected, SessionStore
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, UserResponse
from app.services.audit_service import record_audit_event
from app.services.auth_service import EmailAlreadyRegistered, InvalidCredentials
from app.services.auth_service import authenticate_user as do_authenticate
from app.services.auth_service import register_user as do_register

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger()


def _set_session_cookies(response: Response, pair: SessionPair) -> None:
    settings = get_settings()
    secure = settings.environment != "development"
    response.set_cookie(
        ACCESS_COOKIE_NAME,
        pair.access_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        pair.refresh_token,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/api/v1/auth/refresh",
        max_age=REFRESH_TTL_SECONDS,
    )
    # CSRF cookie is deliberately NOT httpOnly — the dashboard's JS
    # must be able to read it to echo it back as a header (Decision C).
    response.set_cookie(
        CSRF_COOKIE_NAME,
        pair.csrf_token,
        httponly=False,
        secure=secure,
        samesite="strict",
        path="/",
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE_NAME, path="/")
    response.delete_cookie(REFRESH_COOKIE_NAME, path="/api/v1/auth/refresh")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    try:
        user = await do_register(
            db, email=payload.email, password=payload.password, name=payload.name
        )
    except EmailAlreadyRegistered as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered") from exc

    await record_audit_event(
        db,
        action="USER_CREATED",
        user_id=user.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    logger.info("user_registered", user_id=str(user.id))
    return user


@router.post("/login", response_model=UserResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    session_store: SessionStore = Depends(get_session_store),
) -> User:
    try:
        user = await do_authenticate(db, email=payload.email, password=payload.password)
    except InvalidCredentials as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password") from exc

    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    pair = await session_store.create_session(str(user.id), ip_address=ip, user_agent=user_agent)
    _set_session_cookies(response, pair)

    await record_audit_event(
        db, action="LOGIN", user_id=user.id, ip_address=ip, user_agent=user_agent
    )
    await db.commit()
    logger.info("user_logged_in", user_id=str(user.id))
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    session_store: SessionStore = Depends(get_session_store),
) -> None:
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if refresh_token:
        await session_store.revoke_session_by_refresh_token(refresh_token)
    _clear_session_cookies(response)

    await record_audit_event(db, action="LOGOUT", user_id=current_user.id)
    await db.commit()
    logger.info("user_logged_out", user_id=str(current_user.id))


@router.post("/refresh", status_code=status.HTTP_204_NO_CONTENT)
async def refresh(
    request: Request,
    response: Response,
    session_store: SessionStore = Depends(get_session_store),
) -> None:
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not refresh_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No refresh token")

    try:
        pair = await session_store.rotate_refresh_token(refresh_token)
    except SessionReuseDetected:
        _clear_session_cookies(response)
        logger.warning("refresh_token_reuse_detected")
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Session revoked: refresh token reuse detected"
        ) from None
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token") from exc

    _set_session_cookies(response, pair)


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
