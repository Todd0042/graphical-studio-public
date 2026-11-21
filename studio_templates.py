"""Persistent Prompt Builder templates (dropdown selections + custom text)."""

import json
import os
import time

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_PATH = os.path.join(ROOT_DIR, "builder_templates.json")
AUTO_PREFIX = "Auto"
MAX_AUTO_TEMPLATES = 30


def load_templates(path: str = TEMPLATES_PATH) -> list[dict]:
    """Return templates newest-first: [{"name", "values", "notes", "auto", "saved"}]."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    items = data.get("templates", []) if isinstance(data, dict) else []
    return [t for t in items if isinstance(t, dict) and t.get("name") and isinstance(t.get("values"), dict)]


def _write(templates: list[dict], path: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"templates": templates}, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _same(t: dict, values: dict, notes: str) -> bool:
    return t.get("values") == values and (t.get("notes") or "") == (notes or "")


def save_template(name: str, values: dict, notes: str = "", auto: bool = False, path: str = TEMPLATES_PATH) -> str | None:
    """Save (or overwrite by name) a template and move it to the top. Returns the stored name, or None if skipped.

    Auto-saves are skipped when an identical template already exists under a user-given name; an identical
    earlier auto-save is replaced so repeated sends don't pile up duplicates. Only the newest
    MAX_AUTO_TEMPLATES auto-saves are kept; named templates are never pruned.
    """
    name = name.strip()
    if not name:
        return None
    values = {k: str(v) for k, v in values.items()}
    templates = load_templates(path)
    if auto:
        if any(not t.get("auto") and _same(t, values, notes) for t in templates):
            return None
        templates = [t for t in templates if not (t.get("auto") and _same(t, values, notes))]
    templates = [t for t in templates if t["name"] != name]
    templates.insert(0, {"name": name, "values": values, "notes": notes or "", "auto": bool(auto), "saved": time.strftime("%Y-%m-%d %H:%M:%S")})
    autos = [t for t in templates if t.get("auto")]
    if len(autos) > MAX_AUTO_TEMPLATES:
        drop = {id(t) for t in autos[MAX_AUTO_TEMPLATES:]}
        templates = [t for t in templates if id(t) not in drop]
    _write(templates, path)
    return name


def auto_save_template(kind: str, values: dict, notes: str = "", path: str = TEMPLATES_PATH) -> str | None:
    """Auto-save the builder state when sending a generated prompt."""
    name = f"{AUTO_PREFIX} · {kind} · {time.strftime('%Y-%m-%d %H:%M:%S')}"
    return save_template(name, values, notes, auto=True, path=path)


def delete_template(name: str, path: str = TEMPLATES_PATH) -> bool:
    templates = load_templates(path)
    kept = [t for t in templates if t["name"] != name]
    if len(kept) == len(templates):
        return False
    _write(kept, path)
    return True


def get_template(name: str, path: str = TEMPLATES_PATH) -> dict | None:
    return next((t for t in load_templates(path) if t["name"] == name), None)
