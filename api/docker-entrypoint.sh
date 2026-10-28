#!/bin/sh
# api:    run migrations, seed the curriculum, then serve
# worker: run the background job worker
set -e

case "$1" in
  api)
    echo '{"msg":"running migrations"}'
    alembic upgrade head
    python -m app.seed
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 \
      --workers "${API_WORKERS:-2}" --proxy-headers --forwarded-allow-ips '*' \
      --no-access-log
    ;;
  worker)
    exec arq app.worker.WorkerSettings
    ;;
  *)
    exec "$@"
    ;;
esac
