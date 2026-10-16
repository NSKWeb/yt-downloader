"""Accent palette catalogue.

The palettes are defined once here and served over HTTP, so the frontend can
cross-check the colours it renders against the API rather than trusting a
duplicated list. The selectable values themselves live in
``frontend/assets/style.css``; this module is the machine-readable mirror.

Each palette keeps the four accent roles the stylesheet needs. A single colour
cannot serve all four: an accent light enough to read as text on the dark page
is too light to carry text when used as a button fill.
"""

from __future__ import annotations

from .models import AccentPalette, ThemeInfo

# Ratios are contrast-against-#0d1117 for --accent, and
# contrast-of---accent-ink-against-the-fill for the other two.
THEMES: tuple[AccentPalette, ...] = (
    AccentPalette(
        key="serenity",
        name="Serenity",
        source="Pantone 15-3919 · Colour of the Year 2016",
        accent="#92A8D1",
        accent_solid="#92A8D1",
        accent_ink="#0c1931",
        accent_hover="#a8b9da",
        contrast_accent=7.88,
        contrast_solid=7.29,
        contrast_hover=8.85,
    ),
    AccentPalette(
        key="cerulean",
        name="Cerulean",
        source="Pantone 15-4020 · Colour of the Year 2000",
        accent="#9BB7D4",
        accent_solid="#9BB7D4",
        accent_ink="#0c1e31",
        accent_hover="#b0c6dd",
        contrast_accent=9.12,
        contrast_solid=8.12,
        contrast_hover=9.61,
    ),
    AccentPalette(
        key="tiffany",
        name="Tiffany Blue",
        source="Tiffany & Co.",
        accent="#81D8D0",
        accent_solid="#81D8D0",
        accent_ink="#083531",
        accent_hover="#98dfd9",
        contrast_accent=11.41,
        contrast_solid=8.10,
        contrast_hover=8.88,
    ),
)

DEFAULT_THEME = "serenity"

_BY_KEY = {t.key: t for t in THEMES}


def theme_catalog() -> ThemeInfo:
    """Describe the selectable palettes for the frontend."""
    return ThemeInfo(
        default=DEFAULT_THEME,
        themes=list(THEMES),
        storage_key="ytdl-accent",
    )


def theme_for_key(key: str) -> AccentPalette | None:
    """Look up a palette by key, or None if it is not a known theme."""
    return _BY_KEY.get(key)
