#!/bin/sh
set -eu

if [ "${RUN_MIGRATIONS:-true}" = "true" ] && [ "${1:-}" = "uvicorn" ]; then
  echo "Running database migrations..."
  alembic upgrade head
fi

exec "$@"
