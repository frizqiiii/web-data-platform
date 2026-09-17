"""FastAPI application entrypoint."""

from fastapi import FastAPI

from app.api.router import router
from app.core.logging import configure_logging

configure_logging()

app = FastAPI(
    title="Web Data Acquisition & Automation Platform",
    version="0.1.0",
)

# Root-level probes for infra (Kubernetes probes hit these unversioned)
app.include_router(router)
# Versioned surface per Section 9 API contract
app.include_router(router, prefix="/api/v1")
