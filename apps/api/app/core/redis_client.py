"""Shared async Redis client for the API process.

Separate from apps/worker/worker/core/config.py's Redis usage (that's
Celery's broker connection, a different client/connection pool
entirely) — this one backs session storage (app/core/sessions.py).
"""

from functools import lru_cache
from typing import cast

import redis.asyncio as redis

from app.core.config import get_settings


@lru_cache
def get_redis_client() -> redis.Redis:
    settings = get_settings()
    # redis-py's `from_url` stub returns a looser type than `Redis`
    # (found by actually running mypy) — this cast reflects what
    # `from_url` actually constructs, not a new assumption.
    return cast(redis.Redis, redis.from_url(str(settings.redis_url), decode_responses=True))
