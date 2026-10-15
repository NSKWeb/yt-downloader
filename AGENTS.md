# AGENTS.md

Repository memory for agent sessions. Keep this current when the project changes.

## What this is

A YouTube video/audio downloader: FastAPI API + ARQ worker + Redis, with a
plain HTML/CSS/JS frontend served by Nginx. `PLAN.md` holds the full
must-have/optional feature list with build status.

## Commands

```bash
# Tests and lint (from backend/)
python -m pytest -q
ruff check app tests

# Local stack
redis-server --daemonize yes
DOWNLOAD_DIR=/tmp/downloads REDIS_HOST=127.0.0.1 uvicorn app.main:app --reload
DOWNLOAD_DIR=/tmp/downloads REDIS_HOST=127.0.0.1 arq app.workers.tasks.WorkerSettings

# Docker
docker compose up --build
docker compose config --quiet   # validate before pushing
```

## Layout

- `backend/app/main.py` — FastAPI routes
- `backend/app/downloader.py` — yt-dlp argv construction + subprocess runner
- `backend/app/models.py` — Pydantic schemas, job state, URL validation
- `backend/app/storage.py` — Redis job records (`job:{task_id}`, 24h TTL)
- `backend/app/workers/tasks.py` — ARQ worker
- `frontend/` — static pages, `assets/style.css`, `assets/app.js`
- `nginx/nginx.conf` — proxy, port 12000

## Conventions and gotchas

- **yt-dlp is invoked as `sys.executable -m yt_dlp`**, never the bare `yt-dlp`
  console script. A bare name resolves against PATH and fails inside the worker.
- **Tests must not touch real Redis.** `tests/test_api.py` injects a `FakeRedis`
  and builds `TestClient(app)` without the context manager — using `with
  TestClient(app)` runs the lifespan handler and opens a real Redis pool.
- **`conftest.py` sets `DOWNLOAD_DIR` before `app` is imported**, because
  `Settings()` is instantiated at import time. The default `/downloads` is not
  writable in CI.
- **Format selection is YouTube-shaped.** `bestvideo+bestaudio/best` assumes
  separate streams. Single-file sources need `best`.
- `--no-playlist` is always set; the app is single-video by design.

## Scope boundary

These are intentionally absent. Do not add them without an explicit user
decision, and do not add them quietly:

- `player_client` spoofing / PO token generation (bot-detection bypass)
- Proxy rotation or residential proxies (IP-block evasion)
- Cookie-based auth for age-restricted content
- AdSense or any ad injection into the frontend

`tests/test_downloader.py::test_no_bot_bypass_flags_present` guards the first
group. If that test starts failing, something was added that should not have
been.

## Environment facts

- Python 3.13 locally, 3.12 in the Docker image
- FFmpeg, aria2c, and redis-server are installed in the dev container
- Datacenter IPs get refused by YouTube ("Sign in to confirm you're not a bot").
  This is expected and is not a bug in this code.
- Frontend is served on port 12000 in Docker; `work-1-...` host maps to it.
