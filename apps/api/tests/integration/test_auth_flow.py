"""Integration tests — require REAL PostgreSQL AND REAL Redis.

Status in this repository as authored: BLOCKED (environment). The
authoring sandbox has no Docker, no live Postgres/Redis, no network.
These were written to be correct but could not be executed here —
see PHASE_1_REPORT.md. Run for real via:

    docker compose up -d postgres redis
    export DATABASE_URL=postgresql+asyncpg://platform:platform@localhost:5432/platform
    export REDIS_URL=redis://localhost:6379/0
    uv run pytest apps/api/tests/integration -m integration -v

Each test uses a fresh random email/slug (uuid4) rather than fixtures
that truncate tables — simpler, and avoids one test's cleanup
accidentally hiding another test's bug.

IMPORTANT: every AsyncClient below uses base_url="https://test", not
"http://test". This is not cosmetic — the API sets its session/
refresh/CSRF cookies with `secure=True` for every environment except
"development" (Decision C), and httpx's cookie jar correctly refuses
to send a Secure-flagged cookie back on a plain http:// request (RFC
6265). Using "http://test" here made every request after login
silently drop its cookies and come back 401 — found by actually
running these tests in CI (Section 0c/0d, PHASE_1_REPORT.md). The fix
is here, in the test, not in the app: weakening `secure=True` to make
"http://test" work would mean never testing the real cookie security
behavior at all.
"""

import uuid

import pytest
import structlog
from app.main import app
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration

STRONG_PASSWORD = "correct horse battery staple 42!"


def _unique_email() -> str:
    # NOT @example.test / .example / .invalid / .localhost: those are
    # RFC 2606 special-use TLDs, and pydantic's EmailStr (via the
    # email-validator package) rejects them outright as "special-use
    # or reserved" — found by actually running this in CI, where 4
    # tests failed with a 422 before ever reaching the logic under
    # test. A domain under a real TLD (.com) that isn't one of the
    # handful of RFC 2606-reserved *domains* (example.com/.net/.org/
    # .edu) passes the same syntax check without needing a real,
    # deliverable mailbox — pydantic's EmailStr does not perform a
    # DNS/deliverability lookup by default.
    return f"user-{uuid.uuid4().hex[:12]}@wdp-test-mail.com"


def _unique_slug() -> str:
    return f"org-{uuid.uuid4().hex[:12]}"


async def _register_and_login(client: AsyncClient, *, email: str, password: str, name: str) -> None:
    resp = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": password, "name": name}
    )
    assert resp.status_code == 201, resp.text

    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text


def _csrf_header(client: AsyncClient) -> dict[str, str]:
    token = client.cookies.get("csrf_token")
    assert token, "expected csrf_token cookie to be set after login"
    return {"X-CSRF-Token": token}


@pytest.mark.asyncio
async def test_full_auth_and_organization_flow() -> None:
    email = _unique_email()
    slug = _unique_slug()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _register_and_login(client, email=email, password=STRONG_PASSWORD, name="Test User")

        # protected /me
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 200
        assert resp.json()["email"] == email

        # create organization (state-changing -> needs CSRF header)
        resp = await client.post(
            "/api/v1/organizations",
            json={"name": "Acme Inc", "slug": slug},
            headers=_csrf_header(client),
        )
        assert resp.status_code == 201, resp.text
        org_id = resp.json()["id"]
        assert resp.json()["role"] == "OWNER"

        # access it back
        resp = await client.get(f"/api/v1/organizations/{org_id}")
        assert resp.status_code == 200
        assert resp.json()["slug"] == slug

        # refresh rotates the session
        old_access_cookie = client.cookies.get("session_token")
        resp = await client.post("/api/v1/auth/refresh")
        assert resp.status_code == 204
        assert client.cookies.get("session_token") != old_access_cookie

        # session still works after refresh
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 200

        # logout
        resp = await client.post("/api/v1/auth/logout")
        assert resp.status_code == 204

        # revoked session must be rejected
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_cross_tenant_access_is_denied() -> None:
    """MANDATORY: User A (member of Org A only) must not be able to
    read Org B, which belongs to User B."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="https://test") as client_b:
        await _register_and_login(
            client_b, email=_unique_email(), password=STRONG_PASSWORD, name="User B"
        )
        resp = await client_b.post(
            "/api/v1/organizations",
            json={"name": "Org B", "slug": _unique_slug()},
            headers=_csrf_header(client_b),
        )
        assert resp.status_code == 201
        org_b_id = resp.json()["id"]

    async with AsyncClient(transport=transport, base_url="https://test") as client_a:
        await _register_and_login(
            client_a, email=_unique_email(), password=STRONG_PASSWORD, name="User A"
        )
        resp = await client_a.post(
            "/api/v1/organizations",
            json={"name": "Org A", "slug": _unique_slug()},
            headers=_csrf_header(client_a),
        )
        assert resp.status_code == 201

        # User A tries to read Org B
        resp = await client_a.get(f"/api/v1/organizations/{org_b_id}")
        assert resp.status_code in (403, 404)


@pytest.mark.asyncio
async def test_idor_non_member_cannot_access_any_organization() -> None:
    """MANDATORY: a user with ZERO memberships anywhere must be
    denied access to an organization they've never touched, even
    though they are authenticated."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="https://test") as owner_client:
        await _register_and_login(
            owner_client, email=_unique_email(), password=STRONG_PASSWORD, name="Owner"
        )
        resp = await owner_client.post(
            "/api/v1/organizations",
            json={"name": "Someone Else's Org", "slug": _unique_slug()},
            headers=_csrf_header(owner_client),
        )
        assert resp.status_code == 201
        org_id = resp.json()["id"]

    async with AsyncClient(transport=transport, base_url="https://test") as outsider_client:
        await _register_and_login(
            outsider_client, email=_unique_email(), password=STRONG_PASSWORD, name="Outsider"
        )
        resp = await outsider_client.get(f"/api/v1/organizations/{org_id}")
        assert resp.status_code in (403, 404)


@pytest.mark.asyncio
async def test_password_never_appears_in_logs() -> None:
    """MANDATORY: run a real register+login flow with a distinctive
    plaintext password and inspect every structlog entry emitted
    during it — the password string must not appear anywhere."""
    email = _unique_email()
    distinctive_password = f"NeverLogThis-{uuid.uuid4().hex}-Password!"

    transport = ASGITransport(app=app)
    with structlog.testing.capture_logs() as captured_logs:
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            await _register_and_login(
                client, email=email, password=distinctive_password, name="Log Test User"
            )

    for entry in captured_logs:
        serialized = str(entry)
        assert distinctive_password not in serialized, (
            f"plaintext password leaked into a log entry: {entry}"
        )
