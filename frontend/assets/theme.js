/* ==========================================================================
   yt-downloader — accent palette switcher

   Drives the [data-theme] attribute on <html>, which the stylesheet uses to
   swap the four accent tokens. The palette list here is the single source of
   truth for the control; the matching CSS blocks live in style.css.

   The theme is applied before first paint by a small inline snippet in each
   page's <head>, so this file never causes a flash of the wrong colour — it
   only renders the control and persists changes.
   ========================================================================== */

(function () {
  "use strict";

  var STORAGE_KEY = "ytdl-accent";

  /* hex is the brand colour, shown on the button; key matches a CSS block. */
  var PALETTES = [
    { key: "serenity", hex: "#92A8D1", name: "Serenity",      source: "Pantone 15-3919" },
    { key: "cerulean", hex: "#9BB7D4", name: "Cerulean",      source: "Pantone 15-4020" },
    { key: "tiffany",  hex: "#81D8D0", name: "Tiffany Blue",  source: "Tiffany & Co." }
  ];

  var DEFAULT_KEY = "serenity";

  function isValid(key) {
    for (var i = 0; i < PALETTES.length; i++) {
      if (PALETTES[i].key === key) return true;
    }
    return false;
  }

  function stored() {
    try {
      var v = window.localStorage.getItem(STORAGE_KEY);
      return isValid(v) ? v : null;
    } catch (e) {
      return null; /* private mode, or storage disabled */
    }
  }

  function apply(key) {
    if (!isValid(key)) return;
    document.documentElement.setAttribute("data-theme", key);
    try {
      window.localStorage.setItem(STORAGE_KEY, key);
    } catch (e) {
      /* persisting is a nicety, not a requirement */
    }
    /* Keep the browser chrome colour in step with the page. */
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", "#111318");
    syncButtons(key);
  }

  function syncButtons(key) {
    var btns = document.querySelectorAll(".mood-btn");
    for (var i = 0; i < btns.length; i++) {
      btns[i].setAttribute("aria-pressed", String(btns[i].dataset.key === key));
    }
  }

  function build(mount) {
    var group = mount.querySelector(".mood-swatches");
    if (!group) return;

    PALETTES.forEach(function (p) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "mood-btn";
      b.dataset.key = p.key;
      b.setAttribute("aria-pressed", "false");
      b.title = p.name + " — " + p.source;
      b.setAttribute("aria-label", p.name + ", " + p.source);

      var sw = document.createElement("span");
      sw.className = "swatch";
      sw.style.background = p.hex;
      sw.setAttribute("aria-hidden", "true");

      var label = document.createElement("span");
      label.textContent = p.name;

      b.appendChild(sw);
      b.appendChild(label);
      b.addEventListener("click", function () {
        apply(p.key);
      });
      group.appendChild(b);
    });
  }

  function init() {
    /* The inline pre-paint snippet already set data-theme; fall back only if
       it did not run for some reason. */
    var current = document.documentElement.getAttribute("data-theme") || stored() || DEFAULT_KEY;
    document.documentElement.setAttribute("data-theme", current);

    var mount = document.querySelector("[data-mood]");
    if (mount) build(mount);
    syncButtons(current);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  /* Exposed for the palette catalogue endpoint / tests to cross-check. */
  window.YTDL_PALETTES = PALETTES;
})();
