#!/usr/bin/env bash
set -euo pipefail

# Creates the platform's default bucket in the local MinIO instance.
# Not wired into docker-compose automatically yet (no application
# code touches object storage until Phase 8) — run manually if you
# want to poke at MinIO now:
#
#   docker compose up -d minio
#   ./scripts/init-minio.sh

MINIO_ENDPOINT="${MINIO_ENDPOINT:-localhost:9000}"
MINIO_ACCESS_KEY="${MINIO_ACCESS_KEY:-platform}"
MINIO_SECRET_KEY="${MINIO_SECRET_KEY:-platform123}"
MINIO_BUCKET="${MINIO_BUCKET:-web-data-platform}"

mc alias set local "http://${MINIO_ENDPOINT}" "${MINIO_ACCESS_KEY}" "${MINIO_SECRET_KEY}"
mc mb --ignore-existing "local/${MINIO_BUCKET}"
