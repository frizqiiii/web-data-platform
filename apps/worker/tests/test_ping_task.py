"""Test for the dummy ping task.

This test uses Celery's eager mode (task_always_eager), which means
it does NOT require a live Redis broker to run — task submission and
execution both happen synchronously in-process. It does, however,
require the `celery` package to be installed, which it is not in the
sandbox this repository was authored in (no network to install
dependencies there). Status as authored: UNVERIFIED (dependency not
installed in authoring environment), NOT BLOCKED (no infra needed).

Run for real via:
    uv sync --group worker --group dev
    uv run pytest apps/worker/tests -v
"""

from worker.main import app as celery_app
from worker.tasks.ping import ping


def test_ping_task_executes_and_returns_pong() -> None:
    celery_app.conf.task_always_eager = True
    result = ping.delay()
    assert result.get(timeout=5) == "pong"
