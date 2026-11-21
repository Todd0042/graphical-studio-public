"""Compose: cut a subject out of a photo, place it on a background, flatten, save.

The browser does all the layout (background presets, dragging, scaling, flattening) on a canvas;
the server only cuts subjects out (cutout.py: BiRefNet / anime ISNet on the CPU, so no GPU turn) and
saves the flattened result into outputs/photos with a library row. Layers keep their transparency.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import secrets
import time
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

import studio_library
from studio_helpers import OUTPUTS_DIR, PHOTOS_DIR, ROOT_DIR, VENV_PYTHON

CUTOUT_SCRIPT = os.path.join(ROOT_DIR, "cutout.py")
CUTOUT_MODELS = ("general", "anime", "portrait")
CUTOUT_TIMEOUT_SEC = 300
MAX_SAVE_BYTES = 64 * 1024 * 1024
MAX_RECIPE_BYTES = 64 * 1024


def store_layer_image(raw: bytes, uploads_dir: Path) -> tuple[str, int, int]:
    """Decode with Pillow (PNG/JPEG/WebP only) and re-encode as PNG, keeping transparency."""
    from PIL import Image, UnidentifiedImageError

    Image.MAX_IMAGE_PIXELS = 40_000_000
    try:
        with Image.open(io.BytesIO(raw)) as img:
            if img.format not in ("PNG", "JPEG", "WEBP"):
                raise ValueError("Use a PNG, JPEG or WebP image")
            img.load()
            clean = img.convert("RGBA" if ("A" in img.getbands() or "transparency" in img.info) else "RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError(f"Not a readable image: {exc}")
    token = secrets.token_hex(16)
    clean.save(uploads_dir / f"{token}.png", "PNG")
    return token, clean.width, clean.height


def register_compose_routes(app: FastAPI, uploads_dir: Path, resolve_upload: Callable[[str], str],
                            resolve_under: Callable[[str, str], Path | None], max_upload_bytes: int) -> None:
    cutout_lock = asyncio.Lock()  # one cutout at a time: each one uses most of the CPU

    @app.post("/api/compose/upload")
    async def compose_upload(file: UploadFile = File(...)) -> Response:
        """A layer from a dropped file (transparency kept)."""
        raw = await file.read(max_upload_bytes + 1)
        if len(raw) > max_upload_bytes:
            return JSONResponse({"detail": "Image too large"}, status_code=413)
        try:
            token, w, h = await run_in_threadpool(store_layer_image, raw, uploads_dir)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        return JSONResponse({"upload": token, "width": w, "height": h})

    @app.post("/api/compose/from-gallery")
    async def compose_from_gallery(request: Request) -> Response:
        """A layer (or background) from a gallery photo."""
        body = await request.json()
        path = resolve_under(OUTPUTS_DIR, str((body or {}).get("rel") or ""))
        if not path or path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
            return JSONResponse({"detail": "Pick a photo from the gallery"}, status_code=404)
        try:
            token, w, h = await run_in_threadpool(store_layer_image, path.read_bytes(), uploads_dir)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        return JSONResponse({"upload": token, "width": w, "height": h, "name": path.name})

    @app.post("/api/compose/cutout")
    async def compose_cutout(request: Request) -> Response:
        """Remove the background of a layer image; returns a new transparent, subject-cropped layer."""
        body = await request.json()
        model = str((body or {}).get("model") or "general")
        if model not in CUTOUT_MODELS:
            return JSONResponse({"detail": "Unknown cutout model"}, status_code=400)
        try:
            src = resolve_upload(str((body or {}).get("upload") or ""))
        except Exception as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        if not src:
            return JSONResponse({"detail": "Nothing to cut out"}, status_code=400)
        token = secrets.token_hex(16)
        dst = uploads_dir / f"{token}.png"
        async with cutout_lock:
            proc = await asyncio.create_subprocess_exec(
                VENV_PYTHON, CUTOUT_SCRIPT, "--input", src, "--output", str(dst), "--model", model,
                cwd=ROOT_DIR, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                out, err = await asyncio.wait_for(proc.communicate(), CUTOUT_TIMEOUT_SEC)
            except asyncio.TimeoutError:
                proc.kill()
                return JSONResponse({"detail": "Cutout took too long"}, status_code=504)
        if proc.returncode != 0 or not dst.is_file():
            tail = (err or b"").decode(errors="replace").strip().splitlines()[-1:] or ["unknown error"]
            return JSONResponse({"detail": f"Cutout failed: {tail[0][:300]}"}, status_code=500)
        size = json.loads((out or b"{}").decode().strip().splitlines()[-1])
        return JSONResponse({"upload": token, "width": size["width"], "height": size["height"]})

    @app.post("/api/compose/save")
    async def compose_save(image: UploadFile = File(...), recipe: str = Form("")) -> Response:
        """Save the flattened picture into the gallery (outputs/photos) with a library row."""
        from PIL import Image, UnidentifiedImageError

        raw = await image.read(MAX_SAVE_BYTES + 1)
        if len(raw) > MAX_SAVE_BYTES:
            return JSONResponse({"detail": "Picture too large"}, status_code=413)
        if len(recipe) > MAX_RECIPE_BYTES:
            return JSONResponse({"detail": "Layout too large"}, status_code=413)
        try:
            layout = json.loads(recipe) if recipe else {}
            if not isinstance(layout, dict):
                raise ValueError("layout must be an object")
        except ValueError as exc:
            return JSONResponse({"detail": f"Bad layout: {exc}"}, status_code=400)

        def write() -> Path:
            Image.MAX_IMAGE_PIXELS = 40_000_000
            with Image.open(io.BytesIO(raw)) as img:
                if img.format != "PNG":
                    raise ValueError("Expected a PNG")
                img.load()
                os.makedirs(PHOTOS_DIR, exist_ok=True)
                path = Path(PHOTOS_DIR) / f"compose_{time.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(2)}.png"
                img.convert("RGBA" if "A" in img.getbands() else "RGB").save(path, "PNG")
            studio_library.record(str(path), source="compose", settings={"compose": layout})
            return path

        try:
            path = await run_in_threadpool(write)
        except (ValueError, UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            return JSONResponse({"detail": f"Could not save: {exc}"}, status_code=400)
        return JSONResponse({"rel": os.path.relpath(path, OUTPUTS_DIR), "name": path.name}, status_code=201)
