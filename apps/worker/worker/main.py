"""Celery application entrypoint.

Phase 0 scope: prove the worker process can connect to Redis and
execute a task end-to-end via worker.tasks.ping. No scraping tasks
exist yet (Section 1.5 — no fake queue execution standing in for
real scraping); those start in Phase 5.
"""

from celery import Celery

from worker.core.config import get_worker_settings

settings = get_worker_settings()

app = Celery(
    "web_data_platform_worker",
    broker=str(settings.redis_url),
    backend=str(settings.redis_url),
    include=["worker.tasks.ping"],
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Logical queue names from Section 26 are reserved here but not
    # yet routed to, since no real tasks exist to route.
    task_default_queue="maintenance",
)
