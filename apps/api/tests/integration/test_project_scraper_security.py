"""Integration tests for Project/Scraper/Target: CRUD, lifecycle,
tenant isolation, RBAC, and SSRF — requires real PostgreSQL + Redis.

Status as authored: BLOCKED (environment) — same sandbox limitation
as every other integration test in this repo (PHASE_0_REPORT.md /
PHASE_1_REPORT.md). Run via CI or:

    docker compose up -d postgres redis
    uv run pytest apps/api/tests/integration -m integration -v

One gap worth noting: there is no API endpoint (in Phase 1 or Phase 2)
to invite a member into an organization with a specific role — only
the creator (always OWNER) exists via the API. The "unauthorized
role" test below creates a second, lower-role membership by writing
directly to the database via the app's own session factory, not
through the API, because no API path for it exists yet.
"""

import uuid

import pytest
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.main import app
from app.models.organization_member import OrganizationMember, OrgRole
from app.models.user import User, UserStatus
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

pytestmark = pytest.mark.integration

STRONG_PASSWORD = "correct horse battery staple 42!"


def _unique_email() -> str:
    return f"user-{uuid.uuid4().hex[:12]}@wdp-test-mail.com"


def _unique_slug(prefix: str = "proj") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


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


async def _create_org(client: AsyncClient) -> str:
    resp = await client.post(
        "/api/v1/organizations",
        json={"name": "Test Org", "slug": _unique_slug("org")},
        headers=_csrf_header(client),
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def _create_project(client: AsyncClient, *, organization_id: str) -> str:
    resp = await client.post(
        f"/api/v1/projects?organization_id={organization_id}",
        json={"name": "Test Project", "slug": _unique_slug("proj")},
        headers=_csrf_header(client),
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def _create_scraper(client: AsyncClient, *, project_id: str) -> str:
    resp = await client.post(
        f"/api/v1/projects/{project_id}/scrapers",
        json={"name": "Test Scraper", "slug": _unique_slug("scraper"), "engine": "HTTP"},
        headers=_csrf_header(client),
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


@pytest.mark.asyncio
async def test_full_project_scraper_target_flow() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _register_and_login(
            client, email=_unique_email(), password=STRONG_PASSWORD, name="Owner"
        )
        org_id = await _create_org(client)
        project_id = await _create_project(client, organization_id=org_id)

        # project lifecycle: DRAFT -> ACTIVE -> PAUSED -> ACTIVE -> ARCHIVED
        resp = await client.get(f"/api/v1/projects/{project_id}")
        assert resp.json()["status"] == "DRAFT"

        resp = await client.patch(
            f"/api/v1/projects/{project_id}",
            json={"status": "ACTIVE"},
            headers=_csrf_header(client),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "ACTIVE"

        # invalid transition: DRAFT-only rule shouldn't allow ACTIVE->DRAFT
        resp = await client.patch(
            f"/api/v1/projects/{project_id}", json={"status": "DRAFT"}, headers=_csrf_header(client)
        )
        assert resp.status_code == 409, resp.text

        scraper_id = await _create_scraper(client, project_id=project_id)
        resp = await client.get(f"/api/v1/scrapers/{scraper_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "DRAFT"
        assert resp.json()["engine"] == "HTTP"
        assert resp.json()["configuration"]["timeout_seconds"] == 30  # HttpEngineConfig default

        # enable scraper
        resp = await client.patch(
            f"/api/v1/scrapers/{scraper_id}",
            json={"status": "ACTIVE"},
            headers=_csrf_header(client),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ACTIVE"

        # target CRUD, safe URL
        resp = await client.post(
            f"/api/v1/scrapers/{scraper_id}/targets",
            json={"url": "https://example.com/page"},
            headers=_csrf_header(client),
        )
        assert resp.status_code == 201, resp.text
        target_id = resp.json()["id"]

        resp = await client.get(f"/api/v1/scrapers/{scraper_id}/targets")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        resp = await client.delete(f"/api/v1/targets/{target_id}", headers=_csrf_header(client))
        assert resp.status_code == 204

        # archive project (soft delete)
        resp = await client.delete(f"/api/v1/projects/{project_id}", headers=_csrf_header(client))
        assert resp.status_code == 200
        assert resp.json()["status"] == "ARCHIVED"

        # archived is terminal
        resp = await client.patch(
            f"/api/v1/projects/{project_id}",
            json={"status": "ACTIVE"},
            headers=_csrf_header(client),
        )
        assert resp.status_code == 409


@pytest.mark.asyncio
async def test_ssrf_target_creation_rejected() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _register_and_login(
            client, email=_unique_email(), password=STRONG_PASSWORD, name="Owner"
        )
        org_id = await _create_org(client)
        project_id = await _create_project(client, organization_id=org_id)
        scraper_id = await _create_scraper(client, project_id=project_id)

        resp = await client.post(
            f"/api/v1/scrapers/{scraper_id}/targets",
            json={"url": "http://169.254.169.254/latest/meta-data/"},
            headers=_csrf_header(client),
        )
        assert resp.status_code == 422, resp.text

        resp = await client.post(
            f"/api/v1/scrapers/{scraper_id}/targets",
            json={"url": "http://127.0.0.1:8000/admin"},
            headers=_csrf_header(client),
        )
        assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_cross_tenant_project_and_scraper_access_denied() -> None:
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="https://test") as client_b:
        await _register_and_login(
            client_b, email=_unique_email(), password=STRONG_PASSWORD, name="User B"
        )
        org_b = await _create_org(client_b)
        project_b = await _create_project(client_b, organization_id=org_b)
        scraper_b = await _create_scraper(client_b, project_id=project_b)

    async with AsyncClient(transport=transport, base_url="https://test") as client_a:
        await _register_and_login(
            client_a, email=_unique_email(), password=STRONG_PASSWORD, name="User A"
        )
        org_a = await _create_org(client_a)
        await _create_project(client_a, organization_id=org_a)

        resp = await client_a.get(f"/api/v1/projects/{project_b}")
        assert resp.status_code in (403, 404)

        resp = await client_a.get(f"/api/v1/scrapers/{scraper_b}")
        assert resp.status_code in (403, 404)


@pytest.mark.asyncio
async def test_idor_non_member_denied_for_project_and_scraper() -> None:
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="https://test") as owner_client:
        await _register_and_login(
            owner_client, email=_unique_email(), password=STRONG_PASSWORD, name="Owner"
        )
        org_id = await _create_org(owner_client)
        project_id = await _create_project(owner_client, organization_id=org_id)
        scraper_id = await _create_scraper(owner_client, project_id=project_id)

    async with AsyncClient(transport=transport, base_url="https://test") as outsider_client:
        await _register_and_login(
            outsider_client, email=_unique_email(), password=STRONG_PASSWORD, name="Outsider"
        )
        resp = await outsider_client.get(f"/api/v1/projects/{project_id}")
        assert resp.status_code in (403, 404)
        resp = await outsider_client.get(f"/api/v1/scrapers/{scraper_id}")
        assert resp.status_code in (403, 404)


@pytest.mark.asyncio
async def test_viewer_role_cannot_create_project() -> None:
    """No API endpoint exists (Phase 1 or 2) to invite a member with a
    specific role, so the VIEWER membership is created directly via
    the app's own session factory — this is test setup, not something
    the API allows a client to do."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as owner_client:
        await _register_and_login(
            owner_client, email=_unique_email(), password=STRONG_PASSWORD, name="Owner"
        )
        org_id = await _create_org(owner_client)

    viewer_email = _unique_email()
    async with AsyncSessionLocal() as session:
        viewer_user = User(
            id=uuid.uuid4(),
            email=viewer_email,
            password_hash=hash_password(STRONG_PASSWORD),
            name="Viewer",
            status=UserStatus.ACTIVE.value,
            is_active=True,
        )
        session.add(viewer_user)
        await session.flush()
        session.add(
            OrganizationMember(
                id=uuid.uuid4(),
                user_id=viewer_user.id,
                organization_id=uuid.UUID(org_id),
                role=OrgRole.VIEWER.value,
            )
        )
        await session.commit()

    async with AsyncClient(transport=transport, base_url="https://test") as viewer_client:
        resp = await viewer_client.post(
            "/api/v1/auth/login", json={"email": viewer_email, "password": STRONG_PASSWORD}
        )
        assert resp.status_code == 200, resp.text

        # VIEWER can read...
        resp = await viewer_client.get(f"/api/v1/projects?organization_id={org_id}")
        assert resp.status_code == 200

        # ...but not create.
        resp = await viewer_client.post(
            f"/api/v1/projects?organization_id={org_id}",
            json={"name": "Should Fail", "slug": _unique_slug()},
            headers=_csrf_header(viewer_client),
        )
        assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_suspended_user_denied_on_project_endpoint() -> None:
    transport = ASGITransport(app=app)
    email = _unique_email()
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _register_and_login(client, email=email, password=STRONG_PASSWORD, name="ToSuspend")
        org_id = await _create_org(client)

        async with AsyncSessionLocal() as session:
            await session.execute(update(User).where(User.email == email).values(is_active=False))
            await session.commit()

        resp = await client.get(f"/api/v1/projects?organization_id={org_id}")
        assert resp.status_code == 401
