#!/usr/bin/env bash
# Runs the API and the ARQ worker together so a single-service host (ZopCloud)
# gets the whole backend from one container.
#
# Both processes need Redis at startup: the API's lifespan calls create_pool()
# and the worker connects on boot, so with no reachable Redis the API worker
# dies before it binds the port. If the configured REDIS_HOST does not answer,
# start a local redis-server so the container is self-contained. Point
# REDIS_HOST at a managed Redis instance to use that instead.
set -euo pipefail

: "${PORT:=8000}"
: "${WEB_CONCURRENCY:=2}"
: "${REDIS_HOST:=redis}"
: "${REDIS_PORT:=6379}"

redis_is_up() {
    # A TCP connect is enough: both consumers just need something listening.
    timeout 1 bash -c "</dev/tcp/${REDIS_HOST}/${REDIS_PORT}" 2>/dev/null
}

start_local_redis() {
    echo "start.sh: no Redis at ${REDIS_HOST}:${REDIS_PORT}; starting a local redis-server"
    redis-server --daemonize no --save '' --appendonly no \
        --bind 0.0.0.0 --port "${REDIS_PORT}" --dir /tmp &
    redis_pid=$!
    export REDIS_HOST=127.0.0.1
    for _ in $(seq 1 50); do
        if redis_is_up; then
            echo "start.sh: local redis-server is up"
            return 0
        fi
        sleep 0.2
    done
    echo "start.sh: local redis-server failed to start" >&2
    return 1
}

if ! redis_is_up; then
    start_local_redis
fi

arq app.workers.tasks.WorkerSettings &
worker_pid=$!

shutdown() {
    kill -TERM "$worker_pid" 2>/dev/null || true
    wait "$worker_pid" 2>/dev/null || true
    if [ -n "${redis_pid:-}" ]; then
        kill -TERM "$redis_pid" 2>/dev/null || true
    fi
}
trap shutdown TERM INT

gunicorn app.main:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers "${WEB_CONCURRENCY}" \
    --bind "0.0.0.0:${PORT}" \
    --timeout 120 &
api_pid=$!

# Exit as soon as either process dies, then stop the survivors.
wait -n "$api_pid" "$worker_pid" || true
shutdown
wait 2>/dev/null || true
