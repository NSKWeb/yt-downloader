/* ==========================================================================
   yt-downloader — appearance controls

   Two independent, per-visitor preferences:

     accent  <html data-theme="...">   which of the three brand palettes
     mode    <html data-mode="...">    dark (default) or light

   Both are applied before first paint by a small inline snippet in each page's
   <head>, so this file never causes a flash of the wrong colour — it only
   renders the two controls and persists changes.

   The palette list is duplicated from style.css deliberately: the pre-paint
   snippet has to resolve the stored accent synchronously, before any fetch can
   return. tests/test_themes.py cross-checks this file against the stylesheet
   and the API catalogue, so the copies cannot drift apart.

   The accent picker lives in the footer so the header stays uncluttered; the
   dark/light toggle lives at the top right of the header, where a display
   preference is conventionally found.
   ========================================================================== */

(function () {
  "use strict";

  var STORAGE_KEY = "ytdl-accent";
  var MODE_KEY = "ytdl-mode";

  /* hex is the swatch shown in the picker; key matches a CSS block. */
  var PALETTES = [
    { key: "serenity", hex: "#92A8D1", name: "Serenity",      source: "Pantone 15-3919" },
    { key: "illuminating", hex: "#F5DF4D", name: "Illuminating",  source: "Pantone 13-0647" },
    { key: "tiffany",  hex: "#81D8D0", name: "Tiffany Blue",  source: "Tiffany & Co." }
  ];

  var DEFAULT_KEY = "serenity";
  var DEFAULT_MODE = "dark";
  var MODES = ["dark", "light"];

  function has(list, v) {
    return list.indexOf(v) !== -1;
  }

  function isValid(key) {
    for (var i = 0; i < PALETTES.length; i++) {
      if (PALETTES[i].key === key) return true;
    }
    return false;
  }

  function isValidMode(mode) {
    return has(MODES, mode);
  }

  function read(key) {
    try {
      return window.localStorage.getItem(key);
    } catch (e) {
      return null; /* private mode, or storage disabled */
    }
  }

  function write(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch (e) {
      /* persisting is a nicety, not a requirement */
    }
  }

  function storedTheme() {
    var v = read(STORAGE_KEY);
    return isValid(v) ? v : null;
  }

  function storedMode() {
    var v = read(MODE_KEY);
    return isValidMode(v) ? v : null;
  }

  /* An unset mode follows the OS. The snippet duplicates this so the first
     paint is already correct; this is the fallback when it did not run. */
  function preferredMode() {
    var m = storedMode();
    if (m) return m;
    try {
      if (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) {
        return "light";
      }
    } catch (e) { /* matchMedia unavailable */ }
    return DEFAULT_MODE;
  }

  function setThemeColor() {
    /* Keep the browser chrome in step with the surface actually painted. */
    var meta = document.querySelector('meta[name="theme-color"]');
    if (!meta) return;
    var bg = window.getComputedStyle(document.documentElement)
      .getPropertyValue("--bg").trim();
    if (bg) meta.setAttribute("content", bg);
  }

  function applyTheme(key, persist) {
    if (!isValid(key)) return;
    document.documentElement.setAttribute("data-theme", key);
    if (persist) write(STORAGE_KEY, key);
    syncControls();
    setThemeColor();
  }

  function applyMode(mode, persist) {
    if (!isValidMode(mode)) return;
    document.documentElement.setAttribute("data-mode", mode);
    if (persist) write(MODE_KEY, mode);
    syncControls();
    setThemeColor();
  }

  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") || storedTheme() || DEFAULT_KEY;
  }

  function currentMode() {
    return document.documentElement.getAttribute("data-mode") || preferredMode();
  }

  /* ---------------------------------------------------------------------
     Footer accent picker. One radio per palette, rendered as a bare colour
     swatch in a segmented pill, so the three colours are visible at a glance
     and choosing one needs no reading. The palette name is still announced
     (aria-label) and shown beside the pill (.mood-current), because a swatch
     alone is not perceivable by everyone.
     --------------------------------------------------------------------- */
  function buildPicker(mount) {
    var group = mount.querySelector("[data-mood-options]");
    if (!group) return;

    var legend = document.createElement("span");
    legend.className = "mood-legend";
    legend.id = "mood-legend";
    legend.textContent = "Accent";
    group.setAttribute("role", "radiogroup");
    group.setAttribute("aria-labelledby", "mood-legend");
    mount.insertBefore(legend, group);

    PALETTES.forEach(function (p) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "mood-option";
      b.dataset.key = p.key;
      b.setAttribute("role", "radio");
      b.setAttribute("aria-checked", "false");
      /* The swatch is the visible content, so the name has to be the label. */
      b.setAttribute("aria-label", p.name);
      b.title = p.name + " — " + p.source;

      var sw = document.createElement("span");
      sw.className = "swatch";
      sw.style.background = p.hex;
      sw.setAttribute("aria-hidden", "true");

      b.appendChild(sw);
      b.addEventListener("click", function () {
        applyTheme(p.key, true);
      });
      group.appendChild(b);
    });

    var current = document.createElement("span");
    current.className = "mood-current";
    current.dataset.moodCurrent = "";
    current.setAttribute("aria-live", "polite");
    mount.appendChild(current);
  }

  /* ---------------------------------------------------------------------
     Header dark/light toggle. Shows the mode it will switch *to*, which is
     what a user looks for in a toggle, and carries aria-pressed so the
     current state is still announced.
     --------------------------------------------------------------------- */
  var SUN = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" '
    + 'stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">'
    + '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4'
    + 'M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
  var MOON = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" '
    + 'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    + 'stroke-linejoin="round" aria-hidden="true">'
    + '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>';

  function buildModeToggle(mount) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "mode-toggle";
    b.dataset.modeToggle = "";
    b.addEventListener("click", function () {
      applyMode(currentMode() === "dark" ? "light" : "dark", true);
    });

    var icon = document.createElement("span");
    icon.className = "mode-icon";
    icon.setAttribute("aria-hidden", "true");

    var text = document.createElement("span");
    text.className = "mode-text";
    text.setAttribute("aria-hidden", "true");

    b.appendChild(icon);
    b.appendChild(text);
    mount.appendChild(b);
  }

  function paletteFor(key) {
    for (var i = 0; i < PALETTES.length; i++) {
      if (PALETTES[i].key === key) return PALETTES[i];
    }
    return null;
  }

  function syncControls() {
    var theme = currentTheme();
    var mode = currentMode();
    var light = mode === "light";

    var opts = document.querySelectorAll(".mood-option");
    for (var i = 0; i < opts.length; i++) {
      opts[i].setAttribute("aria-checked", String(opts[i].dataset.key === theme));
    }

    /* The swatch pill shows colour but not which colour, so name it in text. */
    var current = document.querySelector("[data-mood-current]");
    if (current) {
      var p = paletteFor(theme);
      current.textContent = p ? p.name : "";
    }

    var toggle = document.querySelector("[data-mode-toggle]");
    if (toggle) {
      var icon = toggle.querySelector(".mode-icon");
      var text = toggle.querySelector(".mode-text");
      /* Show the mode this will switch to, not the one already on. */
      if (icon) icon.innerHTML = light ? MOON : SUN;
      if (text) text.textContent = light ? "Dark" : "Light";
      toggle.setAttribute("aria-pressed", String(light));
      toggle.setAttribute("aria-label", "Switch to " + (light ? "dark" : "light") + " mode");
      toggle.title = toggle.getAttribute("aria-label");
    }
  }

  function init() {
    /* The inline snippet already set both attributes; fall back only if it did
       not run for some reason. */
    var theme = currentTheme();
    var mode = currentMode();
    document.documentElement.setAttribute("data-theme", theme);
    document.documentElement.setAttribute("data-mode", mode);

    var picker = document.querySelector("[data-mood]");
    if (picker) buildPicker(picker);

    var toggle = document.querySelector("[data-mode-mount]");
    if (toggle) buildModeToggle(toggle);

    syncControls();
    setThemeColor();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  /* Exposed for the palette catalogue endpoint / tests to cross-check. */
  window.YTDL_PALETTES = PALETTES;
  window.YTDL_MODES = MODES;
})();
