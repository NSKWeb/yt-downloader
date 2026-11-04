"""Screenshot intake for conversations that cannot receive images directly.

Upload a screenshot in a browser and the server stores it and runs OCR over it.
The extracted text is what a text-only agent reads: the image bytes never reach
the model, only the words inside them.

Endpoints
    GET  /                  upload page
    POST /upload            multipart form, field "files"; returns the OCR text
    GET  /feed              newest uploads as plain text, for one-call reading
    GET  /shots             newest uploads as JSON
    GET  /shots/{id}        the stored image
    GET  /shots/{id}/text   OCR text for one upload
    GET  /health            liveness, OCR availability, upload count

Set UPLOAD_TOKEN to require ?t=<token> on every route except /health. Without it
anyone who can reach the port can upload and read.
"""

from __future__ import annotations

import io
import json
import os
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

ROOT = Path(os.environ.get("SCREENSHOT_DIR", "/tmp/screenshot-server"))
UPLOADS = ROOT / "uploads"
MAX_BYTES = int(os.environ.get("MAX_UPLOAD_MB", "25")) * 1024 * 1024
TOKEN = os.environ.get("UPLOAD_TOKEN", "").strip()

ALLOWED = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
}

app = FastAPI(title="screenshot-server", version="1.0.0")
UPLOADS.mkdir(parents=True, exist_ok=True)


def _check(token: str | None) -> None:
    if TOKEN and token != TOKEN:
        raise HTTPException(status_code=401, detail="bad or missing token")


def _new_id() -> str:
    return f"{int(time.time())}-{secrets.token_hex(3)}"


def _ocr(data: bytes) -> tuple[str, str | None]:
    """Return (text, error). Missing OCR tooling is a warning, not a failure.

    The image is stored and served either way, so an upload is never lost to a
    missing binary.
    """
    try:
        import pytesseract
        from PIL import Image, ImageOps
    except ImportError as exc:  # pragma: no cover - environment dependent
        return "", f"ocr unavailable: {exc}"
    try:
        image = Image.open(io.BytesIO(data))
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        # UI screenshots are small, and their text is thin and low contrast.
        # Grayscale plus a contrast stretch, then upscaling, is what moves
        # tesseract's accuracy most on this kind of input.
        image = ImageOps.grayscale(image)
        image = ImageOps.autocontrast(image, cutoff=1)
        if max(image.size) < 2000:
            scale = 2000 / max(image.size)
            image = image.resize(
                (int(image.width * scale), int(image.height * scale)),
                Image.LANCZOS,
            )
        return pytesseract.image_to_string(image).strip(), None
    except Exception as exc:  # pragma: no cover - OCR is best effort
        return "", f"ocr failed: {exc}"


def _meta_path(shot_id: str) -> Path:
    return UPLOADS / f"{shot_id}.json"


def _load(shot_id: str) -> dict:
    path = _meta_path(shot_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="no such upload")
    return json.loads(path.read_text())


def _recent(limit: int) -> list[dict]:
    metas = []
    for path in UPLOADS.glob("*.json"):
        try:
            metas.append(json.loads(path.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    metas.sort(key=lambda m: m["created_at"], reverse=True)
    return metas[:limit]


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Send a screenshot</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; display: grid; place-items: center;
         font: 16px/1.5 system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
         background: #0f1115; color: #e8eaed; padding: 24px; }
  main { width: 100%; max-width: 640px; }
  h1 { font-size: 22px; margin: 0 0 4px; }
  p.sub { margin: 0 0 20px; color: #9aa0a6; font-size: 14px; }
  #drop { border: 2px dashed #3c4043; border-radius: 14px; padding: 36px 20px;
          text-align: center; cursor: pointer; transition: .15s; background: #171a1f; }
  #drop.hot { border-color: #8ab4f8; background: #1b2230; }
  #drop b { display: block; font-size: 17px; margin-bottom: 6px; }
  #drop span { color: #9aa0a6; font-size: 13px; }
  input[type=file] { display: none; }
  button { margin-top: 16px; width: 100%; padding: 14px; font-size: 16px;
           font-weight: 600; border: 0; border-radius: 10px; background: #8ab4f8;
           color: #06214a; cursor: pointer; }
  button:disabled { opacity: .5; cursor: default; }
  #list { margin-top: 22px; display: grid; gap: 14px; }
  .card { background: #171a1f; border: 1px solid #2a2e35; border-radius: 12px;
          overflow: hidden; }
  .card img { width: 100%; display: block; max-height: 320px; object-fit: contain;
              background: #000; }
  .card pre { margin: 0; padding: 12px; font-size: 13px; white-space: pre-wrap;
              word-break: break-word; color: #c9cdd2; max-height: 240px;
              overflow: auto; }
  .ok { color: #81c995; font-size: 13px; margin-top: 12px; }
  .err { color: #f28b82; font-size: 13px; margin-top: 12px; }
</style></head><body><main>
  <h1>Send a screenshot</h1>
  <p class="sub">The text in it is extracted so the assistant can read it.</p>
  <div id="drop">
    <b>Tap to choose, or drop an image</b>
    <span>PNG, JPG, WebP, GIF, BMP, TIFF &middot; up to __MAX__ MB</span>
  </div>
  <input type="file" id="file" accept="image/*" multiple>
  <button id="go" disabled>Upload</button>
  <div id="msg"></div>
  <div id="list"></div>
</main>
<script>
const TOKEN = "__TOKEN__";
const qs = TOKEN ? "?t=" + TOKEN : "";
const drop = document.getElementById("drop");
const input = document.getElementById("file");
const go = document.getElementById("go");
const msg = document.getElementById("msg");
const list = document.getElementById("list");
let picked = [];

function label() {
  go.disabled = !picked.length;
  go.textContent = picked.length ? "Upload " + picked.length + " image(s)" : "Upload";
}
drop.addEventListener("click", () => input.click());
input.addEventListener("change", () => { picked = [...input.files]; label(); });
["dragenter","dragover"].forEach(e => drop.addEventListener(e, ev => {
  ev.preventDefault(); drop.classList.add("hot");
}));
["dragleave","drop"].forEach(e => drop.addEventListener(e, ev => {
  ev.preventDefault(); drop.classList.remove("hot");
}));
drop.addEventListener("drop", ev => {
  picked = [...ev.dataTransfer.files].filter(f => f.type.startsWith("image/"));
  label();
});

function show(kind, text) { msg.className = kind; msg.textContent = text; }

function card(shot) {
  const el = document.createElement("div");
  el.className = "card";
  const img = document.createElement("img");
  img.src = "/shots/" + shot.id + qs;
  const pre = document.createElement("pre");
  pre.textContent = shot.ocr_text || "(no text found)";
  el.append(img, pre);
  return el;
}

go.addEventListener("click", async () => {
  if (!picked.length) return;
  go.disabled = true;
  show("ok", "Uploading…");
  const form = new FormData();
  picked.forEach(f => form.append("files", f));
  try {
    const res = await fetch("/upload" + qs, { method: "POST", body: form });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    show("ok", "Uploaded " + data.uploads.length + " image(s).");
    data.uploads.forEach(u => list.prepend(card(u)));
    picked = [];
    input.value = "";
  } catch (e) {
    show("err", "Upload failed: " + e.message);
  }
  label();
});
</script></body></html>"""


@app.get("/health")
async def health() -> dict:
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401

        ocr = True
    except ImportError:
        ocr = False
    return {
        "status": "ok",
        "ocr": ocr,
        "auth": bool(TOKEN),
        "uploads": len(list(UPLOADS.glob("*.json"))),
    }


@app.get("/", response_class=HTMLResponse)
async def index(t: str | None = Query(default=None)) -> str:
    _check(t)
    page = PAGE.replace("__MAX__", str(MAX_BYTES // (1024 * 1024)))
    return page.replace("__TOKEN__", TOKEN)


@app.post("/upload")
async def upload(
    t: str | None = Query(default=None),
    files: list[UploadFile] = File(...),
) -> dict:
    _check(t)
    saved = []
    for item in files:
        ext = ALLOWED.get((item.content_type or "").lower())
        if ext is None:
            raise HTTPException(status_code=415, detail=f"unsupported type: {item.content_type}")
        data = await item.read()
        if not data:
            raise HTTPException(status_code=400, detail=f"{item.filename} is empty")
        if len(data) > MAX_BYTES:
            raise HTTPException(status_code=413, detail=f"{item.filename} exceeds the size limit")

        shot_id = _new_id()
        (UPLOADS / f"{shot_id}{ext}").write_bytes(data)
        text, error = _ocr(data)
        meta = {
            "id": shot_id,
            "filename": item.filename,
            "content_type": item.content_type,
            "bytes": len(data),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "ocr_text": text,
            "ocr_error": error,
            "url": f"/shots/{shot_id}{ext}",
        }
        _meta_path(shot_id).write_text(json.dumps(meta, indent=2))
        saved.append(meta)
    return {"uploads": saved}


@app.get("/shots")
async def shots(t: str | None = Query(default=None), limit: int = Query(default=20, le=100)) -> dict:
    _check(t)
    return {"shots": _recent(limit)}


@app.get("/shots/{shot_id}")
async def shot(shot_id: str, t: str | None = Query(default=None)) -> FileResponse:
    _check(t)
    if not re.fullmatch(r"[0-9a-f-]+", shot_id):
        raise HTTPException(status_code=400, detail="bad id")
    matches = [m for m in UPLOADS.glob(f"{shot_id}.*") if m.suffix != ".json"]
    if not matches:
        raise HTTPException(status_code=404, detail="no such upload")
    return FileResponse(matches[0])


@app.get("/shots/{shot_id}/text", response_class=PlainTextResponse)
async def shot_text(shot_id: str, t: str | None = Query(default=None)) -> str:
    _check(t)
    return _load(shot_id).get("ocr_text", "")


@app.get("/feed", response_class=PlainTextResponse)
async def feed(t: str | None = Query(default=None), limit: int = Query(default=10, le=50)) -> str:
    """Plain text of the newest uploads, so an agent reads it with one call."""
    _check(t)
    out = []
    for meta in _recent(limit):
        out.append(
            f"--- {meta['id']}  {meta['created_at']}  {meta['filename']} ---\n"
            f"{meta.get('ocr_text') or '(no text found)'}\n"
        )
    return "\n".join(out) or "(no uploads yet)"


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "12000")))
