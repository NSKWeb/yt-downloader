# AGENTS.md

Repository memory for agent sessions. Keep this current when the project changes.

## Repository

- Published at https://github.com/NSKWeb/yt-downloader (public, default branch
  `main`).
- CI runs four jobs on every push and pull request: `test`, `lint`, `security`,
  `docker`. Keep them green; the workflow is `.github/workflows/ci.yml`.
- `frontend/robots.txt` and `frontend/sitemap.xml` ship with `https://example.com`
  placeholders. They must be replaced with the real domain before the site is
  indexed, or the sitemap points at the wrong host.
- Files in `frontend/` are served by nginx from a read-only bind mount, so a file
  created without world-readable permissions returns 403 rather than being
  served. If a new page 403s, check its mode before touching the config.

## What this is

A multi-platform (YouTube, Instagram, Facebook, Twitter/X, Pinterest, TikTok)
video/audio downloader: FastAPI API + ARQ worker + Redis, with a plain
HTML/CSS/JS frontend served by Nginx. `PLAN.md` holds the full must-have/optional
feature list with build status.

## Commands

```bash
# Tests and lint (from backend/)
python -m pytest -q
ruff check app tests
pip-audit -r requirements.txt

# Local stack
redis-server --daemonize yes
DOWNLOAD_DIR=/tmp/downloads REDIS_HOST=127.0.0.1 uvicorn app.main:app --reload
DOWNLOAD_DIR=/tmp/downloads REDIS_HOST=127.0.0.1 arq app.workers.tasks.WorkerSettings

# Docker
docker compose up --build
docker compose config --quiet   # validate before pushing
```

## Layout

- `backend/app/main.py` — FastAPI routes, WebSocket progress, rate-limit middleware
- `backend/app/downloader.py` — yt-dlp argv construction + subprocess runner
- `backend/app/platforms.py` — platform registry, detection, format selectors
- `backend/app/models.py` — Pydantic schemas, job state, URL validation
- `backend/app/storage.py` — Redis job records (`job:{task_id}`, 24h TTL)
- `backend/app/history.py` — SQLite history (fails open on a bad path)
- `backend/app/workers/tasks.py` — ARQ worker
- `frontend/` — static pages, `assets/style.css`, `assets/app.js`, legal pages
- `nginx/nginx.conf` — proxy, port 12000

## Conventions and gotchas

- **yt-dlp is invoked as `sys.executable -m yt_dlp`**, never the bare `yt-dlp`
  console script. A bare name resolves against PATH and fails inside the worker.
- **Tests must not touch real Redis.** `tests/test_api.py` injects a `FakeRedis`
  and builds `TestClient(app)` without the context manager — using `with
  TestClient(app)` runs the lifespan handler and opens a real Redis pool. The
  fake must implement the zset calls the rate limiter uses, or the limiter
  raises instead of counting.
- **`conftest.py` sets `DOWNLOAD_DIR` before `app` is imported**, because
  `Settings()` is instantiated at import time. The default `/downloads` is not
  writable in CI.
- **Format selection is per-platform.** YouTube gets
  `bestvideo[height<=N]+bestaudio/best[height<=N]` because it serves separate
  streams. Single-file sources (TikTok, Instagram, Facebook, Twitter, Pinterest)
  get `best[height<=N]/best`; asking them for a separate audio stream selects
  nothing and the job fails. Audio mode uses `bestaudio/best` everywhere, and
  Pinterest images use `best`.
- **aria2c's defaults are stricter than yt-dlp's and will fail a download that
  yt-dlp would have completed.** A host slow to complete a TLS handshake gets
  killed after 60s per try, and the retry loop makes the job look like it hung
  for five minutes. `build_command` passes generous `--connect-timeout`,
  `--timeout`, `--max-tries`, and `--lowest-speed-limit=0`. Keep those.
- **aria2c's progress bar drowns out real errors.** `--summary-interval=0
  --console-log-level=warn` quiets it, and `_meaningful_error()` filters any that
  still appear so the message shown to users is the actual cause.
- `--no-playlist` is always set; the app is single-video unless playlist mode is
  explicitly requested (YouTube only).

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
- In this sandbox, the Docker network cannot complete a TLS handshake to some
  platform CDN hosts (`v19-webapp-prime.us.tiktok.com`, `video.twimg.com`), while
  the host machine reaches them fine. A download that fails only inside the
  container is usually this, not a code fault — verify with a plain
  `socket`/`ssl` connection from inside the worker before changing code.
- Facebook's CDN is reachable from the container, so it is the most reliable
  platform for an end-to-end check here.
- Frontend is served on port 12000 in Docker; `work-1-...` host maps to it.
