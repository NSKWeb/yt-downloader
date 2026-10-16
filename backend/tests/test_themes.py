"""Tests for the accent palette catalogue."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.themes import (
    DEFAULT_MODE,
    DEFAULT_THEME,
    MODES,
    SURFACES,
    THEMES,
    theme_catalog,
    theme_for_key,
)

STYLE_CSS = Path(__file__).resolve().parents[2] / "frontend" / "assets" / "style.css"
THEME_JS = Path(__file__).resolve().parents[2] / "frontend" / "assets" / "theme.js"
INDEX_HTML = Path(__file__).resolve().parents[2] / "frontend" / "index.html"


def _lin(c: float) -> float:
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lum(h: str) -> float:
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _contrast(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


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
    assert body["default_mode"] == "dark"
    assert body["mode_storage_key"] == "ytdl-mode"
    assert body["modes"] == ["dark", "light"]
    assert body["surfaces"] == {"dark": "#0d1117", "light": "#f6f8fa"}
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


def _token(block: str, name: str) -> str | None:
    m = re.search(r"--" + re.escape(name) + r":\s*(#[0-9A-Fa-f]{6})", block)
    return m.group(1) if m else None


def test_state_colours_clear_wcag_aa_in_both_modes():
    """The semantic colours are mode-dependent, so check the rendered pairs.

    These are the real text-on-surface combinations the state tokens produce.
    Reading them from the stylesheet rather than restating the hexes means a
    tweak to one is caught here rather than only by eye. The state borders are
    decorative (the surface tint carries the signal), so they are checked for
    distinctness, not for text contrast.
    """
    css = STYLE_CSS.read_text(encoding="utf-8")
    dark = _css_blocks(css)["__root__"]
    light_m = re.search(r'html\[data-mode="light"\]\s*\{(.*?)\n\}', css, re.S)
    assert light_m is not None, "no html[data-mode=light] block"
    light = light_m.group(1)

    for mode, block in (("dark", dark), ("light", light)):
        muted = _token(block, "muted")
        text = _token(block, "text")
        assert muted and text, f"{mode}: missing muted/text"

        # Progress status text sits on the state surface.
        for surface in ("progress-done-bg", "progress-failed-bg"):
            bg = _token(block, surface)
            assert bg, f"{mode}: missing {surface}"
            assert _contrast(muted, bg) >= 4.5, f"{mode} muted on {surface}"
            assert _contrast(text, bg) >= 4.5, f"{mode} text on {surface}"

        # Alert copy on its own surface.
        for bg_name, fg_name in (("alert-error-bg", "alert-error-text"),
                                 ("alert-ok-bg", "alert-ok-text")):
            bg, fg = _token(block, bg_name), _token(block, fg_name)
            assert bg and fg, f"{mode}: missing {bg_name}/{fg_name}"
            assert _contrast(fg, bg) >= 4.5, f"{mode} {fg_name} on {bg_name}"

        # The success button carries a gradient, so its ink has to clear the
        # lighter (top) endpoint, which is the harder of the two.
        ink = _token(block, "success-ink")
        top = _token(block, "success-grad-top")
        bottom = _token(block, "success-grad-bottom")
        assert ink and top and bottom, f"{mode}: missing success tokens"
        for edge, name in ((top, "top"), (bottom, "bottom")):
            assert _contrast(ink, edge) >= 4.5, f"{mode} success ink on gradient {name}"

        # Each status surface must stand out from the page behind it.
        page = _token(block, "bg")
        for surface in ("progress-done-bg", "progress-failed-bg",
                        "alert-error-bg", "alert-ok-bg"):
            bg = _token(block, surface)
            assert _contrast(bg, page) >= 1.05, f"{mode} {surface} invisible on --bg"


def test_no_hardcoded_hex_outside_the_token_blocks():
    """A literal colour in a rule cannot follow the mode, so it is a bug here."""
    css = STYLE_CSS.read_text(encoding="utf-8")
    offenders = []
    for n, line in enumerate(css.splitlines(), 1):
        if not re.search(r"#[0-9a-fA-F]{3,8}\b", line):
            continue
        # Declarations and explanatory comments are where colours belong.
        if re.match(r"\s*--[A-Za-z0-9-]+:", line) or ":" not in line:
            continue
        offenders.append(f"{n}: {line.strip()}")
    assert not offenders, "hardcoded colour in a rule: " + "; ".join(offenders)


def test_metrics_match_recomputed_contrast():
    """Guard against a hand-edited ratio drifting from the real colours."""
    for t in THEMES:
        assert abs(_contrast(t.accent, SURFACES["dark"]) - t.contrast_accent) < 0.05, t.key
        assert abs(_contrast(t.accent_light, SURFACES["light"]) - t.contrast_accent_light) < 0.05, t.key
        assert abs(_contrast(t.accent_ink, t.accent_solid) - t.contrast_solid) < 0.05, t.key
        assert abs(_contrast(t.accent_ink, t.accent_hover) - t.contrast_hover) < 0.05, t.key


def _css_blocks(css: str) -> dict[str, str]:
    """The accent declarations for :root plus every plain [data-theme] block.

    The light-mode blocks are compound selectors (``html[data-mode="light"]
    [data-theme="..."]``), so they also match a bare [data-theme] search and
    would overwrite the dark values. They are read separately by _light_blocks.
    """
    blocks = {}
    root = re.search(r":root\s*\{(.*?)\}", css, re.S)
    assert root is not None, "no :root block in style.css"
    blocks["__root__"] = root.group(1)
    for m in re.finditer(r'\[data-theme="([^"]+)"\]\s*\{(.*?)\}', css, re.S):
        if 'data-mode="light"' in css[max(0, m.start() - 40):m.start()]:
            continue
        blocks[m.group(1)] = m.group(2)
    assert len(blocks) == 1 + len(THEMES), f"expected one block per theme, got {sorted(blocks)}"
    return blocks


def _assert_block_matches(block: str, theme, scope: str, light: bool = False) -> None:
    """Assert one CSS block declares this theme's roles and RGB triple.

    In light mode only --accent and --accent-rgb change; the fill, its ink and
    the hover are mode-independent, so they are asserted the same way.
    """

    def token(key):
        m = re.search(r"--" + key + r":\s*(#[0-9A-Fa-f]{6})", block)
        assert m is not None, f"--{key} missing for {scope}"
        return m.group(1).lower()

    accent = theme.accent_light if light else theme.accent
    assert token("accent") == accent.lower(), scope

    if not light:
        # The light blocks deliberately omit these: they are mode-independent,
        # so they inherit from the base [data-theme] block rather than being
        # restated (and risking a divergence). Only assert them dark.
        assert token("accent-solid") == theme.accent_solid.lower(), scope
        assert token("accent-ink") == theme.accent_ink.lower(), scope
        assert token("accent-hover") == theme.accent_hover.lower(), scope

    # --accent-rgb is what the focus ring, the glow and every shadow are built
    # from, so a stale triple leaves those tints the old colour even though the
    # four hex roles are correct.
    rgb = re.search(r"--accent-rgb:\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", block)
    assert rgb is not None, f"--accent-rgb missing for {scope}"
    got = "#%02X%02X%02X" % tuple(int(g) for g in rgb.groups())
    assert got.lower() == accent.lower(), f"{scope}: --accent-rgb is {got}"


def _light_blocks(css: str, key: str) -> str | None:
    m = re.search(
        r'html\[data-mode="light"\]\[data-theme="' + key + r'"\]\s*\{(.*?)\}',
        css,
        re.S,
    )
    return m.group(1) if m else None


def test_css_theme_blocks_match_the_api_catalogue():
    """Each [data-theme] block must declare its own palette, not a stale one."""
    css = STYLE_CSS.read_text(encoding="utf-8")
    blocks = _css_blocks(css)

    for t in THEMES:
        block = blocks.get(t.key)
        assert block is not None, f"no [data-theme={t.key}] block in style.css"
        _assert_block_matches(block, t, t.key)

        light = _light_blocks(css, t.key)
        assert light is not None, f"no light block for {t.key}"
        _assert_block_matches(light, t, f"{t.key} light", light=True)


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


def test_switcher_palettes_match_the_api_catalogue():
    """theme.js is what actually decides the colour, and nothing else checked it.

    It carries its own copy of the palette list -- it has to, because the
    pre-paint snippet runs before any fetch -- so this is the third place a
    palette is written down, after the stylesheet and app/themes.py. A hex or a
    key edited here alone would change what users see while every other check
    still passed.
    """
    js = THEME_JS.read_text(encoding="utf-8")
    entries = re.findall(
        r'\{\s*key:\s*"([^"]+)"\s*,\s*hex:\s*"(#[0-9A-Fa-f]{6})"\s*,\s*name:\s*"([^"]+)"',
        js,
    )
    assert entries, "no PALETTES entries found in theme.js"

    assert [k for k, _, _ in entries] == [t.key for t in THEMES], "palette order/keys"
    by_key = {t.key: t for t in THEMES}
    for key, hexval, name in entries:
        theme = by_key[key]
        assert hexval.lower() == theme.accent.lower(), f"{key}: theme.js hex"
        assert name == theme.name, f"{key}: theme.js display name"

    default = re.search(r'var\s+DEFAULT_KEY\s*=\s*"([^"]+)"', js)
    assert default is not None, "no DEFAULT_KEY in theme.js"
    assert default.group(1) == DEFAULT_THEME, "theme.js default != API default"

    storage = re.search(r'var\s+STORAGE_KEY\s*=\s*"([^"]+)"', js)
    assert storage is not None, "no STORAGE_KEY in theme.js"
    assert storage.group(1) == theme_catalog().storage_key, "theme.js storage key"

    mode_key = re.search(r'var\s+MODE_KEY\s*=\s*"([^"]+)"', js)
    assert mode_key is not None, "no MODE_KEY in theme.js"
    assert mode_key.group(1) == theme_catalog().mode_storage_key, "theme.js mode key"

    default_mode = re.search(r'var\s+DEFAULT_MODE\s*=\s*"([^"]+)"', js)
    assert default_mode is not None, "no DEFAULT_MODE in theme.js"
    assert default_mode.group(1) == DEFAULT_MODE, "theme.js default mode"

    modes = re.search(r"var\s+MODES\s*=\s*\[([^\]]+)\]", js)
    assert modes is not None, "no MODES in theme.js"
    assert re.findall(r'"([^"]+)"', modes.group(1)) == list(MODES), "theme.js modes"


def test_picker_is_swatch_only_and_names_the_current_palette():
    """The control shows three colours, not three long text buttons.

    A swatch alone is not perceivable by everyone, so the palette name must
    still be announced on the button and shown in text beside the group. This
    guards both halves, since either one alone would be a regression.
    """
    js = (STYLE_CSS.parents[1] / "assets" / "theme.js").read_text(encoding="utf-8")

    # One button per palette, labelled for assistive tech.
    assert "aria-label" in js and "b.setAttribute(\"aria-label\", p.name)" in js, \
        "swatch button has no accessible name"
    # The verbose per-button text that made the control three long pills.
    assert "mood-source" not in js, "per-button source text is back"
    # ...but the name is still shown, and updated on change.
    assert "data-mood-current" in js, "no current-palette name"
    assert 'p ? p.name : ""' in js, "current-palette name never set"

    css = STYLE_CSS.read_text(encoding="utf-8")
    assert ".mood-source" not in css, "stale .mood-source style"
    # The chosen palette is marked by a ring, which must follow the accent.
    m = re.search(r'\.mood-option\[aria-checked="true"\]\s*\{([^}]*)\}', css)
    assert m, "no checked-state style for the picker"
    assert "--accent" in m.group(1), "checked state does not follow the accent"


def test_every_page_applies_appearance_before_first_paint():
    """Without the snippet a returning visitor sees the wrong accent or mode."""
    pages = sorted((STYLE_CSS.parents[1]).glob("*.html"))
    assert pages, "no HTML pages found"

    for page in pages:
        html = page.read_text(encoding="utf-8")
        assert 'localStorage.getItem("ytdl-accent")' in html, f"{page.name}: no accent read"
        assert 'localStorage.getItem("ytdl-mode")' in html, f"{page.name}: no mode read"
        assert "prefers-color-scheme: light" in html, f"{page.name}: OS preference ignored"
        assert 'setAttribute("data-theme"' in html, f"{page.name}: no data-theme"
        assert 'setAttribute("data-mode"' in html, f"{page.name}: no data-mode"
        assert "theme.js" in html, f"{page.name}: theme.js not included"


def test_picker_is_in_the_footer_and_toggle_in_the_header():
    """The two controls live in different places; both must be present once."""
    pages = sorted((STYLE_CSS.parents[1]).glob("*.html"))
    assert pages, "no HTML pages found"

    for page in pages:
        html = page.read_text(encoding="utf-8")
        assert html.count("data-mood-options") == 1, f"{page.name}: no picker group"
        assert html.count("data-mode-mount") == 1, f"{page.name}: no toggle mount"

        header = html[html.index("<header"):html.index("</header>")]
        footer = html[html.index("<footer"):html.index("</footer>")]
        assert "data-mode-mount" in header, f"{page.name}: toggle not in header"
        assert "data-mood-options" in footer, f"{page.name}: picker not in footer"
        assert "data-mood-options" not in header, f"{page.name}: picker still in header"
        assert "data-mode-mount" not in footer, f"{page.name}: toggle leaked to footer"


def test_light_accents_clear_wcag_aa_on_the_light_page():
    """The brand colours cannot serve as light-mode text; the siblings must."""
    light = SURFACES["light"]
    for t in THEMES:
        assert t.contrast_accent_light >= 4.5, f"{t.key} light accent"
        # The brand colour must actively fail there, or the sibling is pointless.
        assert _contrast(t.accent, light) < 4.5, f"{t.key} should need a sibling"
