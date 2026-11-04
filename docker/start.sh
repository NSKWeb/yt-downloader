#!/usr/bin/env bash
# Runs the API and the ARQ worker together so a single-service host (ZopCloud)
# gets the whole backend from one container. The API runs in the foreground; the
# worker runs in the background and both are torn down together. The container
# runs as the unprivileged `app` user, so SIGTERM goes to this shell and is
# forwarded to both children.
set -euo pipefail

: "${PORT:=8000}"
: "${WEB_CONCURRENCY:=2}"

arq app.workers.tasks.WorkerSettings &
worker_pid=$!

shutdown() {
    kill -TERM "$worker_pid" 2>/dev/null || true
    wait "$worker_pid" 2>/dev/null || true
}
trap shutdown TERM INT

gunicorn app.main:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers "${WEB_CONCURRENCY}" \
    --bind "0.0.0.0:${PORT}" \
    --timeout 120 &
api_pid=$!

# Exit as soon as either process dies, then stop the survivor.
wait -n "$api_pid" "$worker_pid" || true
shutdown
wait 2>/dev/null || true
