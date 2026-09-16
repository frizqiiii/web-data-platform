# Dashboard (Phase 9 — not yet built)

This directory is a placeholder, not a working Next.js application.

Per the plan, the dashboard is implemented in Phase 9. Scaffolding it
now with `pnpm create next-app` requires network access this
authoring environment does not have, and hand-writing a fake Next.js
skeleton that doesn't actually run would be exactly the kind of fake
completeness Master Prompt Section 1.5 forbids.

## What to run when Phase 9 starts

```bash
cd frontend
pnpm create next-app@latest dashboard --typescript --app --src-dir
```

Then wire it into `pnpm-workspace.yaml` (already present at repo
root) and `docker-compose.yml` (frontend service is currently
commented out there, with an explanation).
