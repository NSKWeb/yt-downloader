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


def _css_blocks(css: str) -> dict[str, str]:
    """The accent declarations for :root plus every [data-theme] block."""
    blocks = {}
    root = re.search(r":root\s*\{(.*?)\}", css, re.S)
    assert root is not None, "no :root block in style.css"
    blocks["__root__"] = root.group(1)
    for m in re.finditer(r'\[data-theme="([^"]+)"\]\s*\{(.*?)\}', css, re.S):
        blocks[m.group(1)] = m.group(2)
    return blocks


def _assert_block_matches(block: str, theme, scope: str) -> None:
    """Assert one CSS block declares this theme's four roles and RGB triple."""

    def token(key):
        m = re.search(r"--" + key + r":\s*(#[0-9A-Fa-f]{6})", block)
        assert m is not None, f"--{key} missing for {scope}"
        return m.group(1).lower()

    assert token("accent") == theme.accent.lower(), scope
    assert token("accent-solid") == theme.accent_solid.lower(), scope
    assert token("accent-ink") == theme.accent_ink.lower(), scope
    assert token("accent-hover") == theme.accent_hover.lower(), scope

    # --accent-rgb is what the focus ring, the glow and every shadow are built
    # from, so a stale triple leaves those tints the old colour even though the
    # four hex roles are correct.
    rgb = re.search(r"--accent-rgb:\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", block)
    assert rgb is not None, f"--accent-rgb missing for {scope}"
    got = "#%02X%02X%02X" % tuple(int(g) for g in rgb.groups())
    assert got.lower() == theme.accent.lower(), f"{scope}: --accent-rgb is {got}"


def test_css_theme_blocks_match_the_api_catalogue():
    """Each [data-theme] block must declare its own palette, not a stale one."""
    css = STYLE_CSS.read_text(encoding="utf-8")
    blocks = _css_blocks(css)

    for t in THEMES:
        block = blocks.get(t.key)
        assert block is not None, f"no [data-theme={t.key}] block in style.css"
        _assert_block_matches(block, t, t.key)


def test_root_default_matches_the_default_theme():
    """`:root` is the unthemed fallback, so it must be the default palette.

    Checking only the [data-theme] blocks would miss an edit here, and this is
    what a visitor sees before a theme is applied (and what a browser with
    localStorage disabled never leaves).
    """
    blocks = _css_blocks(STYLE_CSS.read_text(encoding="utf-8"))
    default = theme_for_key(DEFAULT_THEME)
    assert default is not None, f"DEFAULT_THEME {DEFAULT_THEME!r} is not a theme"
    _assert_block_matches(blocks["__root__"], default, f":root (default {DEFAULT_THEME})")
