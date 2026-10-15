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


class TestMeaningfulError:
    """The message shown to users must be the cause, not transfer chatter."""

    def test_strips_aria2_progress_lines(self):
        from app.downloader import _meaningful_error

        lines = [
            "[#8533bb 0B/0B CN:1 DL:0B]",
            "[#8533bb 1.2MiB/3.4MiB CN:1 DL:900KiB]",
            "ERROR: [tiktok] 123: Unable to extract video url",
        ]
        msg = _meaningful_error(lines)
        assert "Unable to extract video url" in msg
        assert "8533bb" not in msg

    def test_strips_ansi_colour_codes(self):
        from app.downloader import _meaningful_error

        msg = _meaningful_error(["\x1b[0;31mERROR:\x1b[0m something broke"])
        assert "\x1b" not in msg
        assert "something broke" in msg

    def test_prefers_error_lines_over_later_noise(self):
        from app.downloader import _meaningful_error

        lines = [
            "ERROR: first real problem",
            "[download] Destination: x.mp4",
            "some trailing note",
        ]
        assert _meaningful_error(lines) == "ERROR: first real problem"

    def test_ignores_blank_lines(self):
        from app.downloader import _meaningful_error

        assert _meaningful_error(["", "   ", "\t"]) == "unknown error"

    def test_falls_back_to_tail_when_no_error_marker(self):
        from app.downloader import _meaningful_error

        msg = _meaningful_error(["step one", "step two"])
        assert "step one" in msg and "step two" in msg

    def test_result_is_bounded(self):
        from app.downloader import _meaningful_error

        msg = _meaningful_error(["ERROR: " + "x" * 5000])
        assert len(msg) <= 600


class TestAria2cArgs:
    """aria2c must not be the reason a download that yt-dlp could do fails."""

    def _args(self):
        from app.downloader import build_command

        cmd = build_command(
            "https://youtu.be/x", "video", "720p", "mp3", Path("/tmp"), "youtube"
        )
        idx = cmd.index("--downloader-args")
        return cmd[idx + 1]

    def test_forwards_connection_tuning(self):
        args = self._args()
        assert "-x 16" in args
        assert "-s 16" in args
        assert "-k 1M" in args

    def test_uses_generous_timeouts(self):
        args = self._args()
        assert "--connect-timeout=60" in args
        assert "--timeout=60" in args
        assert "--max-tries=5" in args

    def test_disables_speed_floor(self):
        # A slow but progressing transfer must not be killed for being slow.
        assert "--lowest-speed-limit=0" in self._args()

    def test_quiets_aria2c_progress_output(self):
        args = self._args()
        assert "--summary-interval=0" in args
        assert "--console-log-level=warn" in args

    def test_downloader_is_aria2c(self):
        from app.downloader import build_command

        cmd = build_command(
            "https://youtu.be/x", "video", "720p", "mp3", Path("/tmp"), "youtube"
        )
        assert cmd[cmd.index("--downloader") + 1] == "aria2c"
