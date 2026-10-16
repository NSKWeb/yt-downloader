"""Tests for the accent palette catalogue."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.themes import DEFAULT_THEME, THEMES, theme_for_key

STYLE_CSS = Path(__file__).resolve().parents[2] / "frontend" / "assets" / "style.css"


@pytest.fixture
def client(monkeypatch):
    # Deliberately not `with TestClient(app)`: that runs the lifespan handler
    # and opens a real Redis pool. This route touches neither, so a plain
    # client avoids needing Redis for a static catalogue lookup.
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    yield TestClient(app)


def test_theme_catalog_lists_three_finalists(client):
    body = client.get("/api/themes").json()

    assert body["default"] == "serenity"
    assert body["storage_key"] == "ytdl-accent"
    keys = [t["key"] for t in body["themes"]]
    assert keys == ["serenity", "cerulean", "tiffany"]


def test_palette_carries_the_brand_colours():
    by_key = {t.key: t for t in THEMES}

    assert by_key["serenity"].accent == "#92A8D1"   # Pantone 15-3919
    assert by_key["cerulean"].accent == "#9BB7D4"   # Pantone 15-4020
    assert by_key["tiffany"].accent == "#81D8D0"    # Tiffany & Co.


def test_default_theme_exists():
    assert theme_for_key(DEFAULT_THEME) is not None


def test_unknown_theme_returns_none():
    assert theme_for_key("chartreuse") is None


def test_every_palette_passes_wcag_aa():
    """The whole point of the four roles: each must clear AA on the dark page."""
    for t in THEMES:
        assert t.contrast_accent >= 4.5, f"{t.key} accent on --bg"
        assert t.contrast_solid >= 4.5, f"{t.key} ink on fill"
        assert t.contrast_hover >= 4.5, f"{t.key} ink on hover fill"


def test_metrics_match_recomputed_contrast():
    """Guard against a hand-edited ratio drifting from the real colours."""

    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    def lum(h):
        h = h.lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)

    def ratio(a, b):
        la, lb = lum(a), lum(b)
        hi, lo = max(la, lb), min(la, lb)
        return (hi + 0.05) / (lo + 0.05)

    for t in THEMES:
        assert abs(ratio(t.accent, "#0d1117") - t.contrast_accent) < 0.05, t.key
        assert abs(ratio(t.accent_ink, t.accent_solid) - t.contrast_solid) < 0.05, t.key
        assert abs(ratio(t.accent_ink, t.accent_hover) - t.contrast_hover) < 0.05, t.key


def test_css_blocks_match_the_api_catalogue():
    """The API is a mirror of the stylesheet, so they must not drift apart."""
    css = STYLE_CSS.read_text(encoding="utf-8")

    for t in THEMES:
        block = re.search(
            r'\[data-theme="' + t.key + r'"\]\s*\{(.*?)\}', css, re.S
        )
        assert block is not None, f"no [data-theme={t.key}] block in style.css"
        body = block.group(1)

        def token(name):
            m = re.search(r"--" + name + r":\s*(#[0-9A-Fa-f]{6})", body)
            assert m is not None, f"--{name} missing for {t.key}"
            return m.group(1).lower()

        assert token("accent") == t.accent.lower(), t.key
        assert token("accent-solid") == t.accent_solid.lower(), t.key
        assert token("accent-ink") == t.accent_ink.lower(), t.key
        assert token("accent-hover") == t.accent_hover.lower(), t.key
