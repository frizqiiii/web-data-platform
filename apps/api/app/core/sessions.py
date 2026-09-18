"""Opaque Redis-backed session store (Decision A / ADR-003).

Design:
- Access and refresh tokens are random opaque strings (app.core.
  security.generate_token) — never JWTs, never decodable without a
  Redis lookup.
- Redis keys are SHA-256 hashes of the tokens, not the tokens
  themselves (Decision H) — a Redis dump alone does not hand out
  usable tokens.
- Every access+refresh pair issued together shares a `family_id`.
  All token hashes issued under a family are tracked in a Redis SET
  (`session:family:{family_id}`) so the whole family can be revoked
  together (logout, or reuse-detected compromise response).
- Refresh rotation: using a refresh token issues a brand new
  access+refresh pair in the SAME family and marks the used token
  `used=True` (kept until natural expiry, not deleted) rather than
  deleting it immediately — this is what makes reuse detectable.
- Refresh reuse detection: presenting an already-`used` refresh
  token revokes the ENTIRE family immediately (all devices/sessions
  descended from that original login) — the standard mitigation for
  a stolen-and-replayed refresh token.

This module depends only on the small `AsyncKeyValueStore` protocol
below, not on `redis.asyncio.Redis` directly, so it can be unit
tested with a lightweight in-memory fake (see
apps/api/tests/unit/test_sessions.py) without a real Redis instance.
"""

import builtins
import json
import uuid
from dataclasses import dataclass
from typing import Protocol

from app.core.security import generate_token, hash_token

ACCESS_TTL_SECONDS = 15 * 60  # 15 minutes
REFRESH_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days
FAMILY_SET_PREFIX = "session:family:"
TOKEN_KEY_PREFIX = "session:token:"


class AsyncKeyValueStore(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ex: int | None = None) -> object: ...
    async def delete(self, *keys: str) -> object: ...
    async def sadd(self, key: str, *values: str) -> object: ...
    # `builtins.set` (not the bare `set` type) — this Protocol also
    # declares a method named `set` (the Redis SET command), which
    # shadows the builtin `set` type within this class body and
    # otherwise makes mypy reject `set[str]` as "not valid as a type"
    # (found by actually running mypy — a real, if obscure, gotcha of
    # naming a Protocol method the same as a builtin used elsewhere in
    # the same class).
    async def smembers(self, key: str) -> builtins.set[str]: ...
    async def expire(self, key: str, seconds: int) -> object: ...


class SessionReuseDetected(Exception):
    """Raised when a refresh token that was already used is presented
    again — indicates the token was stolen and replayed. The entire
    session family has already been revoked by the time this is
    raised; the caller (auth router) should return 401 and may want
    to alert the user out-of-band in a later phase."""


@dataclass(frozen=True)
class SessionPair:
    access_token: str
    refresh_token: str
    csrf_token: str


@dataclass(frozen=True)
class _TokenRecord:
    user_id: str
    family_id: str
    token_type: str  # "access" | "refresh"
    used: bool
    ip_address: str | None
    user_agent: str | None
    csrf_token: str


class SessionStore:
    def __init__(self, store: AsyncKeyValueStore) -> None:
        self._store = store

    async def create_session(
        self, user_id: str, ip_address: str | None = None, user_agent: str | None = None
    ) -> SessionPair:
        family_id = str(uuid.uuid4())
        return await self._issue_pair(user_id, family_id, ip_address, user_agent)

    async def _issue_pair(
        self,
        user_id: str,
        family_id: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> SessionPair:
        access_token = generate_token()
        refresh_token = generate_token()
        csrf_token = generate_token()
        access_hash = hash_token(access_token)
        refresh_hash = hash_token(refresh_token)

        access_record = _TokenRecord(
            user_id=user_id,
            family_id=family_id,
            token_type="access",
            used=False,
            ip_address=ip_address,
            user_agent=user_agent,
            csrf_token=csrf_token,
        )
        refresh_record = _TokenRecord(
            user_id=user_id,
            family_id=family_id,
            token_type="refresh",
            used=False,
            ip_address=ip_address,
            user_agent=user_agent,
            csrf_token=csrf_token,
        )

        await self._store.set(
            TOKEN_KEY_PREFIX + access_hash,
            json.dumps(access_record.__dict__),
            ex=ACCESS_TTL_SECONDS,
        )
        await self._store.set(
            TOKEN_KEY_PREFIX + refresh_hash,
            json.dumps(refresh_record.__dict__),
            ex=REFRESH_TTL_SECONDS,
        )
        family_key = FAMILY_SET_PREFIX + family_id
        await self._store.sadd(family_key, access_hash, refresh_hash)
        await self._store.expire(family_key, REFRESH_TTL_SECONDS)

        return SessionPair(
            access_token=access_token, refresh_token=refresh_token, csrf_token=csrf_token
        )

    async def get_user_id_for_access_token(self, access_token: str) -> str | None:
        raw = await self._store.get(TOKEN_KEY_PREFIX + hash_token(access_token))
        if raw is None:
            return None
        record = json.loads(raw)
        if record.get("token_type") != "access":
            return None
        # json.loads returns Any — this cast just asserts what we
        # ourselves put in the record; not a new assumption.
        return str(record["user_id"])

    async def get_csrf_token_for_access_token(self, access_token: str) -> str | None:
        """Used by the CSRF dependency to fetch the server-side value
        to compare the request's cookie+header pair against."""
        raw = await self._store.get(TOKEN_KEY_PREFIX + hash_token(access_token))
        if raw is None:
            return None
        record = json.loads(raw)
        csrf_token = record.get("csrf_token")
        return str(csrf_token) if csrf_token is not None else None

    async def rotate_refresh_token(self, refresh_token: str) -> SessionPair:
        refresh_hash = hash_token(refresh_token)
        raw = await self._store.get(TOKEN_KEY_PREFIX + refresh_hash)
        if raw is None:
            raise ValueError("invalid or expired refresh token")

        record = json.loads(raw)
        if record.get("token_type") != "refresh":
            raise ValueError("not a refresh token")

        if record.get("used"):
            # Reuse of an already-rotated refresh token: treat the
            # whole family as compromised and revoke it immediately.
            await self.revoke_family(record["family_id"])
            raise SessionReuseDetected(
                f"refresh token reuse detected for family {record['family_id']}"
            )

        # Mark this refresh token as used but keep it (with its
        # existing TTL) so a future reuse attempt is still detectable.
        record["used"] = True
        await self._store.set(
            TOKEN_KEY_PREFIX + refresh_hash, json.dumps(record), ex=REFRESH_TTL_SECONDS
        )

        return await self._issue_pair(
            user_id=record["user_id"],
            family_id=record["family_id"],
            ip_address=record.get("ip_address"),
            user_agent=record.get("user_agent"),
        )

    async def revoke_family(self, family_id: str) -> None:
        family_key = FAMILY_SET_PREFIX + family_id
        members = await self._store.smembers(family_key)
        if members:
            await self._store.delete(*(TOKEN_KEY_PREFIX + h for h in members))
        await self._store.delete(family_key)

    async def revoke_session_by_refresh_token(self, refresh_token: str) -> None:
        """Logout: revoke the entire family this refresh token belongs
        to (both the access and refresh token issued together)."""
        raw = await self._store.get(TOKEN_KEY_PREFIX + hash_token(refresh_token))
        if raw is None:
            return
        record = json.loads(raw)
        await self.revoke_family(record["family_id"])
