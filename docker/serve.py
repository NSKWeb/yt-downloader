"""ASGI entrypoint that serves the API and the static frontend from one app.

docker-compose puts nginx in front of the API, so there `app.main:app` stays the
entrypoint and this module is unused. A single-service host has no nginx, so
without this the frontend would never be served and the site root would return
404. Mounting StaticFiles at "/" reuses the same origin the API already serves,
so the frontend's relative "/api/*" and "/ws/*" calls keep working unchanged.

The mount is added after the API routes, and Starlette matches routes in order,
so "/api/*", "/docs" and "/ws/*" are unaffected.
"""

from pathlib import Path

from fastapi.staticfiles import StaticFiles

from app.main import app

FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"

app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
