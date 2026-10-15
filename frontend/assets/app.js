/* Downloader UI: mode toggle, quality grid, polling, progress rendering. */
(function () {
  "use strict";

  const API = "/api";
  const VIDEO_QUALITIES = [
    { value: "360p", label: "360p" },
    { value: "480p", label: "480p" },
    { value: "720p", label: "720p HD" },
    { value: "1080p", label: "1080p FHD" },
    { value: "1440p", label: "1440p 2K" },
    { value: "2160p", label: "2160p 4K" },
    { value: "4320p", label: "4320p 8K" },
    { value: "best", label: "Best" },
  ];
  const AUDIO_FORMATS = ["mp3", "m4a", "wav", "flac", "opus", "aac", "ogg"];

  let mode = "video";
  let quality = "best";
  let audioFormat = "mp3";
  let pollTimer = null;

  const $ = (id) => document.getElementById(id);

  function el(tag, attrs, text) {
    const node = document.createElement(tag);
    if (attrs) Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
    if (text != null) node.textContent = text;
    return node;
  }

  function renderOptions() {
    const grid = $("options");
    grid.innerHTML = "";

    if (mode === "video") {
      VIDEO_QUALITIES.forEach((q) => {
        const b = el("button", { type: "button" }, q.label);
        b.className = q.value === quality ? "active" : "";
        b.addEventListener("click", () => {
          quality = q.value;
          renderOptions();
        });
        grid.appendChild(b);
      });
    } else {
      const select = el("select", { id: "audio-select" });
      AUDIO_FORMATS.forEach((f) => {
        const opt = el("option", { value: f }, f.toUpperCase());
        if (f === audioFormat) opt.selected = true;
        select.appendChild(opt);
      });
      select.addEventListener("change", (e) => {
        audioFormat = e.target.value;
      });
      grid.style.display = "block";
      grid.appendChild(select);
      return;
    }
    grid.style.display = "grid";
  }

  function setMode(next) {
    mode = next;
    document.querySelectorAll(".toggle button").forEach((b) => {
      b.classList.toggle("active", b.dataset.mode === next);
    });
    $("mode-label").textContent = next === "video" ? "Quality" : "Audio format";
    renderOptions();
  }

  function showAlert(kind, message) {
    const box = $("alert");
    box.className = "alert visible " + kind;
    box.textContent = message;
  }

  function hideAlert() {
    $("alert").className = "alert";
  }

  function resetProgress() {
    $("progress").classList.remove("visible");
    $("fill").style.width = "0%";
    $("pct").textContent = "0%";
    $("speed").textContent = "";
    $("eta").textContent = "";
    const link = $("download-link");
    link.style.display = "none";
    link.removeAttribute("href");
  }

  function renderStatus(data) {
    $("progress").classList.add("visible");
    const pct = Math.max(0, Math.min(100, data.progress || 0));
    $("fill").style.width = pct + "%";
    $("pct").textContent = pct.toFixed(1) + "%";
    $("speed").textContent = data.speed ? data.speed : "";
    $("eta").textContent = data.eta ? "ETA " + data.eta : "";

    if (data.status === "complete") {
      stopPolling();
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
      stopPolling();
      showAlert("error", data.error || "Download failed.");
      $("submit").disabled = false;
      return;
    }
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  async function poll(taskId) {
    try {
      const res = await fetch(API + "/status/" + taskId);
      if (res.status === 404) {
        stopPolling();
        showAlert("error", "Task not found. It may have expired.");
        $("submit").disabled = false;
        return;
      }
      if (!res.ok) return;
      renderStatus(await res.json());
    } catch (err) {
      stopPolling();
      showAlert("error", "Lost connection to the server.");
      $("submit").disabled = false;
    }
  }

  async function submit() {
    const url = $("url").value.trim();
    hideAlert();
    resetProgress();

    if (!url) {
      showAlert("error", "Paste a YouTube URL first.");
      return;
    }

    $("submit").disabled = true;

    try {
      const res = await fetch(API + "/download", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: url,
          mode: mode,
          quality: mode === "video" ? quality : "best",
          audio_format: audioFormat,
        }),
      });

      if (!res.ok) {
        let detail = "Request rejected.";
        try {
          const body = await res.json();
          if (Array.isArray(body.detail)) detail = body.detail[0].msg;
          else if (body.detail) detail = body.detail;
        } catch (_) { /* non-JSON error body */ }
        showAlert("error", detail);
        $("submit").disabled = false;
        return;
      }

      const data = await res.json();
      showAlert("ok", "Queued. Working on it\u2026");
      $("progress").classList.add("visible");
      stopPolling();
      poll(data.task_id);
      pollTimer = setInterval(() => poll(data.task_id), 1000);
    } catch (err) {
      showAlert("error", "Could not reach the backend.");
      $("submit").disabled = false;
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".toggle button").forEach((b) => {
      b.addEventListener("click", () => setMode(b.dataset.mode));
    });
    $("submit").addEventListener("click", submit);
    $("url").addEventListener("keydown", (e) => {
      if (e.key === "Enter") submit();
    });
    renderOptions();
  });
})();
