"""Dummy task proving the queue pipeline works end-to-end.

This is intentionally trivial. The distinction from a "fake queue
execution" (forbidden by Section 1.5) is that this task is REAL: it
is actually serialized, sent through Redis, picked up by an actual
worker process, and actually executed — it just doesn't do anything
domain-specific yet, because there is no domain logic in Phase 0.
"""

from worker.main import app


@app.task(name="worker.tasks.ping.ping")
def ping() -> str:
    return "pong"
