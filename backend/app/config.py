"""Application settings, loaded from the environment."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # yt-dlp / aria2c tuning
    aria2c_connections: int = 16
    aria2c_split: int = 16
    aria2c_min_split_size: str = "1M"
    socket_timeout: int = 30
    retries: int = 5

    # Limits
    max_concurrent_jobs: int = 2
    max_duration_seconds: int = 4 * 60 * 60

    # Rate limiting (sliding window, per client IP)
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 10
    rate_limit_per_hour: int = 100

    # Download history (SQLite). Left unset, the database lives beside the
    # downloads so that overriding download_dir does not silently break history.
    history_enabled: bool = True
    database_path: Path | None = None

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


settings = Settings()
