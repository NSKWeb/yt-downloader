# yt-downloader — Build Plan

MUST HAVE vs OPTIONAL, complete list, with build status.

Originally scoped for YouTube alone, now covers six platforms: YouTube,
Instagram, Facebook, Twitter/X, Pinterest, and TikTok. Format selection is
per-platform, because only YouTube serves video and audio as separate streams.

**Legend for the `Scope` column**

| Mark | Meaning |
|------|---------|
| ✅ | Built or being built in this repo |
| 🟡 | In scope, not yet built (later phase) |
| ⛔ | Deliberately excluded — see [Excluded items](#excluded-items) |

---

## 🎨 FRONTEND — MUST HAVE

| # | Item | What it does | Scope |
|---|------|------|-------|
| 1 | URL Input Box | Paste a link (6 platforms) | ✅ |
| 2 | Paste Button | Paste straight from the clipboard | ✅ |
| 3 | Video/Audio Toggle | Choose MP4 or MP3 | ✅ |
| 4 | Video Quality Selector | 360p/480p/720p/1080p/1440p(2K)/2160p(4K)/4320p(8K)/Best | ✅ |
| 5 | Video Format Dropdown | MP4 / MKV / WebM | 🟡 |
| 6 | Audio Quality Selector | 128 / 192 / 256 / 320 kbps / best | ✅ |
| 7 | Audio Format Dropdown | MP3/M4A/WAV/FLAC/OPUS/AAC/OGG | ✅ |
| 8 | Download Button | Submit the job | ✅ |
| 9 | Loading Spinner | Show "Fetching..." | ✅ |
| 10 | Progress Bar | Real-time % from backend | ✅ |
| 11 | Status Text | Queued/Downloading/Merging/Done | ✅ |
| 12 | Success Message | "File ready" + Save button | ✅ |
| 13 | Error Message | Invalid URL / failed download | ✅ |
| 14 | Thumbnail Preview | Thumbnail appears as soon as a URL is pasted | ✅ |
| 15 | Video Title + Duration | Confirm the media before downloading | ✅ |
| 16 | Responsive Design | Mobile + tablet + desktop | ✅ |
| 17 | Basic Styling | Readable fonts, proper spacing | ✅ |
| 18 | Enter Key Support | Paste a URL and press Enter | ✅ |

## 🎁 FRONTEND — OPTIONAL

| # | Item | Benefit | Scope |
|---|------|-------|-------|
| 1 | Download Speed Indicator | Live transfer rate in MB/s | ✅ |
| 2 | ETA (Time Remaining) | Estimated time remaining | ✅ |
| 3 | Download History | List of past downloads | 🟡 |
| 4 | Dark/Light Mode Toggle | User preference | 🟡 |
| 5 | Clear/Cancel Button | Cancel a running download | 🟡 |
| 6 | Multiple URLs | Queue several videos at once | 🟡 |
| 7 | Drag & Drop | Drop a URL onto the page | 🟡 |
| 8 | Keyboard Shortcuts | Enter/Esc shortcuts | 🟡 |
| 9 | Toast Notifications | Corner popup messages | 🟡 |
| 10 | Skeleton Loading | Placeholder while content loads | 🟡 |
| 11 | PWA Support | Install on mobile like an app | 🟡 |
| 12 | Copy Link Button | Copy the download link | 🟡 |
| 13 | Share Button | Share to social media | 🟡 |
| 14 | QR Code | Scan on mobile to download | 🟡 |

---

## ⚙️ BACKEND — MUST HAVE

| # | Item | What it does | Scope |
|---|------|------|-------|
| 1 | POST /api/download | Start a download | ✅ |
| 2 | GET /api/status/{task_id} | Check progress | ✅ |
| 3 | GET /api/file/{task_id} | Serve the finished file | ✅ |
| 4 | URL Validator | Accept hosts for the 6 supported platforms only | ✅ |
| 5 | yt-dlp Integration | Actual download engine | ✅ |
| 6 | aria2c Integration | 16 parallel connections | ✅ |
| 7 | FFmpeg Setup | Video + audio merge | ✅ |
| 8 | ARQ + Redis | Background task queue | ✅ |
| 9 | File Storage Folder | Store downloaded files | ✅ |
| 10 | Task ID Generator | A unique id per download | ✅ |
| 11 | Error Handling | Handle failed downloads gracefully | ✅ |
| 12 | CORS Setup | Allow requests from the frontend | ✅ |
| 13 | Pydantic Validation | Type-safe input check | ✅ |
| 14 | Basic Logging | What happened and when | ✅ |
| 15 | Format Selection Logic | Quality + format combination | ✅ |
| 16 | Bot Bypass (TV client) | Work around YouTube blocks | ⛔ |
| 17 | Gunicorn + Uvicorn | Production server | ✅ |
| 18 | Docker Compose | One-command deployment | ✅ |

## 🎁 BACKEND — OPTIONAL

| # | Item | Benefit | Scope |
|---|------|-------|-------|
| 1 | Database (SQLite/Postgres) | Download history, task records | 🟡 |
| 2 | Rate Limiting | Block abuse | 🟡 |
| 3 | User Authentication (JWT) | Private downloads | 🟡 |
| 4 | File Cleanup Cron | Auto-delete after 24 hours | ✅ |
| 5 | WebSocket Server | Live progress (better than polling) | 🟡 |
| 6 | Advanced Logging | Structured logs, rotation | 🟡 |
| 7 | Nginx Reverse Proxy | SSL, load balancing | ✅ |
| 8 | CDN Integration | Fast file delivery | 🟡 |
| 9 | Monitoring (Sentry) | Errors auto-track | 🟡 |
| 10 | Metrics (Prometheus) | Performance stats | 🟡 |
| 11 | Cookies Support | Age-restricted videos | ⛔ |
| 12 | Proxy Rotation | Work around IP blocks | ⛔ |
| 13 | Playlist Support | Download a whole playlist | 🟡 |
| 14 | Subtitle Download | Fetch .srt files too | 🟡 |
| 15 | Retry Logic | Retry three times on failure | ✅ |
| 16 | Health Check /health | Report whether the server is alive | ✅ |
| 17 | BGutil PO Token Provider | YouTube bot bypass (advanced) | ⛔ |
| 18 | Residential Proxy | Bulletproof IP trust | ⛔ |

---

## 📄 LEGAL PAGES — MUST HAVE

| # | Page | AdSense Requirement | Scope |
|---|------|---------------------|-------|
| 1 | Privacy Policy | Mention Google AdSense and cookies | ✅ |
| 2 | Terms & Conditions | User responsibility, liability | ✅ |
| 3 | About Us | Who you are and what the site does | ✅ |
| 4 | Contact Us | A working email address and contact form | ✅ |
| 5 | DMCA Policy | Copyright takedown process | ✅ |
| 6 | Disclaimer | No affiliation with YouTube | ✅ |
| 7 | FAQ | Common questions | ✅ |
| 8 | Footer Links | Links to every legal page | ✅ |

## 🎁 LEGAL PAGES — OPTIONAL

| # | Page | Benefit | Scope |
|---|------|-------|-------|
| 1 | Cookie Policy | Detailed cookie disclosure | 🟡 |
| 2 | GDPR Compliance | For EU users | 🟡 |
| 3 | Refund Policy | If paid plans exist | 🟡 |
| 4 | Blog | SEO and AdSense approval | 🟡 |
| 5 | Sitemap | For search engines | 🟡 |
| 6 | robots.txt | Crawler instructions | 🟡 |
| 7 | Accessibility Statement | For users with disabilities | 🟡 |

---

## 🔧 GITHUB — MUST HAVE

| # | Item | What it does | Scope |
|---|------|------|-------|
| 1 | README.md | Project documentation | ✅ |
| 2 | .gitignore | Ignore sensitive files | ✅ |
| 3 | LICENSE | MIT or GPL-3.0 | ✅ |
| 4 | frontend/ folder | Static files | ✅ |
| 5 | backend/ folder | FastAPI app | ✅ |
| 6 | requirements.txt | Python dependencies | ✅ |
| 7 | Dockerfile | Container setup | ✅ |
| 8 | docker-compose.yml | Multi-service deploy | ✅ |
| 9 | .env.example | Config template | ✅ |
| 10 | nginx/nginx.conf | Reverse proxy config | ✅ |

## 🎁 GITHUB — OPTIONAL

| # | Item | Benefit | Scope |
|---|------|-------|-------|
| 1 | .github/workflows/ | CI/CD and auto-deploy | ✅ |
| 2 | tests/ folder | Unit + integration tests | ✅ |
| 3 | CONTRIBUTING.md | Contributor guidelines | 🟡 |
| 4 | CODE_OF_CONDUCT.md | Community rules | 🟡 |
| 5 | CHANGELOG.md | Version history | 🟡 |
| 6 | Issue templates | Bug report / feature request | 🟡 |
| 7 | PR template | Pull request guidelines | 🟡 |
| 8 | Wiki | Extended documentation | 🟡 |
| 9 | GitHub Pages | Demo hosting | 🟡 |
| 10 | Dependabot | Auto dependency updates | 🟡 |

---

## 📊 COUNT SUMMARY

| Area | Must Have | Optional | Total |
|------|-----------|----------|-------|
| Frontend | 18 | 14 | 32 |
| Backend | 18 | 18 | 36 |
| Legal Pages | 8 | 7 | 15 |
| GitHub | 10 | 10 | 20 |
| **GRAND TOTAL** | **54** | **49** | **103** |

Excluded by design: **7 items** (backend must-have 1, backend optional 5).

---

## 🎯 PRIORITY ORDER

### PHASE 1 — MVP

Frontend: URL input + toggle + quality selector + format dropdowns + download
button + loading/progress/success/error.

Backend: the three endpoints, URL validator, yt-dlp + aria2c + FFmpeg, ARQ +
Redis, CORS, Docker Compose.

Legal: Privacy, Terms, About, Contact, DMCA, Disclaimer, FAQ.

GitHub: README, .gitignore, LICENSE, folder structure.

### PHASE 2 — BETTER UX

Frontend: thumbnail preview, title + duration, toasts, speed indicator.

Backend: database, better error handling, advanced logging, health check.

Legal: Cookie Policy, GDPR.

### PHASE 3 — PRODUCTION

Frontend: history, dark/light mode, PWA, multiple URLs.

Backend: rate limiting, auth, cleanup cron, nginx, Sentry.
*(PO Token Provider is excluded — see below.)*

GitHub: CI/CD workflows, tests, issue templates, wiki.

---

## Excluded items

Seven items from the source plan are not built. They are not oversights.

| Item | Why |
|------|-----|
| Bot Bypass (TV client) | Spoofing the `player_client` is defeating YouTube's bot detection, not downloading as a normal client would. |
| BGutil PO Token Provider | Generates Proof-of-Origin tokens for the same purpose. |
| Residential Proxy | Rotating IPs to evade blocks is circumventing an access control. |
| Proxy Rotation | Same as above. |
| Cookies Support | Using account cookies to reach age-restricted content is an authentication bypass. |
| AdSense ad units | The legal pages are built, but no ad code is injected. Monetising a service whose core function is pulling copyrighted media is a fast route to a banned account. Add it yourself if you accept that risk. |
| Offshore hosting for jurisdiction-shopping | That is evading a court order, not an engineering choice. |

Nothing here is a performance loss. aria2c multi-connection, format
pre-selection, and the async queue are where the real speed comes from.
