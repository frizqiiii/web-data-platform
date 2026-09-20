"""FastAPI application entrypoint."""

from fastapi import FastAPI

from app.api.router import router
from app.core.logging import configure_logging
from app.modules.auth.router import router as auth_router
from app.modules.organizations.router import router as organizations_router
from app.modules.projects.router import router as projects_router
from app.modules.scrapers.router import project_scrapers_router
from app.modules.scrapers.router import router as scrapers_router
from app.modules.targets.router import router as targets_router
from app.modules.targets.router import scraper_targets_router

configure_logging()

app = FastAPI(
    title="Web Data Acquisition & Automation Platform",
    version="0.1.0",
)

# Root-level probes for infra (Kubernetes probes hit these unversioned)
app.include_router(router)
# Versioned surface per Section 9 API contract
app.include_router(router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(organizations_router, prefix="/api/v1")
app.include_router(projects_router, prefix="/api/v1")
app.include_router(project_scrapers_router, prefix="/api/v1")
app.include_router(scrapers_router, prefix="/api/v1")
app.include_router(scraper_targets_router, prefix="/api/v1")
app.include_router(targets_router, prefix="/api/v1")
