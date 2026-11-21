"""The library: the exact recipe behind every generated output.

One SQLite file (outputs/library.db) shared by the web generator and the desktop app. Each row is one
output file plus everything needed to rebuild it: the Prompt Builder state (dropdown values + vision)
when it came from the builder, the prompt as queued, the prompt as rendered, and every setting.
"Import into Prompt Builder" reads a row back so a picture can be tweaked and rendered again.

Files are the source of truth for what exists: rows whose file is gone are hidden, and files made
before the library existed (or outside both apps) get a row on the next listing, with whatever the old
photo_meta.json remembers about them.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import closing
from typing import Any

import addons
from studio_helpers import OUTPUTS_DIR, PHOTOS_DIR, _scan_dir_by_ext

LIBRARY_DB = os.environ.get("GS_LIBRARY_DB", os.path.join(OUTPUTS_DIR, "library.db"))
PHOTO_EXTS = (".jpg", ".jpeg", ".png", ".webp")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS assets (
    path             TEXT PRIMARY KEY,   -- absolute path of the output file
    kind             TEXT NOT NULL,      -- output kind (photo, etc.)
    created          REAL NOT NULL,
    source           TEXT NOT NULL,      -- web, web-builder, desktop, desktop-builder, disk...
    prompt           TEXT NOT NULL DEFAULT '',  -- prompt as queued (form text)
    effective_prompt TEXT NOT NULL DEFAULT '',  -- prompt as rendered (after cleanup / person variety)
    variation        TEXT NOT NULL DEFAULT '',  -- auto person variety added to the prompt, if any
    settings         TEXT NOT NULL DEFAULT '{}',  -- JSON: model/version, size, steps, cfg, seed, negative...
    builder          TEXT,               -- JSON: {"values", "vision", "target", "reconciled_prompt"} or NULL
    reference        TEXT NOT NULL DEFAULT '',  -- reference image path used, if any
    parent           TEXT NOT NULL DEFAULT ''   -- optional parent asset path, if derived from another item
);
CREATE INDEX IF NOT EXISTS assets_kind_created ON assets (kind, created DESC);
"""


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(LIBRARY_DB), exist_ok=True)
    con = sqlite3.connect(LIBRARY_DB, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(_SCHEMA)
    return con


def kind_of(path: str) -> str | None:
    ext = os.path.splitext(path)[1].lower()
    for kind, (_dir, exts) in addons.media_kind_specs(OUTPUTS_DIR, PHOTOS_DIR).items():
        if ext in exts:
            return kind
    return None


def _row(r: sqlite3.Row) -> dict[str, Any]:
    out = dict(r)
    out["settings"] = json.loads(out["settings"] or "{}")
    out["builder"] = json.loads(out["builder"]) if out["builder"] else None
    return out


def record(path: str, *, source: str, prompt: str = "", effective_prompt: str = "", variation: str = "",
           settings: dict | None = None, builder: dict | None = None, reference: str = "", parent: str = "") -> None:
    """Remember how an output file was made (replaces any older row for the same path)."""
    path = os.path.abspath(path)
    kind = kind_of(path)
    if not kind:
        return
    settings = {k: v for k, v in (settings or {}).items() if k not in ("output", "prompt", "image", "ref_image")}
    try:
        created = os.path.getmtime(path)
    except OSError:
        created = time.time()
    with closing(_connect()) as con, con:
        con.execute(
            "INSERT OR REPLACE INTO assets (path, kind, created, source, prompt, effective_prompt, variation, settings,"
            " builder, reference, parent) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (path, kind, created, source, prompt or "", effective_prompt or prompt or "", variation or "",
             json.dumps(settings), json.dumps(builder) if builder else None, reference or "",
             os.path.abspath(parent) if parent else ""),
        )


def get(path: str) -> dict[str, Any] | None:
    with closing(_connect()) as con:
        r = con.execute("SELECT * FROM assets WHERE path = ?", (os.path.abspath(path),)).fetchone()
    return _row(r) if r else None


def forget(path: str) -> None:
    with closing(_connect()) as con, con:
        con.execute("DELETE FROM assets WHERE path = ?", (os.path.abspath(path),))


def list_assets(kind: str, limit: int = 300) -> list[dict[str, Any]]:
    """Newest first; only files that still exist. Adds rows for files the library hasn't seen yet."""
    sync_from_disk(kind)
    with closing(_connect()) as con:
        rows = con.execute("SELECT * FROM assets WHERE kind = ? ORDER BY created DESC", (kind,)).fetchall()
    out = []
    for r in rows:
        if os.path.isfile(r["path"]):
            out.append(_row(r))
            if len(out) >= limit:
                break
    return out


def sync_from_disk(kind: str) -> int:
    """Give every output file on disk a row. Older photos get what photo_meta.json remembers."""
    specs = addons.media_kind_specs(OUTPUTS_DIR, PHOTOS_DIR)
    if kind not in specs:
        return 0
    base_dir, exts = specs[kind]
    files = _scan_dir_by_ext(base_dir, exts)
    with closing(_connect()) as con:
        known = {r[0] for r in con.execute("SELECT path FROM assets WHERE kind = ?", (kind,))}
    new = [f for f in files if os.path.abspath(f["path"]) not in known]
    if not new:
        return 0
    legacy = _legacy_photo_meta() if kind == "photo" else {}
    parent_keys = tuple(addons.REGISTRY.web.get("legacy_parent_keys", ()))
    for f in new:
        meta = legacy.get(os.path.basename(f["path"])) or {}
        settings = dict(meta.get("cfg") or {})
        if meta.get("model") and "model" not in settings:
            settings["model"] = meta["model"]
        if meta.get("seed") is not None and "seed" not in settings:
            settings["seed"] = meta["seed"]
        source = str(meta.get("source") or ("desktop" if meta else "disk"))
        parent_name = next((meta[k] for k in parent_keys if meta.get(k)), "")
        record(f["path"], source=source, prompt=str(meta.get("base_prompt") or ""),
               effective_prompt=str(meta.get("effective_prompt") or meta.get("base_prompt") or ""),
               variation=str(meta.get("variation") or ""), settings=settings,
               parent=os.path.join(PHOTOS_DIR, parent_name) if parent_name else "")
    return len(new)


def _legacy_photo_meta() -> dict[str, dict]:
    from studio_profiles import PHOTO_META_JSON

    try:
        with open(PHOTO_META_JSON, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def builder_state(values: dict | None, vision: str, target: str, reconciled_prompt: str,
                  final_prompt: str = "", llm: str = "", **extra) -> dict | None:
    """The Prompt Builder state worth keeping: real dropdown picks ("None" dropped), the vision,
    what the LLM reconciled, the Final prompt as edited, and which LLM did it."""
    picks = {str(k): str(v) for k, v in (values or {}).items() if v and not str(v).lower().startswith("none")}
    vision = (vision or "").strip()
    if not picks and not vision:
        return None
    llm_k = addons.llm_ui_strings()["result_model_key"]
    chosen = llm or extra.get(llm_k) or ""
    return {"values": picks, "vision": vision, "target": target, "reconciled_prompt": reconciled_prompt or "",
            "final_prompt": final_prompt or reconciled_prompt or "", llm_k: chosen}
