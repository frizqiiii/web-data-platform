"""Structured JSON logging configuration.

Rule (Master Prompt Section 39/41): never log passwords, tokens,
secrets, or credentials. This module only sets up the processor
chain — callers are responsible for not passing sensitive values as
log fields. Correlation fields (request_id, organization_id, job_id,
...) are bound via structlog.contextvars starting from the modules
that introduce them (auth middleware in Phase 1, job execution in
Phase 4, etc.) — Phase 0 only wires the base chain.
"""
import logging
import sys

import structlog

from app.core.config import get_settings


def configure_logging() -> None:
    settings = get_settings()
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
