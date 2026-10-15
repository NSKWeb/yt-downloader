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


@pytest.fixture
def client():
    # Deliberately not using `with TestClient(app)` — that would run the
    # lifespan handler and open a real Redis pool. The API layer only touches
    # app.state.redis, so injecting the stub is enough.
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
