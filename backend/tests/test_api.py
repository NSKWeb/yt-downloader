"""API tests. Redis is faked with a small in-memory stub so the real request
validation, storage, and response-shaping code paths are exercised."""


import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


class FakeRedis:
    """Minimal stand-in for the ARQ redis pool used by the API layer."""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.jobs: list[tuple] = []
        self.zsets: dict[str, dict] = {}

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        self.store.pop(key, None)

    async def enqueue_job(self, name, *args):
        self.jobs.append((name, args))

    async def close(self):
        pass

    # --- rate limiter support -------------------------------------------------
    def pipeline(self):
        return _FakePipeline(self.zsets)


class _FakePipeline:
    def __init__(self, store):
        self.store = store
        self.ops = []

    def zremrangebyscore(self, key, _min, max_score):
        self.ops.append(("trim", key, max_score))
        return self

    def zadd(self, key, mapping):
        self.ops.append(("add", key, mapping))
        return self

    def zcard(self, key):
        self.ops.append(("card", key))
        return self

    def expire(self, key, seconds):
        self.ops.append(("expire", key, seconds))
        return self

    async def execute(self):
        results = []
        for op in self.ops:
            if op[0] == "trim":
                _, key, cutoff = op
                entries = self.store.setdefault(key, {})
                for member in [m for m, s in entries.items() if s <= cutoff]:
                    del entries[member]
                results.append(None)
            elif op[0] == "add":
                _, key, mapping = op
                self.store.setdefault(key, {}).update(mapping)
                results.append(1)
            elif op[0] == "card":
                _, key = op
                results.append(len(self.store.get(key, {})))
            else:
                results.append(True)
        return results


@pytest.fixture
def client(monkeypatch):
    # Deliberately not using `with TestClient(app)` — that would run the
    # lifespan handler and open a real Redis pool. The API layer only touches
    # app.state.redis, so injecting the stub is enough.
    # Rate limiting is off here so lifecycle tests are not affected by it; it
    # has its own dedicated tests in test_rate_limit.py.
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "history_enabled", False)
    fake = FakeRedis()
    app.state.redis = fake
    settings.download_dir.mkdir(parents=True, exist_ok=True)
    yield TestClient(app)


class TestHealth:
    def test_health_ok(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


class TestValidation:
    @pytest.mark.parametrize(
        "url",
        [
            "not-a-url",
            "ftp://youtube.com/watch?v=x",
            "https://vimeo.com/12345",
            "https://evil.com/?q=youtube.com/watch?v=x",
            "https://youtube.com.evil.com/watch?v=x",
            "",
        ],
    )
    def test_rejects_bad_urls(self, client, url):
        r = client.post("/api/download", json={"url": url})
        assert r.status_code == 422

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
        ],
    )
    def test_accepts_youtube_urls(self, client, url):
        r = client.post("/api/download", json={"url": url, "mode": "video"})
        assert r.status_code == 200
        assert r.json()["status"] == "queued"

    def test_rejects_unknown_quality(self, client):
        r = client.post(
            "/api/download",
            json={"url": "https://youtu.be/x", "quality": "9000p"},
        )
        assert r.status_code == 422

    def test_rejects_unknown_audio_format(self, client):
        r = client.post(
            "/api/download",
            json={
                "url": "https://youtu.be/x",
                "mode": "audio",
                "audio_format": "wma",
            },
        )
        assert r.status_code == 422

    def test_rejects_unknown_mode(self, client):
        r = client.post("/api/download", json={"url": "https://youtu.be/x", "mode": "gif"})
        assert r.status_code == 422


class TestJobLifecycle:
    def test_download_enqueues_job(self, client):
        r = client.post("/api/download", json={"url": "https://youtu.be/abc"})
        assert r.status_code == 200
        task_id = r.json()["task_id"]
        assert len(task_id) == 32
        assert app.state.redis.jobs[0][0] == "download_task"

    def test_status_reports_queued(self, client):
        task_id = client.post("/api/download", json={"url": "https://youtu.be/abc"}).json()[
            "task_id"
        ]
        r = client.get(f"/api/status/{task_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["task_id"] == task_id
        assert body["status"] == "queued"
        assert body["progress"] == 0.0

    def test_status_unknown_task_is_404(self, client):
        assert client.get("/api/status/deadbeef").status_code == 404

    def test_file_before_completion_is_409(self, client):
        task_id = client.post("/api/download", json={"url": "https://youtu.be/abc"}).json()[
            "task_id"
        ]
        assert client.get(f"/api/file/{task_id}").status_code == 409

    def test_file_unknown_task_is_404(self, client):
        assert client.get("/api/file/deadbeef").status_code == 404

    def test_file_served_after_completion(self, client):
        from app.models import JobState, JobStatus

        settings.download_dir.mkdir(parents=True, exist_ok=True)
        target = settings.download_dir / "test-artifact.bin"
        target.write_bytes(b"hello")

        job = JobState(
            task_id="abc123",
            url="https://youtu.be/x",
            mode="video",
            quality="best",
            status=JobStatus.COMPLETE,
            progress=100.0,
            filename=target.name,
        )
        app.state.redis.store["job:abc123"] = job.model_dump_json()

        r = client.get("/api/file/abc123")
        assert r.status_code == 200
        assert r.content == b"hello"
        target.unlink()

    def test_path_traversal_filename_is_rejected(self, client):
        from app.models import JobState, JobStatus

        job = JobState(
            task_id="evil",
            url="https://youtu.be/x",
            mode="video",
            quality="best",
            status=JobStatus.COMPLETE,
            filename="../../etc/passwd",
        )
        app.state.redis.store["job:evil"] = job.model_dump_json()

        r = client.get("/api/file/evil")
        assert r.status_code in (400, 410)


class TestPlatformsEndpoint:
    def test_lists_all_six_platforms(self, client):
        r = client.get("/api/platforms")
        assert r.status_code == 200
        keys = {p["key"] for p in r.json()["platforms"]}
        assert keys == {
            "youtube",
            "instagram",
            "facebook",
            "twitter",
            "pinterest",
            "tiktok",
        }

    def test_each_platform_reports_its_options(self, client):
        for p in client.get("/api/platforms").json()["platforms"]:
            assert p["video_qualities"], p["key"]
            assert p["audio_formats"], p["key"]
            assert p["owner"], p["key"]

    def test_capability_flags_present(self, client):
        by_key = {p["key"]: p for p in client.get("/api/platforms").json()["platforms"]}
        assert by_key["youtube"]["supports_playlists"] is True
        assert by_key["youtube"]["supports_subtitles"] is True
        assert by_key["tiktok"]["supports_playlists"] is False
        assert by_key["pinterest"]["supports_images"] is True


class TestMultiPlatformRequests:
    @pytest.mark.parametrize(
        "url,expected_platform",
        [
            ("https://www.tiktok.com/@a/video/1", "tiktok"),
            ("https://x.com/u/status/1", "twitter"),
            ("https://www.facebook.com/watch/?v=1", "facebook"),
            ("https://www.pinterest.com/pin/1/", "pinterest"),
            ("https://www.instagram.com/reel/a/", "instagram"),
        ],
    )
    def test_platform_recorded_on_job(self, client, url, expected_platform):
        r = client.post("/api/download", json={"url": url, "quality": "720p"})
        assert r.status_code == 200
        task_id = r.json()["task_id"]
        status = client.get(f"/api/status/{task_id}").json()
        assert status["platform"] == expected_platform

    def test_platform_key_is_passed_to_the_worker(self, client):
        client.post(
            "/api/download",
            json={"url": "https://www.tiktok.com/@a/video/1", "quality": "720p"},
        )
        name, args = app.state.redis.jobs[-1]
        assert name == "download_task"
        assert args[5] == "tiktok"

    def test_playlist_and_subtitles_reach_the_worker(self, client):
        client.post(
            "/api/download",
            json={
                "url": "https://youtu.be/x",
                "quality": "720p",
                "playlist": True,
                "subtitles": True,
                "audio_quality": "320",
            },
        )
        _, args = app.state.redis.jobs[-1]
        assert args[6] is True  # playlist
        assert args[7] is True  # subtitles
        assert args[8] == "320"  # audio_quality

    def test_playlist_rejected_where_unsupported(self, client):
        r = client.post(
            "/api/download",
            json={"url": "https://www.tiktok.com/@a/video/1", "playlist": True},
        )
        assert r.status_code == 422
        assert "playlist" in r.text.lower()

    def test_quality_ceiling_enforced_per_platform(self, client):
        r = client.post(
            "/api/download",
            json={"url": "https://www.tiktok.com/@a/video/1", "quality": "2160p"},
        )
        assert r.status_code == 422

    def test_lookalike_host_is_rejected(self, client):
        r = client.post(
            "/api/download", json={"url": "https://tiktok.com.evil.net/@a/video/1"}
        )
        assert r.status_code == 422


class TestHistoryEndpoints:
    def test_history_empty_when_disabled(self, client):
        r = client.get("/api/history")
        assert r.status_code == 200
        assert r.json()["entries"] == []

    def test_history_records_a_job(self, client, monkeypatch, tmp_path):
        import asyncio

        from app.history import init_db

        monkeypatch.setattr(settings, "history_enabled", True)
        monkeypatch.setattr(settings, "database_path", tmp_path / "h.db")
        # The lifespan handler creates the table in production; the client
        # fixture skips the lifespan, so create it here.
        asyncio.run(init_db())

        client.post(
            "/api/download",
            json={"url": "https://www.tiktok.com/@a/video/1", "quality": "720p"},
        )
        r = client.get("/api/history")
        assert r.status_code == 200
        entries = r.json()["entries"]
        assert len(entries) == 1
        assert entries[0]["platform"] == "tiktok"

    def test_history_limit_is_clamped(self, client):
        assert client.get("/api/history?limit=0").status_code == 200
        assert client.get("/api/history?limit=99999").status_code == 200

    def test_delete_history_entry(self, client):
        r = client.delete("/api/history/someid")
        assert r.status_code == 200
        assert r.json()["deleted"] == "someid"

    def test_info_accepts_fractional_duration(self, client, monkeypatch):
        """yt-dlp reports duration as a float, e.g. 74.304 for a 74s clip."""
        from app import main

        async def fake_probe(url):
            return {
                "title": "A clip",
                "uploader": "Someone",
                "duration": 74.304,
                "thumbnail": "https://example.invalid/t.jpg",
                "webpage_url": "https://www.facebook.com/watch/?v=1",
                "formats": [
                    {"height": 720, "vcodec": "avc1"},
                    {"height": 360, "vcodec": "avc1"},
                ],
            }

        monkeypatch.setattr(main, "probe_info", fake_probe)
        r = client.get("/api/info?url=https://www.facebook.com/watch/?v=1")
        assert r.status_code == 200
        body = r.json()
        assert body["duration"] == 74
        assert body["formats_available"] == ["360p", "720p"]

    def test_info_tolerates_missing_duration(self, client, monkeypatch):
        """yt-dlp yields the string "NA" when it cannot read a duration."""
        from app import main

        async def fake_probe(url):
            return {"title": "No duration", "duration": "NA", "formats": []}

        monkeypatch.setattr(main, "probe_info", fake_probe)
        r = client.get("/api/info?url=https://youtu.be/abc")
        assert r.status_code == 200
        assert r.json()["duration"] is None
