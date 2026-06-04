#!/bin/sh
# Container entrypoint: apply Postgres migrations (idempotent) then serve the app.
# Set RUN_MIGRATIONS=false to skip the migrate step (e.g. when a Job owns schema).
set -e

if [ -n "$DATABASE_URL" ] && [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  echo "[entrypoint] applying migrations…"
  python -m migrate
fi

echo "[entrypoint] starting uvicorn on ${HOST:-0.0.0.0}:${PORT:-8000}"
exec python -m server
