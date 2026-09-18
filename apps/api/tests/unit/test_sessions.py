"""Unit tests for SessionStore: creation, validation, expiration,
refresh rotation, and reuse detection.

Uses an in-memory fake implementing the same small
`AsyncKeyValueStore` protocol that `redis.asyncio.Redis` satisfies —
no real Redis needed. This is deliberate: SessionStore only depends
on that protocol (app/core/sessions.py), specifically so its logic
(the part that's actually worth unit testing — rotation, reuse
detection, expiration) can be verified without infrastructure. The
fact that `redis.asyncio.Redis` really does satisfy this protocol is
what the integration tests (../integration/test_auth_flow.py) prove.
"""

import builtins
import time

import pytest
from app.core.sessions import SessionReuseDetected, SessionStore


class FakeAsyncRedis:
    """Minimal in-memory stand-in for redis.asyncio.Redis, implementing
    exactly the methods SessionStore uses. Supports a controllable
    clock so expiration can be tested without real sleeping."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self._expires_at: dict[str, float] = {}
        self._sets: dict[str, builtins.set[str]] = {}
        self.now: float = time.time()

    def _is_expired(self, key: str) -> bool:
        deadline = self._expires_at.get(key)
        return deadline is not None and self.now >= deadline

    def _purge_if_expired(self, key: str) -> None:
        if self._is_expired(key):
            self._values.pop(key, None)
            self._expires_at.pop(key, None)
            self._sets.pop(key, None)

    async def get(self, key: str) -> str | None:
        self._purge_if_expired(key)
        return self._values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._values[key] = value
        if ex is not None:
            self._expires_at[key] = self.now + ex

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self._values.pop(key, None)
            self._expires_at.pop(key, None)
            self._sets.pop(key, None)

    async def sadd(self, key: str, *values: str) -> None:
        self._sets.setdefault(key, set()).update(values)

    # See app/core/sessions.py's AsyncKeyValueStore.smembers for why
    # this is builtins.set[str], not bare set[str].
    async def smembers(self, key: str) -> builtins.set[str]:
        self._purge_if_expired(key)
        return set(self._sets.get(key, set()))

    async def expire(self, key: str, seconds: int) -> None:
        self._expires_at[key] = self.now + seconds


@pytest.fixture
def fake_redis() -> FakeAsyncRedis:
    return FakeAsyncRedis()


@pytest.fixture
def store(fake_redis: FakeAsyncRedis) -> SessionStore:
    return SessionStore(fake_redis)


@pytest.mark.asyncio
async def test_create_session_returns_usable_pair(store: SessionStore) -> None:
    pair = await store.create_session("user-123")
    assert pair.access_token
    assert pair.refresh_token
    assert pair.csrf_token
    assert len({pair.access_token, pair.refresh_token, pair.csrf_token}) == 3


@pytest.mark.asyncio
async def test_valid_access_token_resolves_to_user_id(store: SessionStore) -> None:
    pair = await store.create_session("user-123")
    resolved = await store.get_user_id_for_access_token(pair.access_token)
    assert resolved == "user-123"


@pytest.mark.asyncio
async def test_unknown_access_token_resolves_to_none(store: SessionStore) -> None:
    assert await store.get_user_id_for_access_token("not-a-real-token") is None


@pytest.mark.asyncio
async def test_access_token_expires(store: SessionStore, fake_redis: FakeAsyncRedis) -> None:
    pair = await store.create_session("user-123")
    assert await store.get_user_id_for_access_token(pair.access_token) == "user-123"

    fake_redis.now += 15 * 60 + 1  # past ACCESS_TTL_SECONDS
    assert await store.get_user_id_for_access_token(pair.access_token) is None


@pytest.mark.asyncio
async def test_refresh_rotation_issues_new_pair(store: SessionStore) -> None:
    original = await store.create_session("user-123")
    rotated = await store.rotate_refresh_token(original.refresh_token)

    assert rotated.access_token != original.access_token
    assert rotated.refresh_token != original.refresh_token
    # new access token must actually work
    assert await store.get_user_id_for_access_token(rotated.access_token) == "user-123"


@pytest.mark.asyncio
async def test_rotating_an_invalid_refresh_token_raises(store: SessionStore) -> None:
    with pytest.raises(ValueError):
        await store.rotate_refresh_token("not-a-real-refresh-token")


@pytest.mark.asyncio
async def test_refresh_token_reuse_is_detected_and_revokes_family(store: SessionStore) -> None:
    original = await store.create_session("user-123")
    rotated = await store.rotate_refresh_token(original.refresh_token)

    # Attacker (or a buggy client) replays the ALREADY-USED original
    # refresh token a second time.
    with pytest.raises(SessionReuseDetected):
        await store.rotate_refresh_token(original.refresh_token)

    # The entire family — including the token issued by the
    # legitimate rotation above — must now be dead.
    assert await store.get_user_id_for_access_token(rotated.access_token) is None
    with pytest.raises(ValueError):
        await store.rotate_refresh_token(rotated.refresh_token)


@pytest.mark.asyncio
async def test_logout_revokes_the_session(store: SessionStore) -> None:
    pair = await store.create_session("user-123")
    await store.revoke_session_by_refresh_token(pair.refresh_token)

    assert await store.get_user_id_for_access_token(pair.access_token) is None
    with pytest.raises(ValueError):
        await store.rotate_refresh_token(pair.refresh_token)


@pytest.mark.asyncio
async def test_csrf_token_is_retrievable_for_a_valid_session(store: SessionStore) -> None:
    pair = await store.create_session("user-123")
    csrf = await store.get_csrf_token_for_access_token(pair.access_token)
    assert csrf == pair.csrf_token
