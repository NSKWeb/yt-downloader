"""yt-dlp command construction and execution.

The download pipeline is deliberately plain: build an argument list, run it,
parse yt-dlp's progress lines, hand the resulting file back to the caller.

Notes on what is intentionally absent:
  * No Proof-of-Origin token provider and no `player_client` spoofing. Those
    exist to defeat YouTube's bot detection rather than to download as an
    ordinary client would, so they are out of scope.
  * No proxy rotation.
Requests are made as a normal client. If YouTube rate-limits a datacenter IP,
that is a hosting decision, not something this module works around.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import sys
from pathlib import Path
from typing import Awaitable, Callable, Optional

from .config import settings
from .platforms import PLATFORMS

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict], Awaitable[None] | None]

# Invoke yt-dlp through the running interpreter rather than the console script,
# so it always resolves to the same environment the app was installed into.
YTDLP = [sys.executable, "-m", "yt_dlp"]

_PROGRESS_RE = re.compile(
    r"\[download\]\s+(?P<pct>[\d.]+)%"
    r"(?:\s+of\s+~?\s*(?P<size>[\d.]+\w+))?"
    r"(?:\s+at\s+(?P<speed>[\d.]+\w+/s))?"
    r"(?:\s+ETA\s+(?P<eta>[\d:]+))?"
)

# aria2c renders its own progress bar, and those lines can push the actual
# error out of the captured tail. Drop them so the message we surface is the
# one yt-dlp or the extractor actually produced.
_ARIA2_PROGRESS_RE = re.compile(r"\[#[0-9a-f]+\s")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _meaningful_error(lines: list[str]) -> str:
    """Pick the lines that explain a failure, ignoring transfer chatter."""
    cleaned = []
    for raw in lines:
        line = _ANSI_RE.sub("", raw).strip()
        if not line or _ARIA2_PROGRESS_RE.search(line):
            continue
        cleaned.append(line)
    if not cleaned:
        return "unknown error"
    # Prefer lines that look like the cause; otherwise keep the last few.
    errors = [ln for ln in cleaned if "ERROR" in ln or "error" in ln]
    chosen = errors[:3] if errors else cleaned[-8:]
    return "\n".join(chosen)[:600]


def build_format_selector(mode: str, quality: str, platform_key: str = "youtube") -> str:
    """Return the yt-dlp -f expression for the requested mode and quality.

    The selector is intentionally conservative: `bestvideo+bestaudio` only
    applies where a platform actually publishes separate streams. Elsewhere we
    fall back to a plain `best`, which is correct for the single-file MP4s that
    short-form platforms serve.
    """
    platform = PLATFORMS.get(platform_key)

    if mode == "image":
        return "best"

    if mode == "audio":
        return "bestaudio/best"

    # Only YouTube reliably exposes split video/audio tracks.
    if platform is None or platform.key != "youtube":
        if quality == "best":
            return "best"
        height = quality.removesuffix("p")
        return f"best[height<={height}]/best"

    if quality == "best":
        return "bestvideo+bestaudio/best"
    height = quality.removesuffix("p")
    return f"bestvideo[height<={height}]+bestaudio/best[height<={height}]"


def audio_quality_arg(audio_quality: str) -> str:
    """Translate a kbps target into yt-dlp's --audio-quality value.

    yt-dlp accepts a bitrate like `192K` or a VBR grade from 0 (best) to 9
    (worst). `best` maps to VBR 0, which keeps the source quality.
    """
    value = (audio_quality or "").strip().lower()
    if value in ("", "best"):
        return "0"
    return f"{value}K"


def build_command(
    url: str,
    mode: str,
    quality: str,
    audio_format: str,
    output_dir: Path,
    platform_key: str = "youtube",
    playlist: bool = False,
    subtitles: bool = False,
    audio_quality: str = "192",
) -> list[str]:
    """Assemble the yt-dlp argv for one job."""
    outtmpl = str(output_dir / "%(title).150B [%(id)s].%(ext)s")
    cmd: list[str] = [
        *YTDLP,
        "--no-warnings",
        "--newline",
        "--progress",
        "--retries", str(settings.retries),
        "--socket-timeout", str(settings.socket_timeout),
        "--print", "after_move:filepath",
        # Emitted before the download starts so the UI can show a title and a
        # size estimate while the transfer is still running. The unit separator
        # keeps titles containing spaces or tabs parseable.
        "--print", "before_dl:__META__%(title)s\x1f%(filesize,filesize_approx)s",
        "-o", outtmpl,
    ]

    # --no-playlist is the safe default: a watch URL carrying a &list= parameter
    # should still fetch one video. Playlist mode opts in explicitly.
    if playlist:
        cmd.append("--yes-playlist")
    else:
        cmd.append("--no-playlist")

    if subtitles:
        cmd += [
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs", "en.*",
            "--convert-subs", "srt",
        ]

    if mode == "image":
        cmd += ["-f", "best"]
    elif mode == "audio":
        cmd += [
            "-f", build_format_selector(mode, quality, platform_key),
            "--extract-audio",
            "--audio-format", audio_format,
            "--audio-quality", audio_quality_arg(audio_quality),
        ]
    else:
        cmd += [
            "-f", build_format_selector(mode, quality, platform_key),
            "--merge-output-format", "mp4",
        ]

    # Multi-connection acceleration. aria2c only helps when yt-dlp is fetching
    # a single direct media stream; it is a no-op for segmented (m3u8/DASH)
    # downloads, which yt-dlp handles natively.
    #
    # The timeout and retry options matter: aria2c's defaults are far less
    # forgiving than yt-dlp's, and a host that is slow to start a TLS handshake
    # makes it abort a transfer that yt-dlp would have completed. Console
    # output is quieted because its progress bar drowns out real errors.
    if shutil.which("aria2c"):
        aria2_args = (
            f"aria2c:-x {settings.aria2c_connections} "
            f"-s {settings.aria2c_split} "
            f"-k {settings.aria2c_min_split_size} "
            f"--connect-timeout={settings.aria2c_connect_timeout} "
            f"--timeout={settings.aria2c_timeout} "
            f"--max-tries={settings.retries} "
            "--retry-wait=3 "
            "--lowest-speed-limit=0 "
            "--file-allocation=none "
            "--summary-interval=0 "
            "--console-log-level=warn"
        )
        cmd += [
            "--downloader", "aria2c",
            "--downloader-args", aria2_args,
        ]

    cmd.append(url)
    return cmd


def _parse_progress_line(line: str) -> Optional[dict]:
    match = _PROGRESS_RE.search(line)
    if not match:
        return None
    data: dict = {"percent": float(match.group("pct"))}
    if match.group("size"):
        data["total"] = match.group("size")
    if match.group("speed"):
        data["speed"] = match.group("speed")
    if match.group("eta"):
        data["eta"] = match.group("eta")
    return data


async def run_download(
    url: str,
    mode: str,
    quality: str,
    audio_format: str,
    output_dir: Path,
    on_progress: ProgressCallback | None = None,
    on_meta: Callable[[dict], Awaitable[None] | None] | None = None,
    platform_key: str = "youtube",
    playlist: bool = False,
    subtitles: bool = False,
    audio_quality: str = "192",
) -> Path:
    """Run yt-dlp and return the path to the finished file.

    Raises RuntimeError with yt-dlp's own message on failure.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = build_command(
        url,
        mode,
        quality,
        audio_format,
        output_dir,
        platform_key,
        playlist=playlist,
        subtitles=subtitles,
        audio_quality=audio_quality,
    )
    logger.info("starting download: %s", " ".join(cmd[:-1]) + " <url>")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    final_path: str | None = None
    tail: list[str] = []

    assert proc.stdout is not None
    async for raw in proc.stdout:
        line = raw.decode("utf-8", errors="replace").rstrip()
        if not line:
            continue
        tail.append(line)
        if len(tail) > 40:
            tail.pop(0)

        progress = _parse_progress_line(line)
        if progress and on_progress:
            result = on_progress(progress)
            if asyncio.iscoroutine(result):
                await result
            continue

        # Metadata line, emitted once before the transfer begins.
        if line.startswith("__META__") and on_meta:
            payload = line[len("__META__"):]
            title, _, raw_size = payload.partition("\x1f")
            size: int | None = None
            if raw_size.strip().isdigit():
                size = int(raw_size.strip())
            result = on_meta({"title": title or None, "filesize": size})
            if asyncio.iscoroutine(result):
                await result
            continue

        # yt-dlp emits metadata JSON when --print is combined with a template
        # that returns a dict; we use the simpler filepath print instead, and
        # capture any absolute path line as the finished artefact.
        if line.startswith("/") and Path(line).suffix:
            final_path = line

        if on_meta and line.startswith("{"):
            try:
                result = on_meta(json.loads(line))
                if asyncio.iscoroutine(result):
                    await result
            except json.JSONDecodeError:
                pass

    returncode = await proc.wait()
    if returncode != 0:
        raise RuntimeError("yt-dlp failed: " + _meaningful_error(tail))

    if final_path and Path(final_path).exists():
        return Path(final_path)

    # Fall back to the newest file in the output directory.
    candidates = sorted(
        (p for p in output_dir.iterdir() if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise RuntimeError("yt-dlp reported success but produced no file")
    return candidates[0]


async def probe_info(url: str) -> dict:
    """Fetch metadata without downloading. Returns {} on failure."""
    cmd = [
        *YTDLP,
        "--no-playlist",
        "--no-warnings",
        "--skip-download",
        "--dump-single-json",
        url,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return {}
    try:
        return json.loads(stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {}
