"""Request/response schemas and the job state model."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, field_validator

VIDEO_QUALITIES = ["360p", "480p", "720p", "1080p", "1440p", "2160p", "4320p", "best"]
AUDIO_FORMATS = ["mp3", "m4a", "wav", "flac", "opus", "aac", "ogg"]

_YOUTUBE_HOSTS = (
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
)


class JobStatus(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


class JobState(BaseModel):
    task_id: str
    url: str
    mode: str
    quality: str
    audio_format: str | None = None
    status: JobStatus = JobStatus.QUEUED
    progress: float = 0.0
    speed: str | None = None
    eta: str | None = None
    title: str | None = None
    filename: str | None = None
    filesize: int | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DownloadRequest(BaseModel):
    url: str
    mode: str = "video"
    quality: str = "best"
    audio_format: str = "mp3"

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("URL is required")
        if not re.match(r"^https?://", v, re.IGNORECASE):
            raise ValueError("URL must start with http:// or https://")
        # Only accept the supported host set; anything else is rejected before
        # it ever reaches the download engine.
        host = re.sub(r"^https?://", "", v, flags=re.IGNORECASE).split("/")[0].lower()
        host = host.split(":")[0]
        if host not in _YOUTUBE_HOSTS:
            raise ValueError(f"Unsupported host: {host}")
        return v

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in ("video", "audio"):
            raise ValueError("mode must be 'video' or 'audio'")
        return v

    @field_validator("quality")
    @classmethod
    def validate_quality(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in VIDEO_QUALITIES:
            raise ValueError(f"quality must be one of {', '.join(VIDEO_QUALITIES)}")
        return v

    @field_validator("audio_format")
    @classmethod
    def validate_audio_format(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in AUDIO_FORMATS:
            raise ValueError(f"audio_format must be one of {', '.join(AUDIO_FORMATS)}")
        return v


class DownloadResponse(BaseModel):
    task_id: str
    status: JobStatus


class StatusResponse(BaseModel):
    task_id: str
    status: JobStatus
    progress: float
    speed: str | None = None
    eta: str | None = None
    title: str | None = None
    filesize: int | None = None
    error: str | None = None


class InfoResponse(BaseModel):
    title: str | None = None
    uploader: str | None = None
    duration: int | None = None
    thumbnail: str | None = None
    webpage_url: str | None = None
    formats_available: list[str] = Field(default_factory=list)
