"""ASGI entrypoint that serves the API and the static frontend from one app.

docker-compose puts nginx in front of the API, so there `app.main:app` stays the
entrypoint and this module is unused. A single-service host has no nginx, so
without this the frontend would never be served and the site root would return
404. Mounting StaticFiles at "/" reuses the same origin the API already serves,
so the frontend's relative "/api/*" and "/ws/*" calls keep working unchanged.

The screenshot intake service is mounted at /shots on the same port, because a
single-service host gives one port. It is disabled unless SCREENSHOT_TOKEN is
set: the routes it exposes accept uploads and read back stored ones, so an
unguarded instance on a public host is an open drop box.

Both mounts are added after the API routes, and Starlette matches routes in
order, so "/api/*", "/docs" and "/ws/*" are unaffected. /shots is added before
the catch-all "/" mount for the same reason.
"""

import os
from pathlib import Path

from fastapi.staticfiles import StaticFiles

from app.main import app

FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"

SCREENSHOT_TOKEN = os.environ.get("SCREENSHOT_TOKEN", "").strip()
if SCREENSHOT_TOKEN:
    from screenshot_server import create_app as create_screenshot_app

    app.mount("/shots", create_screenshot_app(token=SCREENSHOT_TOKEN))

app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

