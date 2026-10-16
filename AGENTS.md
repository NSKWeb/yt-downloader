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

- **Two appearance preferences ship: accent and light/dark mode.**
  - Accent: five palettes (`serenity`, `turquoise`, `aqua-sky`,
    `blue-turquoise`, `tiffany`), chosen from a picker in the **footer**.
    Stored in `localStorage["ytdl-accent"]`, applied as `[data-theme]`.
    Serenity is deliberately far from the other four; the turquoise family
    (Turquoise, Aqua Sky, Blue Turquoise, Tiffany Blue) is *intentionally*
    clustered within 15 CIELAB units, so those four read as one family rather
    than four separate colours. That is a product decision, not a bug. If a
    palette is ever swapped, keep any non-turquoise pair at least 25 apart in
    CIELAB and keep the turquoise family together;
    `test_palette_hues_are_spread_or_explicitly_clustered` pins both rules.
  - Mode: `dark` (default) or `light`, chosen from a toggle at the **top right
    of the header**. Stored in `localStorage["ytdl-mode"]`, applied as
    `[data-mode]`. An unset mode follows the OS via `prefers-color-scheme`.

  There are no user accounts, so nothing is stored server-side. The two controls
  are deliberately in different places: a display preference belongs in the
  header, and the footer keeps the brand choice out of the way.

  Each palette splits across four roles, plus an RGB triple:
  - `--accent` — text, borders, progress fill, chips
  - `--accent-solid` — filled buttons and active tabs
  - `--accent-ink` — the text on those filled surfaces
  - `--accent-hover` — hover fill, still clears the ink
  - `--accent-rgb` — the accent as an RGB triple, for the translucent shadows,
    focus ring and hero glow. **A hex alone is not enough**: `rgba()` cannot be
    built from a hex custom property, and hardcoding the numbers leaves the
    shadows blue after a switch. Every `rgba()` tint in the stylesheet goes
    through this token.

  The roles cannot share one variable. These accents are light, so they read as
  text on the dark `--bg` but cannot carry white text as a fill: filled surfaces
  use `--accent-ink`, **never** `#fff` (white on any of them is about 2:1). All
  five palettes clear WCAG AA on every role in both modes; the ratios are
  recorded in `backend/app/themes.py` and asserted by `tests/test_themes.py`,
  which also recomputes them from the hex values and checks the `:root` fallback,
  each `[data-theme]` block and every `--accent-rgb` triple in `style.css`
  against `GET /api/themes`. That test is the guard: editing a colour in one
  place without the other fails CI.

  **Light mode changes exactly one role.** `--accent` is measured against
  `--bg`, and `--bg` is what the mode swaps, so on the light page all three
  brand colours fall to 1.5-2.3:1 and each needs a darker sibling
  (`accent_light` in the catalogue: `#606F8A`, `#5F7081`, `#477772`, all near
  4.75:1). The fill roles are **mode-independent** — a filled button keeps the
  dark ink on the brand colour on either background — so light mode still shows
  the brand colour on the primary button. The focus ring is opaque in light mode
  rather than the 40% tint used on dark: a translucent tint of any of these is
  under 2:1 on a light page, below the 3:1 a focus indicator should clear. The
  state tokens (progress, alerts, success) are mode-dependent too and have their
  own light values in the `html[data-mode="light"]` block; keep new state
  colours in that block rather than hardcoding them.

  History, so it is not retried: bright red (`#ff0033`) vibrates on the dark
  background, reads as "error" on a primary action, and measured only 3.96:1
  against its own white button label. It went to a rose, then to sky blue, then
  to the selectable set.

  Colours live in the `:root` block plus one `[data-theme]` block per palette in
  `frontend/assets/style.css`, with the light overrides in the
  `html[data-mode="light"][data-theme=...]` blocks; all of it is mirrored in
  `backend/app/themes.py`. The palette selectors are prefixed with `html` on
  purpose so a stored `[data-theme]` still out-specifies `:root`. A small inline
  snippet in each page's `<head>` applies the stored `data-theme` **and**
  `data-mode` before first paint so there is no flash of the wrong accent or
  mode; keep that snippet in sync when adding a palette. `frontend/assets/
  favicon.ico` is a flat `--accent-solid` square, so adding a palette means
  recapturing the screenshots and rewriting the favicon.

  **The palette is written down in three places, and the frontend is the one
  that decides.** `frontend/assets/theme.js` carries its own `PALETTES` array,
  which is a real duplication rather than an oversight: the pre-paint snippet
  must resolve the stored accent synchronously, before any fetch can return.
  `tests/test_themes.py` therefore cross-checks all three -- the stylesheet,
  `app/themes.py` and `theme.js` -- plus the default mode, the mode list, both
  storage keys, and the wiring and control placement of every page, so a hex,
  key, name, default, mode or storage key edited in one place alone fails CI.

  Do not move the default to the backend. It is tempting, but the frontend is
  served as static files (nginx in the compose stack; FastAPI also serves them
  directly), so the backend cannot inject into the page and a server-supplied
  default would have to arrive by fetch -- after first paint, which is exactly
  the flash the inline snippet exists to prevent. A backend round-trip would buy
  a runtime cost and a flash in exchange for deduplicating three lists that a
  test already keeps honest. If a server-side override is ever genuinely needed,
  the flash-free shape is a tiny `:root{...}` stylesheet served from the API and
  linked in `<head>` -- not a config value the JS fetches. There is also no admin
  or auth mechanism anywhere in the backend, so a runtime "set the mood for
  everyone" endpoint would mean inventing one; see the scope boundary below.
- `docs/img/*.svg` are hand-written diagrams (architecture, request flow, format
  pipeline, platform matrix). They use only text, rects, lines and paths, so
  GitHub renders them without a rasteriser. Keep `font-size` at 11.5px or above
  and check text fits its box before committing — an SVG that overflows looks
  broken on the repo page and no linter catches it.
- `docs/img/screenshot-*.png` are real captures of the running stack, taken with
  headless Chromium over the DevTools Protocol at 1280x860 with
  `deviceScaleFactor: 2`, so they land at 2560x1720. Keep that size; the README
  lays them out side by side. To reproduce, serve the frontend (see the Redis
  note below), then drive `http://127.0.0.1:12000/` with CDP: `Page.navigate`,
  `Runtime.evaluate` to set the URL input and dispatch `input`/`change`, click
  `#submit`, and `Page.captureScreenshot`. The mode toggle's buttons are built by
  `app.js` and carry no `data-mode` attribute, so select them by index
  (`#mode-toggle button`[1] is Audio) rather than by attribute. Do not hand-write
  these; a stale screenshot is worse than none.
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
  is expected and does not mean the repo or the push URL is wrong. In this
  sandbox that is the *only* token available — `GH_TOKEN` is also present but
  reports as invalid (`gh auth status` fails on it) and there is no
  `~/.git-credentials`, `~/.netrc` or `gh` hosts file — so a push cannot be
  completed from here at all, by any of the URL/askpass routes above. Note the
  token's `permissions` block from `GET /api/repos/{owner}/{repo}` reports
  `"push": true`, which is misleading: that reflects the app's declared access,
  not what the installation actually grants. Commit locally and hand the push to
  the user rather than retrying variations.
- Python 3.13 locally, 3.12 in the Docker image
- FFmpeg and aria2c are installed. **`redis-server` is not**, contrary to what
  this file used to claim, and `dockerd` needs root so the compose stack cannot
  be brought up either. Redis-dependent tests still run, because
  `tests/test_api.py` injects an in-memory stub instead of opening a real pool.
  For screenshots, the same trick serves the real API: mount
  `frontend/` with `StaticFiles` and replace `app.state.redis` with that stub
  *before* `uvicorn.run`, and swap `app.router.lifespan_context` for a no-op so
  the ARQ pool is never opened. An `enqueue_job` stub that writes a terminal
  `JobState` is enough to photograph the completed-progress state through the
  genuine `/ws/progress` route. Never add a Redis dependency to the app to work
  around a sandbox gap.
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
