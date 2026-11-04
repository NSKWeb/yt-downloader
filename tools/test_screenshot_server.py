"""Tests for the screenshot intake server.

OCR accuracy is not asserted: it depends on the tesseract build and the image.
What is asserted is the contract around it — accepted types, size and empty-file
rejection, the token gate, and that a stored upload is readable back through
/feed and /shots/{id}/text.
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import screenshot_server as server  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "UPLOADS", tmp_path)
    monkeypatch.setattr(server, "TOKEN", "")
    return TestClient(server.app)


@pytest.fixture
def png_bytes():
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (400, 120), "white").save(buffer, format="PNG")
    return buffer.getvalue()


class TestHealth:
    def test_reports_ok(self, client):
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert "ocr" in body

    def test_health_needs_no_token(self, tmp_path, monkeypatch, png_bytes):
        monkeypatch.setattr(server, "UPLOADS", tmp_path)
        monkeypatch.setattr(server, "TOKEN", "s3cret")
        assert TestClient(server.app).get("/health").status_code == 200


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
    def test_upload_needs_token_when_set(self, tmp_path, monkeypatch, png_bytes):
        monkeypatch.setattr(server, "UPLOADS", tmp_path)
        monkeypatch.setattr(server, "TOKEN", "s3cret")
        c = TestClient(server.app)
        assert c.post("/upload", files={"files": ("a.png", png_bytes, "image/png")}).status_code == 401
        ok = c.post(
            "/upload?t=s3cret",
            files={"files": ("a.png", png_bytes, "image/png")},
        )
        assert ok.status_code == 200

    def test_feed_and_page_need_token(self, tmp_path, monkeypatch):
        monkeypatch.setattr(server, "UPLOADS", tmp_path)
        monkeypatch.setattr(server, "TOKEN", "s3cret")
        c = TestClient(server.app)
        assert c.get("/feed").status_code == 401
        assert c.get("/").status_code == 401
        assert c.get("/feed?t=s3cret").status_code == 200


class TestReadBack:
    def test_feed_contains_upload(self, client, png_bytes):
        client.post("/upload", files={"files": ("shot.png", png_bytes, "image/png")})
        body = client.get("/feed").text
        assert "shot.png" in body

    def test_text_endpoint_matches_metadata(self, client, png_bytes):
        upload = client.post(
            "/upload", files={"files": ("shot.png", png_bytes, "image/png")}
        ).json()["uploads"][0]
        res = client.get(f"/shots/{upload['id']}/text")
        assert res.status_code == 200
        assert res.text == upload["ocr_text"]

    def test_image_endpoint_serves_bytes(self, client, png_bytes):
        upload = client.post(
            "/upload", files={"files": ("shot.png", png_bytes, "image/png")}
        ).json()["uploads"][0]
        res = client.get(f"/shots/{upload['id']}")
        assert res.status_code == 200
        assert res.content == png_bytes

    def test_unknown_id_is_404(self, client):
        assert client.get("/shots/deadbeef/text").status_code == 404

    def test_bad_id_is_rejected(self, client):
        assert client.get("/shots/..%2fetc/text").status_code in (400, 404)


class TestEmptyState:
    def test_feed_without_uploads(self, client):
        assert "no uploads" in client.get("/feed").text

    def test_page_renders(self, client):
        body = client.get("/").text
        assert "Send a screenshot" in body
        assert "__MAX__" not in body and "__TOKEN__" not in body


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
