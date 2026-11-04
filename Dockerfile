# Root Dockerfile for single-service hosts (e.g. ZopCloud), which build from the
# repository root and run one container. The application lives in backend/, so
# the build context stays at the root and every COPY is prefixed with backend/.
# docker-compose.yml keeps using backend/Dockerfile, which is unchanged.
#
# This container also serves the static frontend (frontend/) so the site root
# works without the nginx that docker-compose provides. The API is served
# through docker/serve.py, which mounts the frontend at "/".
#
# tesseract-ocr, pillow and pytesseract are here for the screenshot intake
# service (tools/screenshot_server.py), which docker/serve.py mounts at /shots
# when SCREENSHOT_TOKEN is set. They add roughly 30 MB; drop them and the
# service reports ocr:false instead of failing, but screenshots then upload
# without their text.

FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        aria2 \
        ca-certificates \
        redis-server \
        tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir pillow pytesseract

COPY backend/app ./app
COPY frontend ./frontend
COPY tools/screenshot_server.py ./screenshot_server.py
COPY docker/serve.py ./serve.py
COPY docker/start.sh /usr/local/bin/start.sh

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /downloads /var/lib/screenshots \
    && chown -R app:app /downloads /app /var/lib/screenshots \
    && chmod 0755 /usr/local/bin/start.sh

USER app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DOWNLOAD_DIR=/downloads \
    SCREENSHOT_DIR=/var/lib/screenshots \
    REDIS_HOST=redis \
    REDIS_PORT=6379 \
    PORT=8000

EXPOSE 8000

# Runs the API and the ARQ worker in one container. If REDIS_HOST is not
# reachable, a local redis-server is started so the container is self-contained.
CMD ["/usr/local/bin/start.sh"]
