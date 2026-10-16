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

# Ratios are contrast-against-the-mode's-page-background for --accent (dark
# background for contrast_accent, light for contrast_accent_light), and
# contrast-of---accent-ink-against-the-fill for the other two, which are the
# same in both modes.
THEMES: tuple[AccentPalette, ...] = (
    AccentPalette(
        key="serenity",
        name="Serenity",
        source="Pantone 15-3919 · Colour of the Year 2016",
        accent="#92A8D1",
        accent_solid="#92A8D1",
        accent_ink="#0c1931",
        accent_hover="#a8b9da",
        accent_light="#606F8A",
        contrast_accent=7.88,
        contrast_accent_light=4.77,
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
        accent_light="#5F7081",
        contrast_accent=9.12,
        contrast_accent_light=4.79,
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
        accent_light="#477772",
        contrast_accent=11.41,
        contrast_accent_light=4.75,
        contrast_solid=8.10,
        contrast_hover=8.88,
    ),
)

DEFAULT_THEME = "serenity"

# Dark is the default because the site was built dark-first; light is opt-in via
# the header toggle, and an unset preference follows the OS (the pre-paint
# snippet reads prefers-color-scheme itself).
MODES: tuple[str, ...] = ("dark", "light")
DEFAULT_MODE = "dark"

# The page background each mode paints. Carried here so a caller can check the
# ratios rather than take them on trust.
SURFACES = {"dark": "#0d1117", "light": "#f6f8fa"}

_BY_KEY = {t.key: t for t in THEMES}


def theme_catalog() -> ThemeInfo:
    """Describe the selectable palettes and modes for the frontend."""
    return ThemeInfo(
        default=DEFAULT_THEME,
        themes=list(THEMES),
        storage_key="ytdl-accent",
        default_mode=DEFAULT_MODE,
        mode_storage_key="ytdl-mode",
        modes=list(MODES),
        surfaces=dict(SURFACES),
    )


def theme_for_key(key: str) -> AccentPalette | None:
    """Look up a palette by key, or None if it is not a known theme."""
    return _BY_KEY.get(key)
