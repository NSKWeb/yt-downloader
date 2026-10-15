# YT Downloader

A fast multi-platform video and audio downloader. Paste a link, pick a format,
get the file.

Supported platforms: **YouTube, Instagram, Facebook, Twitter/X, Pinterest, TikTok.**

- Video from 360p up to 4320p (8K), where the source provides it
- Audio extraction in MP3, M4A, WAV, FLAC, OPUS, AAC, and OGG, with selectable
  bitrate
- Per-platform format selection, so single-file sources are not asked for
  separate video and audio streams they do not have
- Multi-connection fetching via aria2c
- Background jobs on a queue, so long downloads survive a closed tab
- Live progress, speed, and ETA over a WebSocket, with polling fallback
- Per-IP rate limiting and a searchable download history

See [PLAN.md](PLAN.md) for the full feature breakdown.

## Stack

| Layer | Technology |
|-------|------------|
| Frontend | Plain HTML/CSS/JS, no build step |
| API | FastAPI |
| Download engine | yt-dlp + aria2c |
| Muxing / conversion | FFmpeg |
| Queue | ARQ + Redis |
| Process manager | Gunicorn + Uvicorn |
| Reverse proxy | Nginx |
| Deployment | Docker Compose |

## Architecture

```
Browser
   │  POST /api/download
   ▼
FastAPI  ──enqueue──►  Redis  ──►  ARQ worker
   │                                  │
   │                                  ├─ yt-dlp (+ aria2c) fetches streams
   │                                  └─ FFmpeg muxes / converts
   │                                  │
   │  WS /ws/progress/{id}  ◄─────────┘  (job record in Redis)
   │  GET /api/status/{id}  ◄──fallback─┘
   │
   └─ GET /api/file/{id}  ──►  finished file
```

Progress is pushed over a WebSocket. If the socket cannot be established — a
proxy that strips upgrades, a locked-down network — the frontend falls back to
polling `/api/status` and the user sees the same information.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | Liveness check |
| GET | `/api/platforms` | Supported platforms and their options |
| POST | `/api/download` | Queue a download |
| GET | `/api/status/{task_id}` | Progress, speed, ETA, status |
| GET | `/api/file/{task_id}` | Download the finished file |
| GET | `/api/history` | Recent jobs |
| DELETE | `/api/history/{task_id}` | Remove a history entry |
| GET | `/api/info?url=` | Metadata preview (title, duration, thumbnail) |
| WS | `/ws/progress/{task_id}` | Live progress stream |

## Quick start

### Docker (recommended)

```bash
git clone <your-repo-url>
cd yt-downloader
cp backend/.env.example backend/.env
docker compose up --build
```

Open <http://localhost:12000>.

### Local development

Requires Python 3.12+, FFmpeg, aria2, and a running Redis.

```bash
# Redis
redis-server --daemonize yes

# API
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export DOWNLOAD_DIR=/tmp/downloads REDIS_HOST=127.0.0.1
uvicorn app.main:app --reload
```

In a second terminal, start the worker:

```bash
cd backend
source .venv/bin/activate
export DOWNLOAD_DIR=/tmp/downloads REDIS_HOST=127.0.0.1
arq app.workers.tasks.WorkerSettings
```

Then serve `frontend/` however you like, e.g. `python -m http.server 8080`.

## Configuration

All settings come from environment variables. See
[`backend/.env.example`](backend/.env.example) for the full list.

| Variable | Default | Purpose |
|----------|---------|---------|
| `DOWNLOAD_DIR` | `/downloads` | Where finished files are written |
| `FILE_TTL_SECONDS` | `3600` | How long a file is retained |
| `REDIS_HOST` / `REDIS_PORT` | `redis` / `6379` | Queue backend |
| `ARIA2C_CONNECTIONS` | `16` | Connections per server |
| `ARIA2C_SPLIT` | `16` | File split count |
| `ARIA2C_CONNECT_TIMEOUT` | `60` | aria2c connect timeout, seconds |
| `ARIA2C_TIMEOUT` | `60` | aria2c per-read timeout, seconds |
| `MAX_CONCURRENT_JOBS` | `2` | Worker concurrency |
| `RATE_LIMIT_PER_MINUTE` | `10` | Requests allowed per IP per minute |
| `RATE_LIMIT_PER_HOUR` | `100` | Requests allowed per IP per hour |
| `RATE_LIMIT_ENABLED` | `true` | Turn the limiter off entirely |
| `DATABASE_PATH` | `<DOWNLOAD_DIR>/history.db` | SQLite history location |
| `HISTORY_ENABLED` | `true` | Record job history |
| `WS_POLL_INTERVAL` | `0.5` | Seconds between progress reads |
| `CORS_ORIGINS` | `*` | Allowed frontend origins |

## Tests

```bash
cd backend
pip install -r requirements.txt
python -m pytest -q      # 128 tests
ruff check app tests     # lint
```

Tests cover URL validation, platform detection, per-platform format-selection
logic, audio bitrate mapping, progress parsing, job lifecycle, rate limiting,
history recording, path-traversal rejection, and the absence of bot-bypass
flags. `ruff` and `pip-audit` also run in CI.

## Deployment notes

- **Datacenter IPs.** YouTube, and sometimes Twitter/X, refuse requests from
  datacenter IP ranges with a "Sign in to confirm you're not a bot" message.
  That is expected, not a bug: it is the platform declining the host, not the
  code failing. Run this on a residential or well-reputed host, or keep the
  volume low. Instagram and Pinterest can return `403` to a datacenter IP for
  the same reason.
- **Bandwidth.** Proxying files costs egress. 10,000 downloads averaging 1.5 GB
  is 15 TB of traffic. Budget for it or run it privately.
- **Legal.** Downloading is lawful only for content you have the right to save.
  You are responsible for how this tool is used. See the
  [DMCA](frontend/dmca.html) and [Disclaimer](frontend/disclaimer.html) pages.

## Subdomain architecture

The nginx server block uses `server_name _`, so one container answers for the
apex domain and for every platform subdomain
(`youtube.example.com`, `tiktok.example.com`, and so on). Add a wildcard DNS
record (`*.example.com`) and a wildcard certificate; no per-subdomain nginx
block is needed.

What the subdomain does and does not do:

- **Does:** set `request.state.subdomain_platform`, so a handler can default to
  that platform and the mapping can be logged. The frontend can pre-select the
  matching tab.
- **Does not:** grant any access. A request to `youtube.example.com` carrying a
  TikTok URL is validated against the URL allowlist exactly like any other
  request, and the Host header is never used for an authorization decision.

This matters because the `Host` header is attacker-controlled. Treating it as a
trust signal is how host-header injection becomes an open redirect or a cache
poisoning bug. Here it is a display hint only.

## Security

- **URL allowlist.** Only the six supported platforms' hosts are accepted; every
  other host is rejected before a job is queued, so the API cannot be pointed at
  an arbitrary URL.
- **Path-traversal rejection.** `/api/file/{task_id}` resolves the task's
  recorded filename inside the download directory and rejects anything that
  escapes it.
- **Rate limiting.** Sliding-window counters per client IP, in Redis.
- **Response headers.** `X-Content-Type-Options`, `X-Frame-Options`, and
  `Referrer-Policy` are set at the edge, and `server_tokens` is off.
- **Dependency audit.** `pip-audit` runs in CI and currently reports no known
  vulnerabilities.
- **No secrets in the image.** Configuration comes from the environment; only
  `.env.example` is committed.

## What this project does not do

By design, and stated plainly so nobody has to guess:

- No `player_client` spoofing or Proof-of-Origin token generation to defeat
  YouTube's bot detection.
- No proxy rotation or residential proxies to evade IP blocks.
- No cookie-based authentication to reach age-restricted content.
- No ad code is injected into the pages. The legal pages exist, but wiring up
  AdSense to monetise a downloader is a decision with real consequences, so it
  is left to the operator.

These are access-control measures, not speed features. Removing them costs no
performance: aria2c multi-connection, format pre-selection to avoid re-encoding,
and the async queue are where the speed actually comes from.

## Licence

MIT. See [LICENSE](LICENSE).
