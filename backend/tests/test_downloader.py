"""Tests for the downloader helpers (no network, no Redis)."""

from pathlib import Path

import pytest

from app.config import settings
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

    def test_duration_cap_is_enforced(self):
        """MAX_DURATION_SECONDS was a dead setting; the command must carry it."""
        from app.downloader import duration_filter

        cmd = build_command("https://youtu.be/x", "video", "best", "mp3", Path("/tmp"))
        assert "--match-filter" in cmd
        assert cmd[cmd.index("--match-filter") + 1] == duration_filter(
            settings.max_duration_seconds
        )

    def test_duration_filter_uses_optional_match(self):
        """`<?` not `<`: a video with no reported duration must still download."""
        from app.downloader import duration_filter

        assert duration_filter(3600) == "duration<?3600"


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


class TestOutputPicker:
    """The fallback must never hand back a non-media file.

    The output directory also holds the SQLite history database, and a job can
    leave subtitles or yt-dlp partials behind. A real run once served users
    `history.db` instead of their video because it simply took the newest file.
    """

    def _mk(self, tmp_path, name, *, age=0.0):
        p = tmp_path / name
        p.write_bytes(b"x" * 10)
        if age:
            import os
            import time

            ts = time.time() - age
            os.utime(p, (ts, ts))
        return p

    def test_ignores_history_database(self, tmp_path):
        from app.downloader import _pick_media_file

        self._mk(tmp_path, "history.db")
        video = self._mk(tmp_path, "clip.mp4", age=30)
        assert _pick_media_file(tmp_path) == video


    def test_ignores_subtitles(self, tmp_path):
        from app.downloader import _pick_media_file

        self._mk(tmp_path, "clip.en.srt")
        video = self._mk(tmp_path, "clip.mp4", age=30)
        assert _pick_media_file(tmp_path) == video

    def test_ignores_incomplete_partials(self, tmp_path):
        from app.downloader import _pick_media_file

        self._mk(tmp_path, "clip.mp4.part")
        video = self._mk(tmp_path, "clip.mp4", age=30)
        assert _pick_media_file(tmp_path) == video

    def test_picks_newest_media_when_several(self, tmp_path):
        from app.downloader import _pick_media_file

        self._mk(tmp_path, "old.mp4", age=100)
        new = self._mk(tmp_path, "new.mp4", age=1)
        assert _pick_media_file(tmp_path) == new

    def test_since_excludes_stale_files(self, tmp_path):
        import time

        from app.downloader import _pick_media_file

        self._mk(tmp_path, "stale.mp4", age=600)
        now = time.time()
        fresh = self._mk(tmp_path, "fresh.webm")
        assert _pick_media_file(tmp_path, since=now) == fresh

    def test_raises_when_no_media_present(self, tmp_path):
        from app.downloader import _pick_media_file

        self._mk(tmp_path, "history.db")
        with pytest.raises(RuntimeError, match="produced no file"):
            _pick_media_file(tmp_path)

    @pytest.mark.parametrize("ext", ["mp4", "webm", "mkv", "mp3", "m4a", "opus", "jpg"])
    def test_accepts_each_media_family(self, tmp_path, ext):
        from app.downloader import _pick_media_file

        f = self._mk(tmp_path, f"file.{ext}")
        assert _pick_media_file(tmp_path) == f

    def test_extension_match_is_case_insensitive(self, tmp_path):
        from app.downloader import _pick_media_file

        f = self._mk(tmp_path, "clip.MP4")
        assert _pick_media_file(tmp_path) == f


class TestProbeConcurrencyBound:
    """Each /api/info call forks a yt-dlp process, so concurrency must be capped.

    The route is unauthenticated; before the semaphore, 25 simultaneous requests
    started 25 processes and exhausted memory long before the queue drained.
    """

    @pytest.mark.asyncio
    async def test_concurrent_probes_are_bounded(self, monkeypatch):
        import asyncio

        from app import downloader

        peak = 0
        live = 0

        async def fake_probe(url):
            nonlocal peak, live
            live += 1
            peak = max(peak, live)
            await asyncio.sleep(0.05)
            live -= 1
            return {"title": url}

        # Fresh semaphore so the test does not inherit a partially drained one.
        monkeypatch.setattr(downloader, "_probe_semaphore", None)
        monkeypatch.setattr(downloader, "_probe_info_uncapped", fake_probe)

        results = await asyncio.gather(
            *(downloader.probe_info(f"u{i}") for i in range(20))
        )

        assert len(results) == 20
        assert peak <= downloader._PROBE_CONCURRENCY, (
            f"{peak} probes ran at once; cap is {downloader._PROBE_CONCURRENCY}"
        )
        assert peak > 1, "the cap must not serialise probes"

    @pytest.mark.asyncio
    async def test_semaphore_is_released_after_a_failure(self, monkeypatch):
        """A crashing probe must not leak a slot and stall every later request."""
        import asyncio

        from app import downloader

        calls = 0

        async def boom(url):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("probe blew up")
            return {"title": "ok"}

        monkeypatch.setattr(downloader, "_probe_semaphore", None)
        monkeypatch.setattr(downloader, "_probe_info_uncapped", boom)

        with pytest.raises(RuntimeError):
            await downloader.probe_info("first")

        # If the slot leaked, this would block until the test times out.
        assert await asyncio.wait_for(downloader.probe_info("second"), timeout=2) == {
            "title": "ok"
        }


class TestFilteredDownloadIsAFailure:
    """yt-dlp exits 0 when --match-filter rejects a video and writes nothing.

    Treating that as success would fall through to the "newest media file"
    fallback and could hand back a file from an earlier job.
    """

    class _FakeProc:
        def __init__(self, lines):
            self._lines = lines
            self.returncode = 0

        @property
        def stdout(self):
            async def gen():
                for line in self._lines:
                    yield line.encode()

            return gen()

        async def wait(self):
            return self.returncode

    @pytest.mark.asyncio
    async def test_filtered_run_raises_duration_error(self, tmp_path, monkeypatch):
        from app import downloader

        lines = [
            "[download] Some Long Video does not pass filter (duration<?14400), skipping ..",
        ]

        async def fake_exec(*cmd, **kwargs):
            return self._FakeProc(lines)

        monkeypatch.setattr(downloader.asyncio, "create_subprocess_exec", fake_exec)
        # A stale media file must not be mistaken for this job's output.
        (tmp_path / "stale.mp4").write_bytes(b"old")

        with pytest.raises(downloader.DurationLimitExceeded):
            await downloader.run_download(
                "https://youtu.be/x", "video", "best", "mp3", tmp_path
            )

    @pytest.mark.asyncio
    async def test_successful_run_still_returns_the_file(self, tmp_path, monkeypatch):
        from app import downloader

        out = tmp_path / "clip.mp4"

        async def fake_exec(*cmd, **kwargs):
            out.write_bytes(b"data")
            return self._FakeProc([str(out)])

        monkeypatch.setattr(downloader.asyncio, "create_subprocess_exec", fake_exec)

        assert await downloader.run_download(
            "https://youtu.be/x", "video", "best", "mp3", tmp_path
        ) == out
