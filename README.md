# yt-downloader

A fast YouTube video and audio downloader. Paste a link, pick a format, get the
file.

- Video from 360p up to 4320p (8K), where the source provides it
- Audio extraction in MP3, M4A, WAV, FLAC, OPUS, AAC, and OGG
- Multi-connection fetching via aria2c
- Background jobs on a queue, so long downloads survive a closed tab
- Live progress, speed, and ETA

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
   │  GET /api/status/{id}  ◄──poll───┘  (job record in Redis)
   │
   └─ GET /api/file/{id}  ──►  finished file
```

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | Liveness check |
| POST | `/api/download` | Queue a download |
| GET | `/api/status/{task_id}` | Progress, speed, ETA, status |
| GET | `/api/file/{task_id}` | Download the finished file |
| GET | `/api/info?url=` | Metadata preview (title, duration, thumbnail) |

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
| `MAX_CONCURRENT_JOBS` | `2` | Worker concurrency |
| `CORS_ORIGINS` | `*` | Allowed frontend origins |

## Tests

```bash
cd backend
pip install -r requirements.txt
python -m pytest -q      # 35 tests
ruff check app tests     # lint
```

Tests cover URL validation, format-selection logic, progress parsing, job
lifecycle, path-traversal rejection, and the absence of bot-bypass flags.

## Deployment notes

- **Datacenter IPs.** YouTube frequently refuses requests from datacenter IP
  ranges with a "Sign in to confirm you're not a bot" message. That is expected.
  Run this on a residential or well-reputed host, or keep the volume low.
- **Bandwidth.** Proxying files costs egress. 10,000 downloads averaging 1.5 GB
  is 15 TB of traffic. Budget for it or run it privately.
- **Legal.** Downloading is lawful only for content you have the right to save.
  You are responsible for how this tool is used. See the
  [DMCA](frontend/dmca.html) and [Disclaimer](frontend/disclaimer.html) pages.

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
