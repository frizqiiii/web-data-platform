"""Structured JSON logging configuration for the worker.

Mirrors apps/api/app/core/logging.py's processor chain exactly (same
rule: Master Prompt Section 39/41 — never log passwords, tokens,
secrets, or credentials; a resolved credential value must never be
passed as a log field, and neither must the raw Authorization/Cookie
headers of a request or response). The two are deliberately separate
modules, not a shared one — same reasoning as `worker.core.config`
being its own `WorkerSettings` rather than importing the API's
`Settings` (ADR-002): the API and worker are deployed and scaled
independently.
"""

import logging
import sys

import structlog

from worker.core.config import get_worker_settings

_engine_execution_started = "engine_execution_started"
_engine_execution_completed = "engine_execution_completed"
_engine_execution_failed = "engine_execution_failed"
_ssrf_blocked = "ssrf_blocked"


def configure_logging() -> None:
    settings = get_worker_settings()
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=settings.log_level,
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_engine_logger() -> structlog.stdlib.BoundLogger:
    return structlog.get_logger("worker.engines")


def _base_fields(
    *,
    execution_id: object,
    organization_id: object,
    project_id: object,
    scraper_id: object,
    target_id: object,
    engine: str,
) -> dict:
    # UUIDs are passed as `object` and stringified here rather than
    # typed as `UUID` so this module doesn't need to import
    # worker.core.execution — keeps the dependency direction one-way
    # (execution model doesn't need to know about logging).
    return {
        "execution_id": str(execution_id),
        "organization_id": str(organization_id),
        "project_id": str(project_id),
        "scraper_id": str(scraper_id),
        "target_id": str(target_id),
        "engine": engine,
    }


def log_engine_execution_started(logger: structlog.stdlib.BoundLogger, **fields: object) -> None:
    logger.info(_engine_execution_started, **_base_fields(**fields))


def log_engine_execution_completed(
    logger: structlog.stdlib.BoundLogger, *, duration_ms: int, **fields: object
) -> None:
    logger.info(_engine_execution_completed, duration_ms=duration_ms, **_base_fields(**fields))


def log_engine_execution_failed(
    logger: structlog.stdlib.BoundLogger,
    *,
    duration_ms: int,
    error_category: str,
    **fields: object,
) -> None:
    logger.info(
        _engine_execution_failed,
        duration_ms=duration_ms,
        error_category=error_category,
        **_base_fields(**fields),
    )


def log_ssrf_blocked(
    logger: structlog.stdlib.BoundLogger, *, error_category: str, **fields: object
) -> None:
    logger.warning(_ssrf_blocked, error_category=error_category, **_base_fields(**fields))
