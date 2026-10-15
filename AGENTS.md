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
- **`file_editor` writes files mode 600**, which breaks anything served from the
  read-only `frontend/` mount (403) and can break tooling that reads the repo as
  another user. After creating a file, run `chmod 644 <file>`. This has bitten
  `robots.txt`, `sitemap.xml`, and `README.md` so far.
- **yt-dlp reports `duration` as a float** (e.g. `74.304`) and the string `"NA"`
  when unknown. `InfoResponse.duration` is an `int` with a `mode="before"`
  validator that truncates via `float()` and maps unparseable values to `None`.
  Without it `/api/info` returns 500, not 422 — the response model raises during
  serialisation, after the handler has already returned.
- **`/api/info` had no test coverage**, which is why the 500 above survived. It
  now has two tests. Add route tests when adding routes.

## README assets

- `docs/img/*.svg` are hand-written diagrams (architecture, request flow, format
  pipeline, platform matrix). They use only text, rects, lines and paths, so
  GitHub renders them without a rasteriser. Keep `font-size` at 11.5px or above
  and check text fits its box before committing — an SVG that overflows looks
  broken on the repo page and no linter catches it.
- `docs/img/screenshot-*.png` are real captures of the running stack, taken with
  headless Chromium over the DevTools Protocol. To reproduce, start the stack,
  then drive `http://localhost:12000/` with CDP: `Page.navigate`,
  `Runtime.evaluate` to set the URL input and dispatch `input`/`change`, click
  `#submit`, and `Page.captureScreenshot`. Do not hand-write these; a stale
  screenshot is worse than none.
- Markdown payloads in the README were captured from the live API, not invented.
  Re-capture them if the response models change.

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

- **Pushing requires bypassing the global `gh` credential helper.** `~/.gitconfig`
  sets `credential.https://github.com.helper = !/usr/bin/gh auth git-credential`,
  which takes precedence over `GIT_ASKPASS`. Every push therefore sends the
  read-only `ghu_` app token and fails with `403 ... denied to NSKWeb`, even when
  a working write token is supplied. To push with an explicit token, point git at
  a clean global config and supply the token through an askpass helper:

  ```bash
  printf '[safe]\n\tdirectory = /workspace/project\n' > /tmp/gitconfig-clean
  PUSH_TOKEN=... GIT_CONFIG_GLOBAL=/tmp/gitconfig-clean \
    GIT_ASKPASS=/tmp/askpass.sh GIT_TERMINAL_PROMPT=0 git push origin main
  ```

  The `ghu_` app token itself has no write permission on any repo; a 403 from it
  is expected and does not mean the repo or the push URL is wrong.
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
