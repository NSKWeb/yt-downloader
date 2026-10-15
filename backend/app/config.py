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

    # CORS origins for the frontend (comma separated).
    cors_origins: str = "*"

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
