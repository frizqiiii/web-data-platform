"""Scheduler process entrypoint.

Phase 0 scope: skeleton only. Cron parsing, timezone handling, and
distributed locking to prevent duplicate dispatch across multiple
scheduler instances (Section 31/55) are NOT implemented — that is
Phase 6. This entrypoint deliberately raises rather than silently
doing nothing or pretending to schedule jobs (Section 1.5: no fake
scheduler).
"""


def main() -> None:
    raise NotImplementedError(
        "Scheduler logic is not implemented until Phase 6. "
        "This entrypoint exists only to reserve the process/deployment "
        "unit in the repository structure and docker-compose topology."
    )


if __name__ == "__main__":
    main()
