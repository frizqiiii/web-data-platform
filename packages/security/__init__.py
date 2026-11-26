"""Shared, dependency-light security utilities used by more than one
app in this monorepo (currently: apps/api and apps/worker).

Nothing in this package may import from `app.*` or `worker.*` — the
dependency direction is one-way (apps depend on packages/, never the
reverse), otherwise this stops being a shared module and becomes a
hidden coupling between the two apps.
"""
