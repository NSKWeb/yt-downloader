#!/usr/bin/env bash
# Start the screenshot intake server.
#
#   ./run.sh              listen on 12000, no token
#   PORT=8080 ./run.sh    another port
#   UPLOAD_TOKEN=x ./run.sh   require ?t=x on every route but /health
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-12000}"
export PORT
exec python3 screenshot_server.py
