# multi-downloader — Build Plan

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

| # | Item | Kaam | Scope |
|---|------|------|-------|
| 1 | URL Input Box | Link paste karne ke liye (6 platforms) | ✅ |
| 2 | Paste Button | Clipboard se direct paste | ✅ |
| 3 | Video/Audio Toggle | MP4 ya MP3 choose karne ke liye | ✅ |
| 4 | Video Quality Selector | 360p/480p/720p/1080p/1440p(2K)/2160p(4K)/4320p(8K)/Best | ✅ |
| 5 | Video Format Dropdown | MP4 / MKV / WebM | 🟡 |
| 6 | Audio Quality Selector | 128 / 192 / 256 / 320 kbps / best | ✅ |
| 7 | Audio Format Dropdown | MP3/M4A/WAV/FLAC/OPUS/AAC/OGG | ✅ |
| 8 | Download Button | Submit karne ke liye | ✅ |
| 9 | Loading Spinner | "Fetching..." dikhane ke liye | ✅ |
| 10 | Progress Bar | Real-time % from backend | ✅ |
| 11 | Status Text | Queued/Downloading/Merging/Done | ✅ |
| 12 | Success Message | "File ready hai" + Save button | ✅ |
| 13 | Error Message | Invalid URL / failed download | ✅ |
| 14 | Thumbnail Preview | URL paste karte hi video image | ✅ |
| 15 | Video Title + Duration | Confirm karne ke liye | ✅ |
| 16 | Responsive Design | Mobile + tablet + desktop | ✅ |
| 17 | Basic Styling | Readable fonts, proper spacing | ✅ |
| 18 | Enter Key Support | URL daal ke Enter dabao | ✅ |

## 🎁 FRONTEND — OPTIONAL

| # | Item | Fayda | Scope |
|---|------|-------|-------|
| 1 | Download Speed Indicator | Kitne MB/s chal raha hai | ✅ |
| 2 | ETA (Time Remaining) | Kitna time lagega | ✅ |
| 3 | Download History | Pehle ke downloads ki list | 🟡 |
| 4 | Dark/Light Mode Toggle | User preference | 🟡 |
| 5 | Clear/Cancel Button | Download rokne ke liye | 🟡 |
| 6 | Multiple URLs | Ek saath kai videos queue | 🟡 |
| 7 | Drag & Drop | URL drag karke drop | 🟡 |
| 8 | Keyboard Shortcuts | Enter/Esc shortcuts | 🟡 |
| 9 | Toast Notifications | Corner popup messages | 🟡 |
| 10 | Skeleton Loading | Content load hone tak placeholder | 🟡 |
| 11 | PWA Support | Mobile pe app jaisa install | 🟡 |
| 12 | Copy Link Button | Download link copy karne ke liye | 🟡 |
| 13 | Share Button | Social media pe share | 🟡 |
| 14 | QR Code | Mobile pe scan karke download | 🟡 |

---

## ⚙️ BACKEND — MUST HAVE

| # | Item | Kaam | Scope |
|---|------|------|-------|
| 1 | POST /api/download | Download start karne ke liye | ✅ |
| 2 | GET /api/status/{task_id} | Progress check karne ke liye | ✅ |
| 3 | GET /api/file/{task_id} | File serve karne ke liye | ✅ |
| 4 | URL Validator | Sirf 6 supported platforms ke hosts accept kare | ✅ |
| 5 | yt-dlp Integration | Actual download engine | ✅ |
| 6 | aria2c Integration | 16 parallel connections | ✅ |
| 7 | FFmpeg Setup | Video + audio merge | ✅ |
| 8 | ARQ + Redis | Background task queue | ✅ |
| 9 | File Storage Folder | Downloaded files save | ✅ |
| 10 | Task ID Generator | Har download ka unique ID | ✅ |
| 11 | Error Handling | Failed downloads gracefully | ✅ |
| 12 | CORS Setup | Frontend se request allow | ✅ |
| 13 | Pydantic Validation | Type-safe input check | ✅ |
| 14 | Basic Logging | Kya hua, kab hua | ✅ |
| 15 | Format Selection Logic | Quality + format combination | ✅ |
| 16 | Bot Bypass (TV client) | YouTube block se bachne ke liye | ⛔ |
| 17 | Gunicorn + Uvicorn | Production server | ✅ |
| 18 | Docker Compose | One-command deployment | ✅ |

## 🎁 BACKEND — OPTIONAL

| # | Item | Fayda | Scope |
|---|------|-------|-------|
| 1 | Database (SQLite/Postgres) | Download history, task records | 🟡 |
| 2 | Rate Limiting | Abuse rokne ke liye | 🟡 |
| 3 | User Authentication (JWT) | Private downloads | 🟡 |
| 4 | File Cleanup Cron | 24hr baad auto-delete | ✅ |
| 5 | WebSocket Server | Live progress (better than polling) | 🟡 |
| 6 | Advanced Logging | Structured logs, rotation | 🟡 |
| 7 | Nginx Reverse Proxy | SSL, load balancing | ✅ |
| 8 | CDN Integration | Fast file delivery | 🟡 |
| 9 | Monitoring (Sentry) | Errors auto-track | 🟡 |
| 10 | Metrics (Prometheus) | Performance stats | 🟡 |
| 11 | Cookies Support | Age-restricted videos | ⛔ |
| 12 | Proxy Rotation | IP block se bachne ke liye | ⛔ |
| 13 | Playlist Support | Poori playlist download | 🟡 |
| 14 | Subtitle Download | .srt files bhi mile | 🟡 |
| 15 | Retry Logic | 3 baar try kare fail hone pe | ✅ |
| 16 | Health Check /health | Server alive hai? | ✅ |
| 17 | BGutil PO Token Provider | YouTube bot bypass (advanced) | ⛔ |
| 18 | Residential Proxy | Bulletproof IP trust | ⛔ |

---

## 📄 LEGAL PAGES — MUST HAVE

| # | Page | AdSense Requirement | Scope |
|---|------|---------------------|-------|
| 1 | Privacy Policy | Google AdSense + Cookies mention | ✅ |
| 2 | Terms & Conditions | User responsibility, liability | ✅ |
| 3 | About Us | Who you are, what site does | ✅ |
| 4 | Contact Us | Working email + contact form | ✅ |
| 5 | DMCA Policy | Copyright takedown process | ✅ |
| 6 | Disclaimer | No affiliation with YouTube | ✅ |
| 7 | FAQ | Common questions | ✅ |
| 8 | Footer Links | Saare legal pages ke links | ✅ |

## 🎁 LEGAL PAGES — OPTIONAL

| # | Page | Fayda | Scope |
|---|------|-------|-------|
| 1 | Cookie Policy | Separate cookies detail | 🟡 |
| 2 | GDPR Compliance | EU users ke liye | 🟡 |
| 3 | Refund Policy | Agar paid plans ho | 🟡 |
| 4 | Blog | SEO + AdSense approval | 🟡 |
| 5 | Sitemap | Search engines ke liye | 🟡 |
| 6 | robots.txt | Crawler instructions | 🟡 |
| 7 | Accessibility Statement | Disabled users ke liye | 🟡 |

---

## 🔧 GITHUB — MUST HAVE

| # | Item | Kaam | Scope |
|---|------|------|-------|
| 1 | README.md | Project documentation | ✅ |
| 2 | .gitignore | Sensitive files block | ✅ |
| 3 | LICENSE | MIT or GPL-3.0 | ✅ |
| 4 | frontend/ folder | Static files | ✅ |
| 5 | backend/ folder | FastAPI app | ✅ |
| 6 | requirements.txt | Python dependencies | ✅ |
| 7 | Dockerfile | Container setup | ✅ |
| 8 | docker-compose.yml | Multi-service deploy | ✅ |
| 9 | .env.example | Config template | ✅ |
| 10 | nginx/nginx.conf | Reverse proxy config | ✅ |

## 🎁 GITHUB — OPTIONAL

| # | Item | Fayda | Scope |
|---|------|-------|-------|
| 1 | .github/workflows/ | CI/CD auto-deploy | ✅ |
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
