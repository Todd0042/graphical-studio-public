"""Graphical Studio web wrapper.

Single-owner FastAPI app (HMAC-ticket SSO via web/sso.py) in front of the same generators, prompt builder,
and output folders the Tk desktop app uses. Run with:
    .venv-web/bin/uvicorn web.server:create_app --factory --host 127.0.0.1 --port 8040
"""

from __future__ import annotations

import hashlib
import io
import os
import secrets
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from web.config import ROOT_DIR, WEB_DIR, Settings, load_settings

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import addons  # noqa: E402
from wan_compat import analyze_builder_intent  # noqa: E402
import wan_library  # noqa: E402
from wan_models import prompt_llm_options  # noqa: E402
from wan_presets import PRESETS  # noqa: E402
from wan_prompt_catalog import MOTION_FIELDS, PERSON_FIELDS, SCENE_ATTIRE_FIELDS, THEME_FIELDS  # noqa: E402
from wan_studio_helpers import OUTPUTS_DIR, PHOTOS_DIR, extract_thumbnail  # noqa: E402
from wan_templates import delete_template, load_templates, save_template  # noqa: E402

from web.auth import SESSION_COOKIE_NAME, create_session_token, safe_next_path, verify_session_token  # noqa: E402
from web.sso import TicketError, TicketVerifier  # noqa: E402
from web.compose import register_compose_routes  # noqa: E402
from web.jobs import JobQueue  # noqa: E402
from web.specs import (  # noqa: E402
    SpecError, builder_preview, photo_options, prepare_fill, prepare_photo, prepare_reconcile,
    prepare_video, video_options,
)

STATIC_DIR = WEB_DIR / "static"
WEB_THUMB_DIR = ROOT_DIR / ".cache" / "tmp" / "web_thumbs"
PUBLIC_PATHS = {"/login", "/logout", "/auth/sso", "/signed-out", "/api/health", "/robots.txt", "/favicon.ico", "/static/app.css"}
ICON_PATH = ROOT_DIR / "graphical_studio_icon.png"
UPLOAD_MAX_AGE_SEC = 7 * 86400
BUILDER_GROUPS = (
    ("Theme", THEME_FIELDS),
    ("Person", PERSON_FIELDS),
    ("Scene & Attire", SCENE_ATTIRE_FIELDS),
    *((("Motion (video)", MOTION_FIELDS),) if addons.REGISTRY.video_enabled and MOTION_FIELDS else ()),
)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "X-Robots-Tag": "noindex, nofollow",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' blob: data:; media-src 'self'; style-src 'self'; "
        "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
    ),
}


def _is_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "") == "https"


def _resolve_under(base: str, rel: str) -> Path | None:
    """Path of rel inside base, or None if it escapes base or is not a file."""
    root = Path(base).resolve()
    try:
        target = (root / rel).resolve()
    except (OSError, ValueError):
        return None
    if root not in target.parents or not target.is_file():
        return None
    return target


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or load_settings()
    if not cfg.auth_configured:
        raise RuntimeError("Sign-in is not configured: need GS_WEB_SESSION_SECRET in web/.env and ~/.config/dev-sso/secret.")
    tickets = TicketVerifier(cfg.sso_secret_path, cfg.sso_site, cfg.allowed_user)
    cfg.uploads_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(cfg.uploads_dir, 0o700)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.jobs = JobQueue(cfg.jobs_path, str(ROOT_DIR))
        _purge_old_uploads()
        try:
            yield
        finally:
            app.state.jobs.shutdown()

    app = FastAPI(title="Graphical Studio Web", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    def _purge_old_uploads() -> None:
        cutoff = time.time() - UPLOAD_MAX_AGE_SEC
        for p in cfg.uploads_dir.glob("*.png"):
            if p.stat().st_mtime < cutoff:
                p.unlink(missing_ok=True)

    def resolve_upload(token: str) -> str:
        if not token:
            return ""
        if len(token) != 32 or not all(c in "0123456789abcdef" for c in token):
            raise SpecError("Invalid upload reference")
        path = cfg.uploads_dir / f"{token}.png"
        if not path.is_file():
            raise SpecError("Uploaded image expired; upload it again")
        return str(path)

    @app.middleware("http")
    async def gate(request: Request, call_next):
        host = (request.headers.get("host") or "").lower()
        if host not in cfg.allowed_hosts:
            return Response("Unknown host", status_code=421)
        path = request.url.path
        if request.method not in ("GET", "HEAD"):
            origin = request.headers.get("origin")
            if origin and origin.split("://", 1)[-1].lower() != host:
                return _secure(JSONResponse({"detail": "Cross-origin request refused"}, status_code=403))
            if path.startswith("/api/") and request.headers.get("x-gs-csrf") != "1":
                return _secure(JSONResponse({"detail": "Missing CSRF header"}, status_code=403))
        if path not in PUBLIC_PATHS:
            user = verify_session_token(request.cookies.get(SESSION_COOKIE_NAME), cfg.session_secret, cfg.allowed_user)
            if not user:
                if path.startswith("/api/") or path.startswith("/media/"):
                    return _secure(JSONResponse({"detail": "Authentication required"}, status_code=401))
                return _secure(RedirectResponse(f"/login?next={quote(path)}", status_code=303))
        return _secure(await call_next(request))

    def _secure(resp: Response) -> Response:
        for k, v in SECURITY_HEADERS.items():
            resp.headers.setdefault(k, v)
        # no-transform: keeps Cloudflare from injecting its analytics beacon into these private pages
        resp.headers.setdefault("Cache-Control", "no-store, no-transform")
        return resp

    # ---- login -------------------------------------------------------------------------------

    @app.get("/robots.txt")
    def robots() -> Response:
        return Response("User-agent: *\nDisallow: /\n", media_type="text/plain")

    @app.get("/favicon.ico")
    def favicon() -> Response:
        resp = FileResponse(ICON_PATH, media_type="image/png")
        resp.headers["Cache-Control"] = "public, max-age=86400, no-transform"
        return resp

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "service": "graphical-studio-web"}

    # Asset URLs carry a content hash: Cloudflare edge-caches .css/.js, so a deploy must change the URL.
    asset_version = hashlib.sha1(b"".join(
        p.read_bytes() for p in sorted(STATIC_DIR.iterdir()) if p.suffix in (".css", ".js")
    )).hexdigest()[:10]
    login_note = addons.REGISTRY.private_web_defaults.get(
        "login_note", "Sign-in uses your configured SSO provider (owner only)."
    )
    pages = {
        name: (STATIC_DIR / name).read_text(encoding="utf-8")
        .replace("__V__", asset_version)
        .replace("__LOGIN_NOTE__", login_note)
        for name in ("index.html", "login.html")
    }

    @app.get("/login")
    def login(next: str = "/") -> Response:
        # Redirect to the configured SSO hand-off; it returns a one-time ticket to /auth/sso.
        url = f"{cfg.sso_url}?{urlencode({'site': cfg.sso_site, 'next': safe_next_path(next)})}"
        return RedirectResponse(url, status_code=303)

    @app.get("/auth/sso")
    def sso_return(request: Request, ticket: str = "", next: str = "/") -> Response:
        try:
            user = tickets.verify(ticket)
        except TicketError as exc:
            return HTMLResponse(f"<!doctype html><title>Sign-in failed</title><p>Sign-in failed: {exc}.</p>"
                                f'<p><a href="/login">Try again</a></p>', status_code=403)
        resp = RedirectResponse(safe_next_path(next), status_code=303)
        resp.set_cookie(
            SESSION_COOKIE_NAME, create_session_token(user, cfg.session_secret, cfg.session_ttl_seconds),
            max_age=cfg.session_ttl_seconds, httponly=True, samesite="lax", secure=_is_https(request), path="/",
        )
        return resp

    @app.post("/logout")
    def logout() -> Response:
        resp = RedirectResponse("/signed-out", status_code=303)
        resp.delete_cookie(SESSION_COOKIE_NAME, path="/")
        return resp

    @app.get("/signed-out")
    def signed_out() -> Response:
        return HTMLResponse(pages["login.html"])

    # ---- app shell + static ------------------------------------------------------------------

    @app.get("/")
    def index() -> Response:
        return HTMLResponse(pages["index.html"])

    @app.get("/static/{name}")
    def static(name: str) -> Response:
        path = _resolve_under(str(STATIC_DIR), name)
        if not path:
            return Response(status_code=404)
        resp = FileResponse(path)
        resp.headers["Cache-Control"] = "private, max-age=86400, no-transform"  # URL is content-versioned
        return resp

    # ---- status / options --------------------------------------------------------------------

    @app.get("/api/status")
    def status(request: Request) -> dict[str, Any]:
        return {
            "queue": request.app.state.jobs.stats(),
            **(addons.gpu_web_status() or {}),
        }

    @app.get("/api/options")
    def options() -> dict[str, Any]:
        groups = [
            {"group": g, "fields": [{"key": k, "label": label, "options": opts} for k, label, _, opts in fields]}
            for g, fields in BUILDER_GROUPS
        ]
        ui = addons.llm_ui_strings()
        video_on = bool(addons.REGISTRY.video_enabled)
        if video_on and addons.REGISTRY.video_ui_strings:
            ui.update(addons.REGISTRY.video_ui_strings)
        if addons.REGISTRY.gpu_offline_label:
            ui["gpu_offline_label"] = addons.REGISTRY.gpu_offline_label
        if addons.REGISTRY.gpu_active_key:
            ui["gpu_active_key"] = addons.REGISTRY.gpu_active_key
        llm_opts = prompt_llm_options()
        out: dict[str, Any] = {
            "photo": photo_options(),
            **({"video": video_options()} if video_on else {}),
            "features": {"video": video_on},
            "builder": groups,
            "llms": llm_opts, "ui": ui,
            "app_labels": {"graphical_studio": "Graphical Studio", **addons.REGISTRY.gpu_app_labels},
            "presets": [{"name": p["name"], "about": p["about"], "values": p["values"]} for p in PRESETS],
        }
        if ui["api_list_key"] != "llms":
            out[ui["api_list_key"]] = llm_opts
        return out

    @app.post("/api/builder/preview")
    async def builder_preview_route(request: Request) -> Response:
        """Live preview of the prompt the dropdowns + vision make (Python only, no GPU)."""
        body = await request.json()
        if not isinstance(body, dict):
            return JSONResponse({"detail": "Expected a JSON object"}, status_code=400)
        try:
            return JSONResponse(await run_in_threadpool(builder_preview, body))
        except SpecError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)

    # ---- builder -----------------------------------------------------------------------------

    def _values(body: dict) -> dict[str, str]:
        vals = body.get("values")
        if not isinstance(vals, dict):
            return {}
        return {str(k)[:40]: str(v)[:600] for k, v in list(vals.items())[:80]}

    @app.get("/api/templates")
    def templates_list() -> dict[str, Any]:
        return {"templates": load_templates()}

    @app.post("/api/templates")
    async def templates_save(request: Request) -> Response:
        body = await request.json()
        name = str(body.get("name") or "").strip()[:80]
        if not name:
            return JSONResponse({"detail": "Template name required"}, status_code=400)
        saved = save_template(name, _values(body), str(body.get("notes") or "")[:2000])
        return JSONResponse({"saved": saved})

    @app.delete("/api/templates/{name}")
    def templates_delete(name: str) -> dict[str, Any]:
        return {"deleted": delete_template(name)}

    # ---- uploads -----------------------------------------------------------------------------

    @app.post("/api/uploads")
    async def upload(file: UploadFile = File(...)) -> Response:
        raw = await file.read(cfg.max_upload_bytes + 1)
        if len(raw) > cfg.max_upload_bytes:
            return JSONResponse({"detail": "Image too large"}, status_code=413)
        try:
            token = await run_in_threadpool(_store_image, raw, cfg.uploads_dir)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        return JSONResponse({"upload": token})

    register_compose_routes(app, cfg.uploads_dir, resolve_upload, _resolve_under, cfg.max_upload_bytes)

    @app.get("/api/uploads/{token}")
    def upload_preview(token: str) -> Response:
        """Thumbnail source for a re-attached reference (Import into Prompt Builder)."""
        try:
            path = resolve_upload(token)
        except SpecError:
            path = ""
        if not path:
            return Response(status_code=404)
        resp = FileResponse(path, media_type="image/png")
        resp.headers["Cache-Control"] = "private, max-age=3600, no-transform"
        return resp

    # ---- jobs --------------------------------------------------------------------------------

    @app.get("/api/jobs")
    def jobs_list(request: Request) -> dict[str, Any]:
        return {"jobs": request.app.state.jobs.list()}

    @app.get("/api/jobs/{jid}")
    def jobs_get(request: Request, jid: str) -> Response:
        job = request.app.state.jobs.get(jid, with_log=True)
        return JSONResponse(job) if job else JSONResponse({"detail": "Not found"}, status_code=404)

    @app.post("/api/jobs/{kind}")
    async def jobs_submit(request: Request, kind: str) -> Response:
        preparers = {
            "photo": prepare_photo,
            **({"video": prepare_video} if addons.REGISTRY.video_enabled else {}),
            "reconcile": lambda b, _r: prepare_reconcile(b),
            "fill": lambda b, _r: prepare_fill(b),
        }
        if kind not in preparers:
            return JSONResponse({"detail": "Unknown job kind"}, status_code=404)
        body = await request.json()
        if not isinstance(body, dict):
            return JSONResponse({"detail": "Expected a JSON object"}, status_code=400)
        try:
            prepared = await run_in_threadpool(preparers[kind], body, resolve_upload)
            job = request.app.state.jobs.submit(kind, prepared, cfg.max_queued_jobs)
        except SpecError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        except OverflowError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=429)
        return JSONResponse(job, status_code=201)

    @app.post("/api/jobs/{jid}/cancel")
    def jobs_cancel(request: Request, jid: str) -> dict[str, Any]:
        return {"cancelled": request.app.state.jobs.cancel(jid)}

    # ---- gallery -----------------------------------------------------------------------------

    def _asset(path: Path) -> dict[str, Any] | None:
        return wan_library.get(str(path))

    def _media_rows(kind: str) -> list[dict[str, Any]]:
        out = []
        for a in wan_library.list_assets(kind):
            if not a["path"].startswith(OUTPUTS_DIR + os.sep):
                continue  # library rows only ever point inside outputs/, but never serve anything else
            st = os.stat(a["path"])
            item = {"rel": os.path.relpath(a["path"], OUTPUTS_DIR), "name": os.path.basename(a["path"]),
                    "size": f"{st.st_size / 1e6:.1f} MB", "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(a["created"])),
                    "kind": kind, "source": a["source"], "has_builder": bool(a["builder"]),
                    "has_recipe": bool(a["effective_prompt"] or a["builder"])}
            s = a["settings"]
            pp = addons.pair_provider()
            if pp and kind == "photo" and a["effective_prompt"] and s.get("model") and s.get("seed") is not None and s.get("width"):
                item.update(pp.gallery_item_extras(a["effective_prompt"]))
            out.append(item)
        return out

    @app.get("/api/media")
    def media_list(kind: str = "photo") -> Response:
        allowed_kinds = ("photo", "video") if addons.REGISTRY.video_enabled else ("photo",)
        if kind not in allowed_kinds:
            return JSONResponse({"detail": f"kind must be {' or '.join(allowed_kinds)}"}, status_code=400)
        return JSONResponse({"items": _media_rows(kind)})

    @app.get("/api/library/recipe")
    def library_recipe(rel: str) -> Response:
        """Everything behind a gallery item, for Import into Prompt Builder."""
        path = _resolve_under(OUTPUTS_DIR, rel)
        asset = _asset(path) if path else None
        if not asset:
            return JSONResponse({"detail": "Nothing is saved about this file"}, status_code=404)
        ref = Path(asset["reference"]) if asset["reference"] else None
        ref_upload = ref.stem if ref and ref.parent.resolve() == cfg.uploads_dir.resolve() and ref.is_file() else ""
        return JSONResponse({
            "kind": asset["kind"], "name": path.name, "source": asset["source"], "prompt": asset["prompt"],
            "effective_prompt": asset["effective_prompt"], "variation": asset["variation"],
            "settings": asset["settings"], "builder": asset["builder"], "reference_upload": ref_upload,
            "had_reference": bool(asset["reference"]),
        })

    @app.post("/api/media/use-as-reference")
    async def media_use_as_reference(request: Request) -> Response:
        """Attach a gallery photo as the photo-reference or video start image (no re-upload)."""
        body = await request.json()
        path = _resolve_under(PHOTOS_DIR, str(body.get("rel") or "").removeprefix("photos/"))
        if not path or path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
            return JSONResponse({"detail": "Pick a photo from the gallery"}, status_code=404)
        try:
            token, width, height = await run_in_threadpool(_store_image_with_size, path.read_bytes(), cfg.uploads_dir)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        asset = _asset(path) or {}
        prompt = str(asset.get("effective_prompt") or asset.get("prompt") or "")
        ref_mode = "person" if analyze_builder_intent({}, prompt)["has_people"] or not prompt else "background"
        return JSONResponse({"upload": token, "width": width, "height": height, "prompt": prompt,
                             "ref_mode": ref_mode, "name": path.name})

    if (pp := addons.pair_provider()):
        @app.post(pp.route_path)
        async def media_twin(request: Request) -> Response:
            """Queue the matching twin version of a finished web photo."""
            body = await request.json()
            rel = str(body.get("rel") or "")
            path = _resolve_under(OUTPUTS_DIR, rel)
            if not path:
                return JSONResponse({"detail": "Not found"}, status_code=404)
            try:
                plan = pp.prepare(_asset(path), rel)
                job = request.app.state.jobs.submit(pp.kind, plan, cfg.max_queued_jobs)
            except SpecError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=400)
            except OverflowError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=429)
            return JSONResponse(job, status_code=201)

    @app.get("/media/file/{rel:path}")
    def media_file(rel: str, download: bool = False) -> Response:
        path = _resolve_under(OUTPUTS_DIR, rel)
        if not path:
            return Response(status_code=404)
        resp = FileResponse(path, filename=path.name if download else None)
        resp.headers["Cache-Control"] = "private, max-age=3600, no-transform"
        return resp

    @app.get("/media/thumb/{rel:path}")
    async def media_thumb(rel: str) -> Response:
        path = _resolve_under(OUTPUTS_DIR, rel)
        if not path:
            return Response(status_code=404)
        thumb = await run_in_threadpool(_thumbnail_for, path)
        if not thumb:
            return Response(status_code=404)
        resp = FileResponse(thumb, media_type="image/jpeg")
        resp.headers["Cache-Control"] = "private, max-age=86400, no-transform"
        return resp

    @app.delete("/api/media/{rel:path}")
    def media_delete(rel: str) -> Response:
        path = _resolve_under(OUTPUTS_DIR, rel)
        exts = (".jpg", ".jpeg", ".png", ".webp", ".mp4") if addons.REGISTRY.video_enabled else (".jpg", ".jpeg", ".png", ".webp")
        if not path or path.suffix.lower() not in exts:
            return JSONResponse({"detail": "Not found"}, status_code=404)
        path.unlink()
        wan_library.forget(str(path))
        return JSONResponse({"deleted": rel})

    return app


def _store_image_with_size(raw: bytes, uploads_dir: Path) -> tuple[str, int, int]:
    token = _store_image(raw, uploads_dir)
    from PIL import Image

    with Image.open(uploads_dir / f"{token}.png") as img:
        return token, img.width, img.height


def _store_image(raw: bytes, uploads_dir: Path) -> str:
    """Decode with Pillow and re-encode as PNG so only clean pixels reach the generators."""
    from PIL import Image, UnidentifiedImageError

    Image.MAX_IMAGE_PIXELS = 40_000_000
    try:
        with Image.open(io.BytesIO(raw)) as img:
            if img.format not in ("PNG", "JPEG", "WEBP"):
                raise ValueError("Use a PNG, JPEG or WebP image")
            img.load()
            clean = img.convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError(f"Not a readable image: {exc}")
    token = secrets.token_hex(16)
    clean.save(uploads_dir / f"{token}.png", "PNG")
    return token


def _thumbnail_for(path: Path) -> str | None:
    if path.suffix.lower() == ".mp4":
        return extract_thumbnail(str(path))
    from PIL import Image

    st = path.stat()
    key = hashlib.sha1(f"{path}:{st.st_mtime_ns}:{st.st_size}".encode()).hexdigest()[:16]
    WEB_THUMB_DIR.mkdir(parents=True, exist_ok=True)
    thumb = WEB_THUMB_DIR / f"{key}.jpg"
    if not thumb.is_file():
        with Image.open(path) as img:
            img.thumbnail((480, 480))
            img.convert("RGB").save(thumb, "JPEG", quality=82)
    return str(thumb)
