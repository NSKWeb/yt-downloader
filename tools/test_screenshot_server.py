"""Tests for the screenshot intake server.

OCR accuracy is not asserted: it depends on the tesseract build and the image.
What is asserted is the contract around it — accepted types, size and empty-file
rejection, the token gate, the mounted-prefix form, and that a stored upload is
readable back through /feed and /{id}/text.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import screenshot_server as server  # noqa: E402


def make_png(size=(400, 120)) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, "white").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def png_bytes():
    return make_png()


@pytest.fixture
def client(tmp_path):
    return TestClient(server.create_app(upload_dir=tmp_path))


@pytest.fixture
def guarded(tmp_path):
    return TestClient(server.create_app(token="s3cret", upload_dir=tmp_path))


class TestHealth:
    def test_reports_ok(self, client):
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert "ocr" in body

    def test_health_needs_no_token(self, guarded):
        assert guarded.get("/health").status_code == 200


class TestUpload:
    def test_stores_and_returns_ocr_field(self, client, png_bytes):
        res = client.post("/upload", files={"files": ("a.png", png_bytes, "image/png")})
        assert res.status_code == 200
        upload = res.json()["uploads"][0]
        assert upload["filename"] == "a.png"
        assert upload["bytes"] == len(png_bytes)
        assert "ocr_text" in upload

    def test_multiple_files_in_one_request(self, client, png_bytes):
        res = client.post(
            "/upload",
            files=[
                ("files", ("a.png", png_bytes, "image/png")),
                ("files", ("b.png", png_bytes, "image/png")),
            ],
        )
        assert len(res.json()["uploads"]) == 2

    def test_rejects_non_image(self, client):
        res = client.post("/upload", files={"files": ("a.txt", b"hello", "text/plain")})
        assert res.status_code == 415

    def test_rejects_empty_file(self, client):
        res = client.post("/upload", files={"files": ("a.png", b"", "image/png")})
        assert res.status_code == 400

    def test_rejects_oversized_file(self, client, monkeypatch, png_bytes):
        monkeypatch.setattr(server, "MAX_BYTES", 10)
        res = client.post("/upload", files={"files": ("a.png", png_bytes, "image/png")})
        assert res.status_code == 413


class TestToken:
    def test_upload_needs_token_when_set(self, guarded, png_bytes):
        blocked = guarded.post("/upload", files={"files": ("a.png", png_bytes, "image/png")})
        assert blocked.status_code == 401
        ok = guarded.post("/upload?t=s3cret", files={"files": ("a.png", png_bytes, "image/png")})
        assert ok.status_code == 200

    def test_wrong_token_is_rejected(self, guarded):
        assert guarded.get("/?t=nope").status_code == 401

    def test_feed_and_page_need_token(self, guarded):
        assert guarded.get("/feed").status_code == 401
        assert guarded.get("/").status_code == 401
        assert guarded.get("/feed?t=s3cret").status_code == 200
        assert guarded.get("/?t=s3cret").status_code == 200


class TestReadBack:
    def test_feed_contains_upload(self, client, png_bytes):
        client.post("/upload", files={"files": ("shot.png", png_bytes, "image/png")})
        assert "shot.png" in client.get("/feed").text

    def test_text_endpoint_matches_metadata(self, client, png_bytes):
        upload = client.post(
            "/upload", files={"files": ("shot.png", png_bytes, "image/png")}
        ).json()["uploads"][0]
        res = client.get(f"/{upload['id']}/text")
        assert res.status_code == 200
        assert res.text == upload["ocr_text"]

    def test_image_endpoint_serves_bytes(self, client, png_bytes):
        upload = client.post(
            "/upload", files={"files": ("shot.png", png_bytes, "image/png")}
        ).json()["uploads"][0]
        res = client.get(f"/{upload['id']}")
        assert res.status_code == 200
        assert res.content == png_bytes

    def test_list_returns_newest_first(self, client, png_bytes):
        for name in ("first.png", "second.png"):
            client.post("/upload", files={"files": (name, png_bytes, "image/png")})
        names = [s["filename"] for s in client.get("/list").json()["shots"]]
        assert names == ["second.png", "first.png"]

    def test_unknown_id_is_404(self, client):
        assert client.get("/deadbeef/text").status_code == 404

    def test_bad_id_is_rejected(self, client):
        assert client.get("/..%2fetc/text").status_code in (400, 404)


class TestEmptyState:
    def test_feed_without_uploads(self, client):
        assert "no uploads" in client.get("/feed").text

    def test_page_renders_without_placeholders(self, client):
        body = client.get("/").text
        assert "Send a screenshot" in body
        assert "__MAX__" not in body and "__TOKEN__" not in body

    def test_page_embeds_token_when_set(self, guarded):
        assert '"s3cret"' in guarded.get("/?t=s3cret").text


class TestMountedPrefix:
    """The downloader deployment mounts this under /shots, sharing its port."""

    @pytest.fixture
    def host(self, tmp_path):
        app = FastAPI()

        @app.get("/api/ping")
        async def ping():
            return {"pong": True}

        app.mount("/shots", server.create_app(token="tok", upload_dir=tmp_path))
        return TestClient(app)

    def test_does_not_shadow_host_routes(self, host):
        assert host.get("/api/ping").json() == {"pong": True}

    def test_bare_prefix_redirects_to_slash(self, host):
        res = host.get("/shots?t=tok", follow_redirects=False)
        assert res.status_code in (307, 308)
        assert res.headers["location"].endswith("/shots/?t=tok")

    def test_page_served_under_prefix(self, host):
        assert "Send a screenshot" in host.get("/shots/?t=tok").text

    def test_upload_and_read_under_prefix(self, host, png_bytes):
        res = host.post("/shots/upload?t=tok", files={"files": ("a.png", png_bytes, "image/png")})
        assert res.status_code == 200
        shot_id = res.json()["uploads"][0]["id"]
        assert host.get(f"/shots/{shot_id}?t=tok").status_code == 200
        assert host.get("/shots/feed?t=tok").text.count("a.png") == 1

    def test_prefix_routes_are_token_gated(self, host):
        assert host.get("/shots/").status_code == 401


class TestOcrDegrades:
    def test_missing_ocr_library_is_reported_not_raised(self, client, monkeypatch, png_bytes):
        """A host without tesseract must still accept the upload."""
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name in ("pytesseract", "PIL"):
                raise ImportError(f"blocked {name}")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        res = client.post("/upload", files={"files": ("a.png", png_bytes, "image/png")})
        assert res.status_code == 200
        upload = res.json()["uploads"][0]
        assert upload["ocr_text"] == ""
        assert "unavailable" in upload["ocr_error"]
