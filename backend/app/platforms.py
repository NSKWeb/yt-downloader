"""Platform registry.

Each supported site is described declaratively. Adding a platform means adding
one entry here; URL validation, the options offered to the frontend, the
subdomain routing, and the yt-dlp format selector all read from this registry.

Scope note, stated plainly because it shapes the whole module: every platform
here targets PUBLIC content. None of them authenticate. There is no cookie
jar, no session login, no bearer token, and no region spoofing. Where a
platform gates most of its content behind a login, that is recorded in
`public_content_limited` so the UI can warn the user honestly instead of
failing mysteriously.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit

# Quality ladder for platforms that publish height-based video streams.
STANDARD_VIDEO_QUALITIES = [
    "360p",
    "480p",
    "720p",
    "1080p",
    "1440p",
    "2160p",
    "4320p",
    "best",
]

STANDARD_AUDIO_FORMATS = ["mp3", "m4a", "wav", "flac", "opus", "aac", "ogg"]

# Short-form platforms rarely publish above 1080p; offering 4K/8K there would
# only produce confusing silent fallbacks.
SHORT_FORM_QUALITIES = ["360p", "480p", "720p", "1080p", "best"]

# Image-first platforms.
IMAGE_FORMATS = ["jpg", "png", "webp"]

# Audio bitrate targets, in kbps. "best" keeps the source bitrate.
AUDIO_QUALITIES = ["128", "192", "256", "320", "best"]


@dataclass(frozen=True)
class Platform:
    key: str
    name: str
    hosts: tuple[str, ...]
    # Legal attribution shown in the per-platform disclaimer.
    owner: str
    video_qualities: list[str] = field(default_factory=lambda: list(STANDARD_VIDEO_QUALITIES))
    audio_formats: list[str] = field(default_factory=lambda: list(STANDARD_AUDIO_FORMATS))
    supports_video: bool = True
    supports_audio: bool = True
    supports_images: bool = False
    image_formats: list[str] = field(default_factory=list)
    # True where the platform gates most content behind a login we do not do.
    public_content_limited: bool = False
    # Playlists are a YouTube concept; only it advertises the capability.
    supports_playlists: bool = False
    supports_subtitles: bool = False
    note: str = ""

    @property
    def default_quality(self) -> str:
        return "best" if "best" in self.video_qualities else self.video_qualities[0]


PLATFORMS: dict[str, Platform] = {
    "youtube": Platform(
        key="youtube",
        name="YouTube",
        owner="YouTube or Google LLC",
        hosts=(
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "music.youtube.com",
            "youtu.be",
            "www.youtu.be",
        ),
        supports_playlists=True,
        supports_subtitles=True,
    ),
    "instagram": Platform(
        key="instagram",
        name="Instagram",
        owner="Instagram or Meta Platforms, Inc.",
        hosts=("instagram.com", "www.instagram.com", "m.instagram.com"),
        video_qualities=list(SHORT_FORM_QUALITIES),
        public_content_limited=True,
        note=(
            "Public posts and reels only. Instagram requires a login for most "
            "content, and this service does not authenticate, so many links "
            "will not work."
        ),
    ),
    "facebook": Platform(
        key="facebook",
        name="Facebook",
        owner="Facebook or Meta Platforms, Inc.",
        hosts=(
            "facebook.com",
            "www.facebook.com",
            "m.facebook.com",
            "web.facebook.com",
            "fb.watch",
        ),
        video_qualities=list(SHORT_FORM_QUALITIES),
        public_content_limited=True,
        note=(
            "Public videos and reels only. Private videos and stories need a "
            "login, which this service does not do."
        ),
    ),
    "twitter": Platform(
        key="twitter",
        name="X (Twitter)",
        owner="X Corp. or Twitter, Inc.",
        hosts=(
            "twitter.com",
            "www.twitter.com",
            "mobile.twitter.com",
            "x.com",
            "www.x.com",
        ),
        video_qualities=list(SHORT_FORM_QUALITIES),
    ),
    "pinterest": Platform(
        key="pinterest",
        name="Pinterest",
        owner="Pinterest, Inc.",
        hosts=(
            "pinterest.com",
            "www.pinterest.com",
            "pinterest.co.uk",
            "pin.it",
        ),
        video_qualities=list(SHORT_FORM_QUALITIES),
        supports_images=True,
        image_formats=list(IMAGE_FORMATS),
        note="Public pins and boards only.",
    ),
    "tiktok": Platform(
        key="tiktok",
        name="TikTok",
        owner="TikTok or ByteDance Ltd.",
        hosts=("tiktok.com", "www.tiktok.com", "m.tiktok.com", "vm.tiktok.com"),
        video_qualities=list(SHORT_FORM_QUALITIES),
    ),
}


def _host_from_url(url: str) -> str:
    """Extract a bare hostname: lowercased, no port, no userinfo, no path.

    This must agree with what the HTTP client downstream will actually fetch,
    so it parses rather than pattern-matches. Two shapes made the old
    split-then-rsplit("@") version disagree with every real client:

      * `http://127.0.0.1:12346#@youtube.com` — the "@youtube.com" sits in the
        fragment, so rsplit("@") returned `youtube.com` while yt-dlp fetched
        127.0.0.1. Stripping the fragment first fixes it.
      * `http://127.0.0.1:12346\\@youtube.com` — browsers and several HTTP
        clients treat a backslash as a path separator, but the old code read
        everything after "@" as the authority. A backslash is never valid in a
        URL authority, so such input is rejected outright.

    Anything that does not parse into a hostname returns "", which never
    matches the allowlist.
    """
    candidate = (url or "").strip()
    if "\\" in candidate:
        return ""

    # The fragment is client-side only and must not influence host detection.
    candidate = candidate.split("#", 1)[0]

    # urlsplit only fills in netloc when a scheme is present. Add the
    # scheme-relative prefix for bare input like "youtube.com/watch?v=x".
    if "//" not in candidate.split("?", 1)[0]:
        candidate = "//" + candidate

    try:
        host = urlsplit(candidate).hostname
    except ValueError:
        return ""
    return (host or "").lower()


def detect_platform(url: str) -> Platform | None:
    """Return the Platform for a URL, or None if the host is not supported.

    Matching is exact against the declared host set, never a suffix match:
    `youtube.com.evil.com` ends with `youtube.com` and must not pass.
    """
    host = _host_from_url(url)
    for platform in PLATFORMS.values():
        if host in platform.hosts:
            return platform
    return None


def platform_for_subdomain(host_header: str) -> Platform | None:
    """Resolve a platform from a Host header such as `tiktok.example.com`."""
    host = (host_header or "").split(":")[0].lower()
    label = host.split(".")[0]
    return PLATFORMS.get(label)


def supported_hosts() -> set[str]:
    hosts: set[str] = set()
    for platform in PLATFORMS.values():
        hosts.update(platform.hosts)
    return hosts


def platform_catalog() -> list[dict]:
    """Serialisable registry, served to the frontend."""
    return [
        {
            "key": p.key,
            "name": p.name,
            "owner": p.owner,
            "hosts": list(p.hosts),
            "video_qualities": p.video_qualities,
            "audio_formats": p.audio_formats,
            "image_formats": p.image_formats,
            "supports_video": p.supports_video,
            "supports_audio": p.supports_audio,
            "supports_images": p.supports_images,
            "supports_playlists": p.supports_playlists,
            "supports_subtitles": p.supports_subtitles,
            "public_content_limited": p.public_content_limited,
            "note": p.note,
        }
        for p in PLATFORMS.values()
    ]
