"""Tests for the downloader helpers (no network, no Redis)."""

from pathlib import Path

import pytest

from app.downloader import _parse_progress_line, build_command, build_format_selector


class TestFormatSelector:
    def test_best_video(self):
        assert build_format_selector("video", "best") == "bestvideo+bestaudio/best"

    def test_specific_height(self):
        assert build_format_selector("video", "1080p") == (
            "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
        )

    def test_8k(self):
        assert "4320" in build_format_selector("video", "4320p")

    def test_audio_ignores_quality(self):
        assert build_format_selector("audio", "1080p") == "bestaudio/best"


class TestCommandBuilder:
    def test_audio_conversion_flags(self):
        cmd = build_command("https://youtu.be/x", "audio", "best", "flac", Path("/tmp"))
        assert "--extract-audio" in cmd
        assert cmd[cmd.index("--audio-format") + 1] == "flac"

    def test_no_playlist_always_set(self):
        cmd = build_command("https://youtu.be/x", "video", "720p", "mp3", Path("/tmp"))
        assert "--no-playlist" in cmd

    def test_output_template_is_inside_target_dir(self):
        cmd = build_command("https://youtu.be/x", "video", "720p", "mp3", Path("/downloads"))
        outtmpl = cmd[cmd.index("-o") + 1]
        assert outtmpl.startswith("/downloads/")

    def test_url_is_last_argument(self):
        url = "https://www.youtube.com/watch?v=abc"
        cmd = build_command(url, "video", "best", "mp3", Path("/tmp"))
        assert cmd[-1] == url

    def test_no_bot_bypass_flags_present(self):
        """The build must not spoof a player client or inject cookies."""
        cmd = build_command("https://youtu.be/x", "video", "best", "mp3", Path("/tmp"))
        joined = " ".join(cmd)
        assert "player_client" not in joined
        assert "--cookies" not in joined
        assert "--proxy" not in joined


class TestProgressParsing:
    @pytest.mark.parametrize(
        "line,expected_pct",
        [
            ("[download]  45.3% of 120.50MiB at 3.20MiB/s ETA 00:23", 45.3),
            ("[download] 100% of 12.00MiB", 100.0),
            ("[download]   0.0% of ~50.00MiB", 0.0),
        ],
    )
    def test_percent_extracted(self, line, expected_pct):
        parsed = _parse_progress_line(line)
        assert parsed is not None
        assert parsed["percent"] == expected_pct

    def test_speed_and_eta_extracted(self):
        parsed = _parse_progress_line(
            "[download]  45.3% of 120.50MiB at 3.20MiB/s ETA 00:23"
        )
        assert parsed["speed"] == "3.20MiB/s"
        assert parsed["eta"] == "00:23"

    def test_non_progress_line_returns_none(self):
        assert _parse_progress_line("[youtube] Extracting URL") is None
