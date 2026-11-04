"""Screenshot intake for conversations that cannot receive images directly.

Upload a screenshot and the server stores it and runs OCR over it. The extracted
text is what a text-only agent reads: the image bytes never reach the model, only
the words inside them.

Two ways to run it:

* Standalone, on its own port — `python screenshot_server.py` (see run.sh and
  Dockerfile in this directory).
* Mounted into another FastAPI app under a path prefix, with
  `create_app(prefix="/shots")`. That is how the downloader deployment exposes
  it, so a single-service host needs no second port.

Client-side URLs are built from `location.pathname`, so the page works under any
prefix without the template knowing what it is.

Set UPLOAD_TOKEN to require `?t=<token>` on every route except /health. In the
mounted form the token is mandatory, because the host is public.
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

MAX_BYTES = int(os.environ.get("MAX_UPLOAD_MB", "25")) * 1024 * 1024
DEFAULT_DIR = Path(os.environ.get("SCREENSHOT_DIR", "/tmp/screenshot-server"))

ALLOWED = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
}


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
// Derived from the page URL so the same file works at "/" standalone and at
// "/shots/" when mounted, without the server templating a path in.
const BASE = location.pathname.replace(/\\/?$/, "/");
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
  img.src = BASE + shot.id + qs;
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
    const res = await fetch(BASE + "upload" + qs, { method: "POST", body: form });
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


def create_app(
    token: str | None = None,
    upload_dir: Path | None = None,
) -> FastAPI:
    """Build the screenshot app.

    Routes are always declared at the app's own root. Mounting this app at a
    path prefix is what exposes it under that prefix — `app.mount("/shots",
    create_app(...))` makes the page reachable at /shots/ and the API at
    /shots/upload, with no second port. Declaring the prefix in the routes as
    well would double it, because Starlette strips the mount path first.

    The page builds its URLs from `location.pathname`, so it works at "/" and
    under any mount without knowing which it is.

    `token` may be None to leave the routes open, which is only appropriate on a
    private network.
    """
    token = (token or "").strip() or None
    uploads = Path(upload_dir) if upload_dir else DEFAULT_DIR / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)

    def guard(t: str | None) -> None:
        if token and t != token:
            raise HTTPException(status_code=401, detail="bad or missing token")

    def meta_path(shot_id: str) -> Path:
        return uploads / f"{shot_id}.json"

    def load(shot_id: str) -> dict:
        path = meta_path(shot_id)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="no such upload")
        return json.loads(path.read_text())

    def recent(limit: int) -> list[dict]:
        metas = []
        for path in uploads.glob("*.json"):
            try:
                metas.append(json.loads(path.read_text()))
            except (json.JSONDecodeError, OSError):
                continue
        metas.sort(key=lambda m: m["created_at"], reverse=True)
        return metas[:limit]

    app = FastAPI(title="screenshot-server", version="1.0.0", docs_url=None, redoc_url=None)

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
            "auth": bool(token),
            "uploads": len(list(uploads.glob("*.json"))),
        }

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index(t: str | None = Query(default=None)) -> str:
        guard(t)
        page = PAGE.replace("__MAX__", str(MAX_BYTES // (1024 * 1024)))
        return page.replace("__TOKEN__", token or "")

    @app.post("/upload")
    async def upload(
        t: str | None = Query(default=None),
        files: list[UploadFile] = File(...),
    ) -> dict:
        guard(t)
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

            shot_id = f"{int(time.time())}-{secrets.token_hex(3)}"
            (uploads / f"{shot_id}{ext}").write_bytes(data)
            text, error = _ocr(data)
            meta = {
                "id": shot_id,
                "filename": item.filename,
                "content_type": item.content_type,
                "bytes": len(data),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "ocr_text": text,
                "ocr_error": error,
            }
            meta_path(shot_id).write_text(json.dumps(meta, indent=2))
            saved.append(meta)
        return {"uploads": saved}

    @app.get("/list")
    async def listing(
        t: str | None = Query(default=None), limit: int = Query(default=20, le=100)
    ) -> dict:
        guard(t)
        return {"shots": recent(limit)}

    @app.get("/feed", response_class=PlainTextResponse)
    async def feed(
        t: str | None = Query(default=None), limit: int = Query(default=10, le=50)
    ) -> str:
        """Plain text of the newest uploads, so an agent reads it with one call."""
        guard(t)
        out = []
        for meta in recent(limit):
            out.append(
                f"--- {meta['id']}  {meta['created_at']}  {meta['filename']} ---\n"
                f"{meta.get('ocr_text') or '(no text found)'}\n"
            )
        return "\n".join(out) or "(no uploads yet)"

    # Dynamic routes are declared last so the literal paths above win.
    @app.get("/{shot_id}/text", response_class=PlainTextResponse)
    async def shot_text(shot_id: str, t: str | None = Query(default=None)) -> str:
        guard(t)
        return load(shot_id).get("ocr_text", "")

    @app.get("/{shot_id}")
    async def shot(shot_id: str, t: str | None = Query(default=None)) -> FileResponse:
        guard(t)
        if not re.fullmatch(r"[0-9a-f-]+", shot_id):
            raise HTTPException(status_code=400, detail="bad id")
        matches = [m for m in uploads.glob(f"{shot_id}.*") if m.suffix != ".json"]
        if not matches:
            raise HTTPException(status_code=404, detail="no such upload")
        return FileResponse(matches[0])

    return app


app = create_app(token=os.environ.get("UPLOAD_TOKEN"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "12000")))
