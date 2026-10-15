"""Request/response schemas and the job state model."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

from .platforms import AUDIO_QUALITIES, detect_platform


class JobStatus(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


class JobState(BaseModel):
    task_id: str
    url: str
    platform: str = "youtube"
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
    audio_quality: str = "192"
    playlist: bool = False
    subtitles: bool = False

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("URL is required")
        if not re.match(r"^https?://", v, re.IGNORECASE):
            raise ValueError("URL must start with http:// or https://")
        # Resolve against the platform allowlist before anything else touches
        # the URL. An unknown host is rejected here, so it never reaches the
        # download engine.
        if detect_platform(v) is None:
            from .platforms import supported_hosts

            raise ValueError(
                "Unsupported host. Supported: " + ", ".join(sorted(supported_hosts()))
            )
        return v

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in ("video", "audio", "image"):
            raise ValueError("mode must be 'video', 'audio', or 'image'")
        return v

    @model_validator(mode="after")
    def validate_against_platform(self) -> "DownloadRequest":
        """Check mode, quality, and format against what the platform offers."""
        platform = detect_platform(self.url)
        if platform is None:  # already rejected by validate_url
            return self

        if self.mode == "video" and not platform.supports_video:
            raise ValueError(f"{platform.name} does not support video downloads")
        if self.mode == "audio" and not platform.supports_audio:
            raise ValueError(f"{platform.name} does not support audio downloads")
        if self.mode == "image" and not platform.supports_images:
            raise ValueError(f"{platform.name} does not support image downloads")

        if self.mode == "video":
            self.quality = self.quality.strip().lower()
            if self.quality not in platform.video_qualities:
                raise ValueError(
                    f"quality for {platform.name} must be one of "
                    + ", ".join(platform.video_qualities)
                )
        elif self.mode == "image":
            # Images have no quality ladder; the field is ignored downstream.
            self.quality = "best"
        else:
            self.audio_format = self.audio_format.strip().lower()
            if self.audio_format not in platform.audio_formats:
                raise ValueError(
                    f"audio_format for {platform.name} must be one of "
                    + ", ".join(platform.audio_formats)
                )

        self.audio_quality = self.audio_quality.strip()
        if self.audio_quality not in AUDIO_QUALITIES:
            raise ValueError(f"audio_quality must be one of {', '.join(AUDIO_QUALITIES)}")

        # Playlists and subtitles are YouTube concepts; elsewhere they are
        # silently ignored rather than rejected, since a user may paste a link
        # that happens to carry a list parameter.
        if self.playlist and not platform.supports_playlists:
            raise ValueError(f"{platform.name} does not support playlist downloads")
        if self.subtitles and not platform.supports_subtitles:
            raise ValueError(f"{platform.name} does not support subtitle downloads")

        return self


class DownloadResponse(BaseModel):
    task_id: str
    status: JobStatus


class StatusResponse(BaseModel):
    task_id: str
    platform: str = "youtube"
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
    # yt-dlp reports duration as a float (74.304 for a 74-second clip), and
    # returns the string "NA" when it cannot determine one. Truncate to whole
    # seconds rather than letting either reach the client as a validation error.
    duration: int | None = None
    thumbnail: str | None = None
    webpage_url: str | None = None
    formats_available: list[str] = Field(default_factory=list)

    @field_validator("duration", mode="before")
    @classmethod
    def _coerce_duration(cls, value):
        if value is None:
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None
