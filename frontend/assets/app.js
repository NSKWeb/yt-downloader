/* Downloader UI: platform detection, dynamic options, WebSocket progress. */
(function () {
  "use strict";

  const API = "/api";
  const AUDIO_FORMATS = ["mp3", "m4a", "wav", "flac", "opus", "aac", "ogg"];
  const AUDIO_QUALITIES = [
    { value: "128", label: "128 kbps" },
    { value: "192", label: "192 kbps" },
    { value: "256", label: "256 kbps" },
    { value: "320", label: "320 kbps" },
    { value: "best", label: "Best available" },
  ];

  let PLATFORMS = {};
  let platform = null;
  let mode = "video";
  let quality = "best";
  let audioFormat = "mp3";
  let audioQuality = "192";
  let playlist = false;
  let subtitles = false;
  let socket = null;
  let pollTimer = null;
  let activeTask = null;

  const $ = (id) => document.getElementById(id);

  function el(tag, attrs, text) {
    const node = document.createElement(tag);
    if (attrs) Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
    if (text != null) node.textContent = text;
    return node;
  }

  /* ---------- platform detection (mirrors the server allowlist) ---------- */

  function detectPlatform(url) {
    let parsed;
    try {
      parsed = new URL(url.trim());
    } catch (_) {
      return null;
    }
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
    const host = parsed.hostname.toLowerCase();
    const keys = Object.keys(PLATFORMS);
    for (let i = 0; i < keys.length; i++) {
      if (PLATFORMS[keys[i]].hosts.indexOf(host) !== -1) return PLATFORMS[keys[i]];
    }
    return null;
  }

  /* ---------- rendering ---------- */

  function showAlert(kind, message) {
    const box = $("alert");
    box.className = "alert visible " + kind;
    box.textContent = message;
  }

  function hideAlert() {
    $("alert").className = "alert";
  }

  function setPlatform(next) {
    if (platform && next && platform.key === next.key) return;
    platform = next;

    const badge = $("platform-badge");
    if (next) {
      badge.textContent = next.name;
      badge.className = "badge visible";
      document.body.dataset.platform = next.key;
    } else {
      badge.className = "badge";
      delete document.body.dataset.platform;
    }

    // Reset choices the new platform may not offer.
    if (next && next.video_qualities.indexOf(quality) === -1) {
      quality = next.default_quality || "best";
    }
    if (next && next.audio_formats.indexOf(audioFormat) === -1) {
      audioFormat = next.audio_formats[0];
    }
    if (next && !next.supports_playlists) playlist = false;
    if (next && !next.supports_subtitles) subtitles = false;
    if (next && !next.supports_video && mode === "video") mode = "audio";

    renderModes();
    renderOptions();
    renderExtras();
    renderNotice();
  }

  function renderNotice() {
    const box = $("platform-note");
    if (!platform || !platform.note) {
      box.className = "notice";
      box.textContent = "";
      return;
    }
    box.className = "notice visible" + (platform.public_content_limited ? " warn" : "");
    box.textContent = platform.note;
  }

  function renderModes() {
    const wrap = $("mode-toggle");
    wrap.innerHTML = "";
    const modes = [];
    if (!platform || platform.supports_video) modes.push(["video", "Video"]);
    if (!platform || platform.supports_audio) modes.push(["audio", "Audio"]);
    if (platform && platform.supports_images) modes.push(["image", "Image"]);

    wrap.style.display = modes.length < 2 ? "none" : "";

    modes.forEach((pair) => {
      const b = el("button", { type: "button" }, pair[1]);
      b.className = pair[0] === mode ? "active" : "";
      b.addEventListener("click", () => {
        mode = pair[0];
        renderModes();
        renderOptions();
        renderExtras();
      });
      wrap.appendChild(b);
    });
  }

  function qualityLabel(q) {
    const labels = {
      "360p": "360p",
      "480p": "480p",
      "720p": "720p HD",
      "1080p": "1080p FHD",
      "1440p": "1440p 2K",
      "2160p": "2160p 4K",
      "4320p": "4320p 8K",
      best: "Best",
    };
    return labels[q] || q;
  }

  function labelledSelect(label, values, current, onChange, format) {
    const wrap = el("div", { class: "select-field" });
    wrap.appendChild(el("label", null, label));
    const select = el("select");
    values.forEach((v) => {
      const opt = el("option", { value: v }, format ? format(v) : String(v).toUpperCase());
      if (v === current) opt.selected = true;
      select.appendChild(opt);
    });
    select.addEventListener("change", (e) => onChange(e.target.value));
    wrap.appendChild(select);
    return wrap;
  }

  function renderOptions() {
    const grid = $("options");
    grid.innerHTML = "";
    grid.style.display = "grid";

    if (mode === "image") {
      $("mode-label").textContent = "Image";
      grid.style.display = "block";
      grid.appendChild(el("p", { class: "hint" }, "The full-size image is downloaded as-is."));
      return;
    }

    if (mode === "video") {
      $("mode-label").textContent = "Quality";
      const qualities = platform ? platform.video_qualities : ["best"];
      qualities.forEach((q) => {
        const b = el("button", { type: "button" }, qualityLabel(q));
        b.className = q === quality ? "active" : "";
        b.addEventListener("click", () => {
          quality = q;
          renderOptions();
        });
        grid.appendChild(b);
      });
      return;
    }

    $("mode-label").textContent = "Audio format";
    const formats = platform ? platform.audio_formats : AUDIO_FORMATS;
    grid.style.display = "block";

    const row = el("div", { class: "select-row" });
    row.appendChild(
      labelledSelect("Format", formats, audioFormat, (v) => {
        audioFormat = v;
      })
    );
    row.appendChild(
      labelledSelect(
        "Bitrate",
        AUDIO_QUALITIES.map((q) => q.value),
        audioQuality,
        (v) => {
          audioQuality = v;
        },
        (v) => ((AUDIO_QUALITIES.find((q) => q.value === v) || {}).label || v)
      )
    );
    grid.appendChild(row);
  }

  function renderExtras() {
    const box = $("extras");
    box.innerHTML = "";
    if (!platform || mode === "image") {
      box.className = "extras";
      return;
    }
    const showPlaylist = platform.supports_playlists && mode === "video";
    const showSubs = platform.supports_subtitles && mode === "video";
    if (!showPlaylist && !showSubs) {
      box.className = "extras";
      return;
    }
    box.className = "extras visible";

    if (showPlaylist) {
      const input = el("input", { type: "checkbox", id: "opt-playlist" });
      input.checked = playlist;
      input.addEventListener("change", (e) => {
        playlist = e.target.checked;
      });
      box.appendChild(input);
      box.appendChild(el("label", { for: "opt-playlist" }, "Download entire playlist"));
    }
    if (showSubs) {
      const input = el("input", { type: "checkbox", id: "opt-subs" });
      input.checked = subtitles;
      input.addEventListener("change", (e) => {
        subtitles = e.target.checked;
      });
      box.appendChild(input);
      box.appendChild(el("label", { for: "opt-subs" }, "Include subtitles (.srt)"));
    }
  }

  /* ---------- progress ---------- */

  function resetProgress() {
    $("progress").classList.remove("visible");
    $("fill").style.width = "0%";
    $("pct").textContent = "0%";
    $("speed").textContent = "";
    $("eta").textContent = "";
    $("progress-title").textContent = "";
    const link = $("download-link");
    link.style.display = "none";
    link.removeAttribute("href");
  }

  function stopWatching() {
    if (socket) {
      try {
        socket.close();
      } catch (_) {
        /* already closed */
      }
      socket = null;
    }
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function renderStatus(data) {
    $("progress").classList.add("visible");
    const pct = Math.max(0, Math.min(100, data.progress || 0));
    $("fill").style.width = pct + "%";
    $("pct").textContent = pct.toFixed(1) + "%";
    $("speed").textContent = data.speed || "";
    $("eta").textContent = data.eta ? "ETA " + data.eta : "";
    if (data.title) $("progress-title").textContent = data.title;

    if (data.status === "complete") {
      stopWatching();
      $("fill").style.width = "100%";
      $("pct").textContent = "100%";
      const link = $("download-link");
      link.href = API + "/file/" + data.task_id;
      link.style.display = "inline-block";
      link.textContent = "Download file";
      showAlert("ok", "Ready.");
      $("submit").disabled = false;
      return;
    }

    if (data.status === "failed") {
      stopWatching();
      showAlert("error", data.error || "Download failed.");
      $("submit").disabled = false;
    }
  }

  function watchViaPolling(taskId) {
    const tick = async () => {
      try {
        const res = await fetch(API + "/status/" + taskId);
        if (res.status === 404) {
          stopWatching();
          showAlert("error", "Task not found. It may have expired.");
          $("submit").disabled = false;
          return;
        }
        if (!res.ok) return;
        renderStatus(await res.json());
      } catch (_) {
        stopWatching();
        showAlert("error", "Lost connection to the server.");
        $("submit").disabled = false;
      }
    };
    tick();
    pollTimer = setInterval(tick, 1000);
  }

  function watch(taskId) {
    activeTask = taskId;
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const url = proto + "//" + location.host + "/ws/progress/" + taskId;

    let ws;
    try {
      ws = new WebSocket(url);
    } catch (_) {
      watchViaPolling(taskId);
      return;
    }
    socket = ws;

    // If the socket cannot be established, fall back rather than stall.
    const fallback = setTimeout(() => {
      if (ws.readyState !== WebSocket.OPEN) {
        if (socket === ws) socket = null;
        try {
          ws.close();
        } catch (_) {
          /* ignore */
        }
        if (!pollTimer) watchViaPolling(taskId);
      }
    }, 3000);

    ws.addEventListener("open", () => clearTimeout(fallback));

    ws.addEventListener("message", (event) => {
      let data;
      try {
        data = JSON.parse(event.data);
      } catch (_) {
        return;
      }
      if (data.error) {
        if (socket === ws) socket = null;
        if (!pollTimer) watchViaPolling(taskId);
        return;
      }
      renderStatus(data);
    });

    ws.addEventListener("close", () => {
      clearTimeout(fallback);
      if (socket !== ws) return;
      socket = null;
      if (activeTask === taskId && !pollTimer) watchViaPolling(taskId);
    });
  }

  /* ---------- submit ---------- */

  async function errorMessage(res) {
    let detail = "Request rejected.";
    try {
      const body = await res.json();
      if (Array.isArray(body.detail)) detail = body.detail[0].msg;
      else if (body.detail) detail = body.detail;
    } catch (_) {
      /* non-JSON body */
    }
    if (res.status === 429) detail = "Too many requests. Please wait a moment.";
    return detail;
  }

  async function submit() {
    const url = $("url").value.trim();
    hideAlert();
    resetProgress();

    if (!url) {
      showAlert("error", "Paste a video URL first.");
      return;
    }
    if (!platform) {
      showAlert("error", "That link is not from a supported platform.");
      return;
    }

    $("submit").disabled = true;
    const payload = {
      url: url,
      mode: mode,
      quality: mode === "video" ? quality : "best",
      audio_format: audioFormat,
      audio_quality: audioQuality,
      playlist: playlist,
      subtitles: subtitles,
    };

    try {
      const res = await fetch(API + "/download", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        showAlert("error", await errorMessage(res));
        $("submit").disabled = false;
        return;
      }

      const data = await res.json();
      showAlert("ok", "Queued. Working on it\u2026");
      $("progress").classList.add("visible");
      stopWatching();
      watch(data.task_id);
    } catch (_) {
      showAlert("error", "Could not reach the backend.");
      $("submit").disabled = false;
    }
  }

  /* ---------- boot ---------- */

  function syncFromInput() {
    const url = $("url").value;
    setPlatform(url.trim() ? detectPlatform(url) : null);
  }

  function renderPlatformStrip() {
    const strip = $("platform-strip");
    if (!strip) return;
    strip.innerHTML = "";
    Object.keys(PLATFORMS).forEach((key) => {
      const p = PLATFORMS[key];
      const chip = el("button", { type: "button", class: "chip" }, p.name);
      chip.addEventListener("click", () => {
        $("url").value = "https://" + p.hosts[0] + "/";
        $("url").focus();
        syncFromInput();
      });
      strip.appendChild(chip);
    });
  }

  async function loadPlatforms() {
    try {
      const res = await fetch(API + "/platforms");
      if (!res.ok) return;
      const data = await res.json();
      data.platforms.forEach((p) => {
        PLATFORMS[p.key] = p;
      });
      renderPlatformStrip();
    } catch (_) {
      /* detection stays disabled; the server still validates every URL */
    }
  }

  document.addEventListener("DOMContentLoaded", async () => {
    await loadPlatforms();

    $("submit").addEventListener("click", submit);
    $("url").addEventListener("input", syncFromInput);
    $("url").addEventListener("change", syncFromInput);
    $("url").addEventListener("paste", () => setTimeout(syncFromInput, 0));
    $("url").addEventListener("keydown", (e) => {
      if (e.key === "Enter") submit();
    });

    renderModes();
    renderOptions();
    renderExtras();
    syncFromInput();
  });
})();
