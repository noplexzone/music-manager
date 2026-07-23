#!/bin/sh
set -e

echo "Running Alembic migrations..."
alembic upgrade head

echo "Reconciling catalog file metadata..."
if ! python -m app.services.catalog_reconcile; then
  echo "Warning: catalog metadata reconciliation failed; continuing startup" >&2
fi

echo "Starting Audiohoard..."
exec uvicorn app.main:app \
  --host "${APP_HOST:-0.0.0.0}" \
  --port "${APP_PORT:-8000}" \
  --log-level "${LOG_LEVEL:-info}"
