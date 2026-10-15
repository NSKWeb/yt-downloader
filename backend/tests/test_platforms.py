"""Tests for the platform registry: detection, validation, and the SSRF guard."""

import pytest

from app.models import DownloadRequest
from app.platforms import (
    PLATFORMS,
    detect_platform,
    platform_catalog,
    platform_for_subdomain,
    supported_hosts,
)

EXPECTED_PLATFORMS = {"youtube", "instagram", "facebook", "twitter", "pinterest", "tiktok"}


class TestRegistry:
    def test_all_planned_platforms_registered(self):
        assert set(PLATFORMS) == EXPECTED_PLATFORMS

    def test_every_platform_has_hosts_and_owner(self):
        for key, platform in PLATFORMS.items():
            assert platform.hosts, f"{key} has no hosts"
            assert platform.owner, f"{key} has no owner attribution"
            assert platform.key == key

    def test_catalog_is_json_serialisable(self):
        import json

        catalog = platform_catalog()
        assert len(catalog) == len(PLATFORMS)
        json.dumps(catalog)  # must not raise

    def test_pinterest_advertises_images(self):
        assert PLATFORMS["pinterest"].supports_images
        assert "jpg" in PLATFORMS["pinterest"].image_formats

    def test_short_form_platforms_do_not_offer_8k(self):
        for key in ("instagram", "facebook", "twitter", "pinterest", "tiktok"):
            assert "4320p" not in PLATFORMS[key].video_qualities

    def test_login_limited_platforms_are_flagged(self):
        assert PLATFORMS["instagram"].public_content_limited
        assert PLATFORMS["facebook"].public_content_limited
        assert not PLATFORMS["youtube"].public_content_limited


class TestDetection:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://www.youtube.com/watch?v=x", "youtube"),
            ("https://youtu.be/x", "youtube"),
            ("https://www.instagram.com/reel/abc/", "instagram"),
            ("https://www.facebook.com/watch/?v=1", "facebook"),
            ("https://fb.watch/abc/", "facebook"),
            ("https://x.com/user/status/1", "twitter"),
            ("https://twitter.com/user/status/1", "twitter"),
            ("https://www.pinterest.com/pin/1/", "pinterest"),
            ("https://pin.it/abc", "pinterest"),
            ("https://www.tiktok.com/@user/video/1", "tiktok"),
            ("https://vm.tiktok.com/abc/", "tiktok"),
        ],
    )
    def test_detects_platform(self, url, expected):
        platform = detect_platform(url)
        assert platform is not None
        assert platform.key == expected

    @pytest.mark.parametrize(
        "url",
        [
            "https://vimeo.com/12345",
            "https://evil.com/",
            "https://notyoutube.com/watch?v=x",
        ],
    )
    def test_unknown_host_returns_none(self, url):
        assert detect_platform(url) is None

    @pytest.mark.parametrize(
        "url",
        [
            "https://youtube.com.evil.com/watch?v=x",
            "https://tiktok.com.attacker.net/@a/video/1",
            "https://x.com.evil.com/status/1",
        ],
    )
    def test_lookalike_domains_rejected(self, url):
        """Suffix matching would let these through; exact matching must not."""
        assert detect_platform(url) is None

    def test_uppercase_host_is_normalised(self):
        assert detect_platform("https://WWW.TikTok.COM/@a/video/1").key == "tiktok"

    def test_port_and_userinfo_stripped(self):
        assert detect_platform("https://user:pw@www.tiktok.com:443/@a/video/1").key == "tiktok"


class TestSubdomainRouting:
    @pytest.mark.parametrize(
        "host,expected",
        [
            ("tiktok.example.com", "tiktok"),
            ("youtube.example.com", "youtube"),
            ("pinterest.example.com", "pinterest"),
            ("tiktok.example.com:443", "tiktok"),
            ("TIKTOK.EXAMPLE.COM", "tiktok"),
        ],
    )
    def test_resolves_platform_from_host(self, host, expected):
        platform = platform_for_subdomain(host)
        assert platform is not None
        assert platform.key == expected

    def test_apex_domain_has_no_platform(self):
        assert platform_for_subdomain("example.com") is None

    def test_unknown_subdomain_has_no_platform(self):
        assert platform_for_subdomain("unknown.example.com") is None


class TestRequestValidation:
    @pytest.mark.parametrize(
        "url,mode",
        [
            ("https://www.tiktok.com/@a/video/1", "video"),
            ("https://x.com/u/status/1", "video"),
            ("https://www.facebook.com/watch/?v=1", "video"),
            ("https://www.pinterest.com/pin/1/", "video"),
            ("https://www.instagram.com/reel/a/", "video"),
        ],
    )
    def test_accepts_platform_urls(self, url, mode):
        req = DownloadRequest(url=url, mode=mode)
        assert req.url == url

    def test_rejects_unsupported_host(self):
        with pytest.raises(ValueError, match="Unsupported host"):
            DownloadRequest(url="https://vimeo.com/1")

    def test_rejects_quality_above_platform_ceiling(self):
        """TikTok has no 4K, so asking for it must fail loudly."""
        with pytest.raises(ValueError, match="quality for TikTok"):
            DownloadRequest(url="https://www.tiktok.com/@a/video/1", quality="2160p")

    def test_accepts_quality_at_platform_ceiling(self):
        req = DownloadRequest(url="https://www.tiktok.com/@a/video/1", quality="1080p")
        assert req.quality == "1080p"

    def test_youtube_still_accepts_8k(self):
        req = DownloadRequest(url="https://youtu.be/x", quality="4320p")
        assert req.quality == "4320p"

    def test_audio_mode_rejects_video_only_quality_validation(self):
        """In audio mode the quality field is not the thing being validated."""
        req = DownloadRequest(url="https://youtu.be/x", mode="audio", audio_format="flac")
        assert req.audio_format == "flac"

    def test_rejects_bad_audio_format(self):
        with pytest.raises(ValueError, match="audio_format"):
            DownloadRequest(url="https://youtu.be/x", mode="audio", audio_format="wma")

    def test_supported_hosts_covers_every_platform(self):
        hosts = supported_hosts()
        for platform in PLATFORMS.values():
            for host in platform.hosts:
                assert host in hosts
