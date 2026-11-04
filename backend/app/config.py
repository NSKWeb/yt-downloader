"""Application settings, loaded from the environment."""

from __future__ import annotations

import atexit
import logging
import tempfile
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Storage
    download_dir: Path = Path("/downloads")
    # Downloaded files are deleted this many seconds after they are last touched.
    file_ttl_seconds: int = 3600

    # Queue
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_database: int = 0

    # yt-dlp authentication. YouTube, and sometimes X/Twitter, refuse requests
    # from datacenter IP ranges unless the request carries a logged-in session.
    # Set this to a Netscape-format cookies.txt exported from a browser, either
    # as a path to an existing file or as the file's contents (for hosts that
    # cannot mount a file). Empty sends no cookies, which is the default.
    ytdlp_cookies: str = ""

    # yt-dlp / aria2c tuning
    aria2c_connections: int = 16
    aria2c_split: int = 16
    aria2c_min_split_size: str = "1M"
    # aria2c's own defaults are stricter than yt-dlp's and abort transfers on
    # hosts that are slow to start a TLS handshake. These are deliberately
    # generous so aria2c does not fail where yt-dlp would have succeeded.
    aria2c_connect_timeout: int = 60
    aria2c_timeout: int = 60
    socket_timeout: int = 30
    retries: int = 5

    # Limits
    max_concurrent_jobs: int = 2
    max_duration_seconds: int = 4 * 60 * 60

    # Rate limiting (sliding window, per client IP)
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 10
    rate_limit_per_hour: int = 100
    # Comma-separated CIDRs of reverse proxies whose X-Forwarded-For may be
    # trusted. Empty means "trust loopback and private peers only", which is
    # correct when the API is not itself reachable from the internet.
    trusted_proxies: str = ""

    # Download history (SQLite). Left unset, the database lives beside the
    # downloads so that overriding download_dir does not silently break history.
    history_enabled: bool = True
    database_path: Path | None = None
    # Retention for the history table, applied by the hourly cleanup job. Rows
    # older than the age cap, or beyond the row cap, are deleted. Without this
    # the table grows without bound: every finished job appends a row and
    # nothing ever removes one.
    history_retention_days: int = 30
    history_max_rows: int = 5000

    # WebSocket progress streaming
    ws_poll_interval: float = 0.5
    ws_max_updates: int = 3600

    # CORS origins for the frontend (comma separated).
    cors_origins: str = "*"

    # Comma-separated list of platform subdomains, used for documentation and
    # for building absolute links. Purely cosmetic; access is controlled by the
    # URL allowlist, never by the Host header.
    platform_subdomains: str = "youtube,instagram,facebook,twitter,pinterest,tiktok"

    @property
    def platform_subdomain_list(self) -> list[str]:
        return [p.strip() for p in self.platform_subdomains.split(",") if p.strip()]

    @property
    def trusted_proxy_list(self) -> list[str]:
        return [p.strip() for p in self.trusted_proxies.split(",") if p.strip()]

    @property
    def history_db_path(self) -> Path:
        """Where the SQLite history lives, defaulting to the download directory."""
        return self.database_path or (self.download_dir / "history.db")

    @property
    def redis_settings(self):
        from arq.connections import RedisSettings

        return RedisSettings(
            host=self.redis_host,
            port=self.redis_port,
            database=self.redis_database,
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def cookies_file(self) -> Path | None:
        """Path to a Netscape-format cookies file, or None to send no cookies.

        `ytdlp_cookies` may be a path to an existing file, or the file's
        contents. Contents are written to a temp file because yt-dlp only reads
        cookies from a path; an unreadable path is ignored rather than passed
        through, so a typo does not break every download.
        """
        return _resolve_cookies(self.ytdlp_cookies)


@lru_cache(maxsize=8)
def _resolve_cookies(value: str) -> Path | None:
    """Turn a YTDLP_COOKIES value into a path once, then reuse it.

    Cached because every download and probe asks for it, and the contents form
    would otherwise write a new temp file per request.
    """
    value = _clean_cookies_value(value)
    if not value:
        return None
    candidate = Path(value)
    if "\n" not in value and candidate.is_file():
        return candidate
    if "# Netscape HTTP Cookie File" not in value and "\t" not in value:
        logger.warning("YTDLP_COOKIES is set but is not a file or cookies.txt content")
        return None
    if not value.endswith("\n"):
        value += "\n"
    with tempfile.NamedTemporaryFile(
        "w", suffix=".txt", prefix="ytdlp-cookies-", delete=False
    ) as handle:
        handle.write(value)
        name = handle.name
    atexit.register(_unlink_quietly, name)
    return Path(name)


def _clean_cookies_value(value: str) -> str:
    """Remove the artefacts a copy-paste into an env field picks up.

    A value pasted from a shell or an editor can arrive wrapped in quotes, with
    a UTF-8 BOM in front, or indented on every line. yt-dlp rejects each of
    those with "Cookies file must be Netscape formatted, not JSON", which names
    neither the file nor the real problem, so the fix is to strip them here.
    """
    value = value.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    value = value.strip()
    # A single pair of matching quotes around the whole value, from a paste
    # like YTDLP_COOKIES='...'. Only the outer pair is removed: a quote inside
    # a cookie value is data.
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    if "\n" not in value:
        return value.strip()
    # The header must start the file and every row must start a line, so drop
    # per-line indentation and blank padding that a paste can introduce.
    lines = [line.strip() for line in value.split("\n")]
    return "\n".join(lines).strip()


def _unlink_quietly(path: str) -> None:
    try:
        Path(path).unlink()
    except OSError:
        pass


settings = Settings()
