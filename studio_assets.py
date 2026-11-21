"""Asset Studio engine: icons, backgrounds, textures and sprites from a one-line brief.

Flow (shared by any front end):
  1. expand_brief(brief, kind, repo)  -> the brief "fluffed up" into a concept plus a value for every
     field of that asset kind (style, palette, platform, lighting...). An LLM does it when one is
     installed; otherwise a keyword matcher does. With a repo path, the repo is skimmed first
     (scan_repo: name, description, README, languages, brand colours, existing icons) and fed in.
  2. The creator edits any field (every field is free text with suggestions).
  3. analyze(kind, fields, concept)   -> the image model, every render setting, the post-processing
     (cut-out, tiling, pixel grid, final size, icon size exports) and the final prompt, written in the
     style that model wants. Each choice comes with a reason.
  4. The creator edits that too, then build_command(plan) gives the generate_asset.py argv.

LLM calls go to allow-listed Ollama instruct models (JSON mode), or a registered extension provider.
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
import urllib.request
from collections import Counter
from datetime import datetime

import addons
from generate_asset import ASSET_MODELS, model_installed

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(ROOT_DIR, "outputs", "assets")
ASSET_SCRIPT = os.path.join(ROOT_DIR, "generate_asset.py")
VENV_PYTHON = os.path.join(ROOT_DIR, ".venv", "bin", "python")
OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
if not OLLAMA_URL.startswith("http"):
    OLLAMA_URL = "http://" + OLLAMA_URL

# ── Asset kinds and their fields ──────────────────────────────────────────────
# Field: (key, label, suggestions, tooltip). Every field is free text; suggestions are just a start.
# "" means "leave it out of the prompt".
_QUALITY = ("quality", "Quality vs Speed", ["Best quality", "Balanced", "Fast draft"],
            "Best quality = Flux dev / full steps. Fast draft = Flux schnell (4 steps) or fewer steps.")
_AVOID = ("avoid", "Avoid", ["", "text, letters, watermark", "people, faces", "clutter, busy details", "photorealism"],
          "Things that must not appear (added as 'without ...' for FLUX/Qwen-Image or negative tags).")
_EXTRA = ("extra", "Extra Details", [""], "Anything else to add to the prompt verbatim.")

FIELDS: dict[str, list[tuple[str, str, list[str], str]]] = {
    "icon": [
        ("subject", "Main Motif", [""], "What the icon literally shows (e.g. a glowing </> bracket fused with a cloud)."),
        ("concept", "Metaphor / Meaning", [""], "What it should communicate (remote, fast, friendly...)."),
        ("style", "Icon Style", ["Modern flat vector with soft gradients", "Flat vector (solid colors)", "Glassmorphism (frosted glass)",
                                 "Soft 3D glossy", "3D clay render", "Isometric 3D", "Line icon (outline)", "Duotone",
                                 "Skeuomorphic realistic", "Neon glow", "Paper cut layers", "Low-poly", "Pixel art",
                                 "Anime chibi mascot", "Hand-drawn sketch"], "Rendering look."),
        ("platform", "Platform Conventions", ["Linux desktop (freedesktop / Papirus-like)", "macOS (Big Sur squircle, soft 3D)",
                                              "Windows 11 Fluent", "Android adaptive icon", "iOS app icon", "Web favicon / PWA",
                                              "Game item / ability icon", "Generic app icon"], "Shape and depth rules the OS expects."),
        ("shape", "Container Shape", ["Rounded square (squircle)", "Circle", "Freeform (no container)", "Rounded rectangle badge",
                                      "Shield", "Hexagon"], "The plate the motif sits on."),
        ("palette", "Color Palette", ["Deep indigo with electric cyan", "Sunset orange to magenta", "Teal and mint",
                                      "Monochrome with one accent color", "Pastel", "Black and neon green (terminal)",
                                      "Warm amber and charcoal"], "Colors; repo brand colors are filled in when the repo is read."),
        ("background", "Background", ["Transparent (cut out)", "Plain white", "Plain dark", "Soft gradient"],
         "Transparent = rendered on white, then cut out to a PNG with alpha."),
        ("lighting", "Depth & Lighting", ["Flat, no shadows", "Soft long shadow", "Subtle inner glow", "Soft studio 3D lighting",
                                          "Rim light glow"], ""),
        ("detail", "Detail Level", ["Minimal (reads at 16px)", "Moderate", "Detailed (large sizes only)"],
         "Icons get small: minimal shapes survive 16-32 px."),
        ("mood", "Mood", ["Friendly", "Professional", "Playful", "Futuristic", "Hacker / terminal", "Calm", "Bold"], ""),
        ("text", "Text on Icon", ["None", "Single letter monogram", "Short word (Flux only)"], "Diffusion text is unreliable; Flux can do 1-5 letters."),
        ("outline", "Outline", ["None", "Thin outline", "Thick sticker outline"], ""),
        ("exports", "Export Sizes", ["16,24,32,48,64,128,256,512 (Linux hicolor)", "16,32,48,256 (Windows .ico)",
                                     "16,32,64,128,256,512,1024 (macOS)", "48,72,96,144,192,512 (Android / PWA)",
                                     "16,32,48,180,192,512 (favicon set)", "None (master only)"], "Square PNGs (+ .ico) next to the master."),
        _QUALITY, _AVOID, _EXTRA,
    ],
    "background": [
        ("subject", "Scene", [""], "The place itself."),
        ("focal", "Focal Point / Key Elements", [""], "Things that must be in it (a cottage, a pine tree...)."),
        ("style", "Art Style", ["Photorealistic", "Cinematic matte painting", "Painterly oil painting", "Soft watercolor",
                                "Hand-painted anime landscape", "Flat vector illustration", "Low-poly 3D", "Pixel art",
                                "Synthwave retro", "Minimal abstract gradient", "Dark tech pattern"], ""),
        ("use", "Used For", ["Desktop wallpaper (16:9)", "Ultrawide wallpaper (21:9)", "Phone wallpaper (9:16)", "Website hero",
                             "App / IDE background (subdued)", "Login / splash screen", "Game background (parallax-friendly)",
                             "Social banner (3:1)", "Square"], "Sets the canvas and final size."),
        ("time", "Time of Day", ["Midday", "Golden hour", "Sunrise", "Sunset", "Blue hour", "Night", "Overcast daylight"], ""),
        ("weather", "Weather / Atmosphere", ["Clear sky", "A few fluffy clouds", "Light haze", "Fog", "Rain", "Snow", "Storm clouds"], ""),
        ("season", "Season", ["Summer", "Spring", "Autumn", "Winter", ""], ""),
        ("lighting", "Lighting", ["Bright natural sunlight", "Warm soft light", "Dramatic rim light", "Soft diffuse light",
                                  "Volumetric god rays", "Neon glow"], ""),
        ("palette", "Color Palette", ["Natural vivid greens and blues", "Warm golden tones", "Cool muted blues", "Pastel",
                                      "Teal and orange", "Monochrome", "Dark with neon accents"], ""),
        ("camera", "Camera / Composition", ["Wide panoramic, eye level", "Low angle looking up", "Aerial view", "Rule of thirds",
                                            "Symmetrical centered", "Long telephoto compression"], ""),
        ("depth", "Depth", ["Deep focus, sharp to the horizon", "Atmospheric perspective haze", "Shallow depth of field", "Layered parallax depth"], ""),
        ("space", "Room for UI / Text", ["None needed", "Calm empty area on the left", "Calm empty area on the right",
                                         "Calm open sky at the top", "Low-contrast center"], "Keeps icons or text readable on top."),
        ("mood", "Mood", ["Peaceful", "Cozy", "Epic", "Mysterious", "Cheerful", "Melancholic", "Energetic"], ""),
        ("detail", "Detail Level", ["Highly detailed", "Moderate", "Minimal / clean"], ""),
        ("final", "Final Size", ["1920x1080", "2560x1440", "3840x2160", "3440x1440", "1080x1920", "1500x500", "2048x2048", "Same as render"],
         "The render is ~1 MP, then resized (Lanczos) and cover-cropped to this."),
        _QUALITY, _AVOID, _EXTRA,
    ],
    "texture": [
        ("subject", "Material", [""], "e.g. mossy cobblestone, brushed steel, oak planks."),
        ("style", "Style", ["Photoreal PBR albedo", "Stylized hand-painted", "Pixel art tile", "Cartoon flat", "Abstract pattern"], ""),
        ("tiling", "Tiling", ["Seamless both directions", "Seamless horizontally only"], "Seamless texture tile layout."),
        ("scale", "Scale", ["Close-up macro", "Medium (about 1 m square)", "Large area"], ""),
        ("palette", "Color Palette", ["Natural", "Warm", "Cool", "Desaturated", "Vibrant"], ""),
        ("lighting", "Lighting", ["Flat, even, no shadows (albedo)", "Soft top-down light"], "Flat is best for game materials."),
        ("detail", "Detail Level", ["Highly detailed", "Moderate", "Simple"], ""),
        ("final", "Final Size", ["1024x1024", "2048x2048", "512x512"], ""),
        _QUALITY, _AVOID, _EXTRA,
    ],
    "sprite": [
        ("subject", "Subject", [""], "The item / character / UI element."),
        ("style", "Style", ["Hand-painted game art", "Flat vector", "Pixel art", "Anime / cel shaded", "3D render", "Cartoon"], ""),
        ("view", "View", ["Front view", "Side view", "Three-quarter view", "Isometric", "Top-down"], ""),
        ("background", "Background", ["Transparent (cut out)", "Plain white", "Plain dark"], ""),
        ("palette", "Color Palette", ["Vibrant", "Muted", "Fantasy jewel tones", "Sci-fi cyan and steel"], ""),
        ("outline", "Outline", ["None", "Thin dark outline", "Thick sticker outline"], ""),
        ("detail", "Detail Level", ["Minimal", "Moderate", "Detailed"], ""),
        ("final", "Final Size", ["512x512", "1024x1024", "256x256", "128x128", "64x64", "32x32"], ""),
        _QUALITY, _AVOID, _EXTRA,
    ],
    "frame": [
        ("subject", "Frame Type", ["Chat / dialogue box", "Speech bubble", "Menu panel", "Window (with title bar)", "Card (portrait)",
                                   "Button", "Inventory slot", "Tooltip", "Banner ribbon", "HUD bar", "Nameplate"],
         "What the frame is for; sets the canvas shape."),
        ("theme", "Theme", ["Fantasy RPG (gold and dark wood)", "Sci-fi HUD (holographic)", "Cyberpunk neon", "Clean modern UI",
                            "Glassmorphism", "Retro JRPG", "Steampunk brass", "Parchment and ink", "Cute pastel",
                            "Art deco noir", "Gothic horror"], ""),
        ("style", "Render Style", ["Hand-painted game UI", "Flat vector", "Pixel art", "3D beveled", "Glossy", "Minimal line art"], ""),
        ("border", "Border", ["Ornate filigree", "Thin clean line", "Thick beveled rim", "Double line", "Riveted metal plates",
                              "Glowing edges", "Carved wood", "Rope", "Soft rounded"], ""),
        ("corners", "Corners", ["Ornamented corner pieces", "Rounded", "Sharp", "Chamfered (cut)", "Accent on one corner"], ""),
        ("center", "Center", ["Transparent (hollow)", "Solid dark panel", "Dark translucent-look panel", "Parchment texture",
                              "Light panel"], "Transparent = rendered flat and empty, then hollowed out to alpha."),
        ("parts", "Extra Parts", ["None", "Title plaque at top", "Title bar with close button", "Speech tail at bottom-left",
                                  "Header tab", "Divider line", "Name tag on top-left"], ""),
        ("background", "Outside", ["Transparent (cut out)", "Plain white", "Plain dark"], ""),
        ("palette", "Color Palette", ["Gold and deep brown", "Steel and cyan", "Magenta and cyan neon", "White and soft grey",
                                      "Pastel pink and lilac", "Black and gold", "Bone and crimson"], ""),
        ("detail", "Detail Level", ["Minimal", "Moderate", "Highly ornate"], ""),
        ("final", "Final Size", ["Auto (by frame type)", "1200x500", "640x936", "1200x800", "750x1050", "600x200", "256x256"],
         "Auto picks a size that fits the frame type."),
        _QUALITY, _AVOID, _EXTRA,
    ],
}
KIND_LABELS = {"icon": "Icon / App Logo", "background": "Background / Wallpaper", "texture": "Seamless Texture / Tile",
               "sprite": "Sprite / Game Item", "frame": "UI Frame (chat box, menu, window, card...)"}
FIELD_LABELS = {k: {f[0]: f[1] for f in fs} for k, fs in FIELDS.items()}

_KIND_WORDS = {
    "icon": ("icon", "logo", "favicon", "app icon", "emblem", "badge", "glyph"),
    "texture": ("texture", "seamless", "tileable", "tile ", "tiles", "material", "pattern"),
    "sprite": ("sprite", "item", "game asset", "character", "prop", "pickup", "weapon", "potion"),
    "frame": ("frame", "chat box", "chatbox", "dialogue box", "dialog box", "text box", "textbox", "speech bubble", "menu",
              "window", "card", "panel", "button", "tooltip", "nameplate", "hud", "border", "ui ", "inventory slot"),
    "background": ("background", "wallpaper", "backdrop", "scene", "landscape", "hero image", "banner", "splash"),
}


_FRAME_CANVAS = {  # frame type -> (render canvas ~1 MP, default final size)
    "chat": ((1536, 640), "1200x500"), "speech": ((1344, 768), "960x540"), "menu": ((832, 1216), "640x936"),
    "window": ((1344, 896), "1200x800"), "card": ((896, 1216), "750x1050"), "button": ((1536, 512), "600x200"),
    "slot": ((1024, 1024), "256x256"), "tooltip": ((1344, 768), "640x360"), "banner": ((1536, 512), "1200x400"),
    "hud": ((1792, 576), "1200x384"), "nameplate": ((1536, 512), "600x200"),
}


def detect_kind(brief: str) -> str:
    low = f" {(brief or '').lower()} "
    scores = {k: sum(low.count(w) for w in ws) for k, ws in _KIND_WORDS.items()}
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] else "background"


# ── Repo reading ──────────────────────────────────────────────────────────────
_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", "target", "__pycache__", ".next", ".cache",
              "vendor", "out", ".idea", ".vscode", "coverage", ".mypy_cache", ".tox", "site-packages"}
_LANG_EXT = {".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript/React", ".jsx": "React",
             ".rs": "Rust", ".go": "Go", ".java": "Java", ".kt": "Kotlin", ".swift": "Swift", ".c": "C", ".cpp": "C++",
             ".cs": "C#", ".rb": "Ruby", ".php": "PHP", ".lua": "Lua", ".gd": "GDScript", ".dart": "Dart", ".vue": "Vue",
             ".svelte": "Svelte", ".sh": "Shell", ".zig": "Zig"}
_STYLE_EXT = (".css", ".scss", ".sass", ".less", ".svelte", ".vue", ".tsx", ".jsx", ".html", ".qss", ".toml", ".json")
_HEX = re.compile(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")


def _read(path: str, limit: int) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""


def _is_greyish(hexv: str) -> bool:
    if len(hexv) == 3:
        hexv = "".join(c * 2 for c in hexv)
    r, g, b = (int(hexv[i:i + 2], 16) for i in (0, 2, 4))
    return max(r, g, b) - min(r, g, b) < 28


def scan_repo(path: str, max_files: int = 5000) -> dict:
    """Skim a repo for what an asset should know: name, description, README, languages, brand colours,
    dependencies and existing icons/logos. Returns {"name", "description", "languages", "colors", "keywords",
    "existing_art", "summary"} where summary is a compact text block for an LLM (<= ~6 KB)."""
    path = os.path.abspath(os.path.expanduser(path or ""))
    if not os.path.isdir(path):
        raise ValueError(f"Not a folder: {path}")
    name, description, deps = os.path.basename(path), "", []
    pj = os.path.join(path, "package.json")
    if os.path.isfile(pj):
        try:
            data = json.loads(_read(pj, 200_000))
            name = data.get("productName") or data.get("name") or name
            description = data.get("description") or ""
            deps = sorted({*data.get("dependencies", {}), *data.get("devDependencies", {})})[:40]
        except ValueError:
            pass
    for fn in ("pyproject.toml", "Cargo.toml"):
        txt = _read(os.path.join(path, fn), 50_000)
        if txt:
            m = re.search(r'^\s*name\s*=\s*"([^"]+)"', txt, re.M)
            d = re.search(r'^\s*description\s*=\s*"([^"]+)"', txt, re.M)
            name = m.group(1) if m and name == os.path.basename(path) else name
            description = description or (d.group(1) if d else "")
            deps += re.findall(r'^\s*"?([A-Za-z0-9_.-]+)"?\s*[=><~]', txt.split("dependencies", 1)[-1], re.M)[:30]
    readme = ""
    for fn in ("README.md", "README.rst", "README.txt", "README", "readme.md"):
        readme = _read(os.path.join(path, fn), 4000)
        if readme:
            break
    if not description and readme:
        paras = [p.strip() for p in re.split(r"\n\s*\n", re.sub(r"<[^>]+>|!\[[^\]]*\]\([^)]*\)", "", readme))
                 if p.strip() and not p.strip().startswith(("#", "[", "```", "|"))]
        description = paras[0][:300] if paras else ""
    heading = re.search(r"^#\s+(.+)$", readme, re.M)
    if heading and name == os.path.basename(path):
        name = re.sub(r"[`*_]", "", heading.group(1)).strip()[:60]

    langs, colors, art, top = Counter(), Counter(), [], []
    seen = 0
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        rel_dir = os.path.relpath(dirpath, path)
        if rel_dir == ".":
            top = sorted(dirnames)[:25] + sorted(filenames)[:25]
        for fn in filenames:
            seen += 1
            if seen > max_files:
                break
            ext = os.path.splitext(fn)[1].lower()
            if ext in _LANG_EXT:
                langs[_LANG_EXT[ext]] += 1
            low = fn.lower()
            if ext in (".png", ".svg", ".ico", ".icns", ".webp") and any(w in low for w in ("icon", "logo", "brand", "favicon", "mark")):
                art.append(os.path.normpath(os.path.join(rel_dir, fn)))
            if ext in _STYLE_EXT and (ext not in (".toml", ".json") or any(w in low for w in ("theme", "tailwind", "color", "palette", "brand"))):
                for h in _HEX.findall(_read(os.path.join(dirpath, fn), 200_000)):
                    if not _is_greyish(h):
                        h6 = h if len(h) == 6 else "".join(c * 2 for c in h)
                        colors["#" + h6.lower()] += 1
        if seen > max_files:
            break
    top_colors = [c for c, _ in colors.most_common(5)]
    words = Counter(w for w in re.findall(r"[a-z]{4,}", f"{name} {description} {readme}".lower())
                    if w not in {"this", "that", "with", "your", "from", "have", "will", "into", "using", "install",
                                 "license", "https", "github", "http", "readme", "the", "and", "for", "run", "make"})
    keywords = [w for w, _ in words.most_common(14)]
    summary = "\n".join(x for x in (
        f"PROJECT: {name}",
        f"DESCRIPTION: {description}" if description else "",
        f"LANGUAGES: {', '.join(l for l, _ in langs.most_common(5))}" if langs else "",
        f"DEPENDENCIES: {', '.join(deps[:30])}" if deps else "",
        f"BRAND / UI COLORS FOUND: {', '.join(top_colors)}" if top_colors else "",
        f"EXISTING ICONS/LOGOS: {', '.join(art[:8])}" if art else "",
        f"TOP-LEVEL: {', '.join(top)}" if top else "",
        "README (start):\n" + readme[:2600].strip() if readme else "",
    ) if x)
    return {"path": path, "name": name, "description": description, "languages": [l for l, _ in langs.most_common(5)],
            "colors": top_colors, "keywords": keywords, "existing_art": art[:20], "summary": summary[:6500]}


# ── LLM choice and calls ──────────────────────────────────────────────────────
# Core supports only allow-listed Ollama instruct models from models.json (unless an extension
# registers an alternative asset LLM provider).
_CORE_RANKING = [
    ("qwen3:8b", "Qwen3 8B: best at strict JSON and design reasoning that fits in 8 GB"),
    ("qwen2.5-coder:7b", "Qwen2.5 Coder 7B: reads code well, fits in 8 GB"),
    ("llama3.1:8b", "Llama 3.1 8B: general instruct"),
    ("gemma3:4b", "Gemma 3 4B: fast lightweight instruct"),
]
_asset_provider = addons.REGISTRY.llm.get("asset_provider")
LLM_RANKING = list(_asset_provider.ranking if _asset_provider else _CORE_RANKING)
_CODE_FIRST = list(getattr(_asset_provider, "code_first", ["qwen2.5-coder:7b", "qwen3:8b"]))


def _norm(name: str) -> str:
    n = name.lower()
    return n[:-7] if n.endswith(":latest") else n


def _allowed_core_llms() -> set[str]:
    from studio_models import manifest

    llms = manifest().get("llms", {})
    entries = list(llms.get("instruct") or []) + list(llms.get("extras") or [])
    return {_norm(str(e["name"])) for e in entries if e.get("name")} | {_norm(n) for n, _ in _CORE_RANKING}


def _ollama_models() -> list[str] | None:
    from studio_models import ollama_installed

    have = ollama_installed()
    if have is None:
        return None
    seen, out = set(), []
    for name in have:
        norm = _norm(name)
        if norm not in seen:
            seen.add(norm)
            out.append(norm if name.endswith(":latest") else name)
    return out


def installed_llms() -> list[str] | None:
    """Usable allow-listed Ollama models, or provider-supplied models if an extension is loaded."""
    if _asset_provider and hasattr(_asset_provider, "installed_llms"):
        return _asset_provider.installed_llms()
    ollama = _ollama_models()
    if ollama is None:
        return None
    allowed = _allowed_core_llms()
    return [name for name in ollama if _norm(name) in allowed]


def pick_llm(read_code: bool = False, requested: str = "") -> tuple[str | None, str]:
    """(model, reason). Strictly allow-listed in core; never falls back to unlisted Ollama models."""
    if _asset_provider and hasattr(_asset_provider, "pick_llm"):
        return _asset_provider.pick_llm(read_code=read_code, requested=requested)
    have = installed_llms()
    if have is None:
        return None, "Ollama isn't running, so the offline matcher was used."
    by_norm = {_norm(h): h for h in have}
    note = ""
    if requested and not requested.lower().startswith("auto"):
        if _norm(requested) in by_norm:
            return by_norm[_norm(requested)], f"{requested}: your pick."
        note = f"{requested} isn't an allow-listed installed model; "
    order = [n for n, _ in LLM_RANKING]
    if read_code:
        order = _CODE_FIRST + [n for n in order if n not in _CODE_FIRST]
    reasons = dict(LLM_RANKING)
    for name in order:
        if _norm(name) in by_norm:
            why = reasons[name] + (" (reading a repo, so a coder model goes first)" if read_code and name in _CODE_FIRST else "")
            return by_norm[_norm(name)], note + why
    return None, note + "No allow-listed instruct LLM is installed. Run start_graphical_studio.sh --llm-sync."


def _parse_json_reply(raw: str) -> dict | None:
    raw = re.sub(r"<think>[\s\S]*?</think>", "", raw or "").strip()
    m = re.search(r"\{[\s\S]*\}", raw)
    try:
        data = json.loads(m.group(0) if m else raw)
    except (ValueError, AttributeError):
        return None
    return data if isinstance(data, dict) else None


def _ollama_chat(model: str, system: str, user: str, ctx: int, temperature: float, timeout: float) -> str:
    body = {"model": model, "stream": False, "format": "json", "keep_alive": "30s",
            "options": {"temperature": temperature, "num_ctx": ctx, "num_predict": 1400},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if _norm(model).startswith("qwen3"):
        body["think"] = False
    req = urllib.request.Request(f"{OLLAMA_URL}/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read()).get("message", {}).get("content", "")


LAST_LLM_ERROR = {"text": ""}


def llm_json(model: str, system: str, user: str, *, ctx: int = 8192, temperature: float = 0.6, timeout: float = 300) -> dict | None:
    """One chat call in JSON mode via Ollama (or registered provider). Surfaces refusals cleanly."""
    from studio_rectifier import _is_llm_refusal

    LAST_LLM_ERROR["text"] = ""
    try:
        if _asset_provider and hasattr(_asset_provider, "chat"):
            raw = _asset_provider.chat(model, system, user, ctx, temperature, timeout)
        else:
            raw = _ollama_chat(model, system, user, ctx, temperature, timeout)
    except Exception as exc:
        LAST_LLM_ERROR["text"] = f"{type(exc).__name__}: {exc}"
        return None
    if _is_llm_refusal(raw) and not addons.REGISTRY.llm.get("allow_refusal_bypass"):
        msg = f"{model} refused the request."
        LAST_LLM_ERROR["text"] = msg
        return {"_refused": True, "_note": msg}
    data = _parse_json_reply(raw)
    if data is None:
        LAST_LLM_ERROR["text"] = "reply wasn't valid JSON"
    return data


# ── Step 1: brief -> concept + fields ─────────────────────────────────────────
_LEAD = re.compile(r"^\s*(?:please\s+)?(?:i\s+(?:need|want|would like)|can you|could you|make|create|generate|design|give me|draw)"
                   r"(?:\s+me)?\s*(?:an?|the|some)?\s*(?:new\s+)?(?:app\s+|program\s+)?"
                   r"(?:icon|logo|background|wallpaper|backdrop|texture|tile|sprite|image|picture|asset)?s?\s*"
                   r"(?:for|of|that is|showing|with)?\s*(?:an?|the|my)?\s*", re.I)

_FOR_THING = re.compile(r"^(?:for\s+)?(?:[\w.()/-]+\s+){0,3}?[\w.()/-]+\s+(?:that is|that's|which is|that shows|showing|depicting)\s+", re.I)

_MOTIFS = [
    (("ide", "editor", "code", "coding", "coder", "programming", "developer", "dev "), "a bold </> code bracket"),
    (("remote", "cloud", "server", "ssh", "hosted"), "a soft cloud"),
    (("terminal", "shell", "cli", "console", "command line"), "a terminal prompt '>_'"),
    (("vibe", "vibecod", "flow", "music", "audio", "sound"), "a flowing sound-wave ribbon"),
    (("ai", "agent", "llm", "assistant", "smart", "magic"), "a four-point sparkle"),
    (("chat", "message", "talk", "social"), "a rounded speech bubble"),
    (("game", "gaming", "play"), "a stylized game controller"),
    (("security", "secure", "vault", "password", "lock"), "a shield with a keyhole"),
    (("database", "data", "storage", "sql"), "a stacked database cylinder"),
    (("photo", "image", "camera", "graphic", "studio", "art", "paint"), "a camera aperture"),
    (("film", "movie", "cinema", "reel"), "a play triangle in a film frame"),
    (("note", "notes", "writing", "docs", "document"), "a folded page with a pen"),
    (("mail", "email", "inbox"), "an envelope"),
    (("finance", "money", "budget", "wallet"), "a coin stack"),
    (("weather", "forecast"), "a sun peeking from a cloud"),
    (("map", "location", "travel", "navigation"), "a map pin"),
    (("rocket", "deploy", "launch", "fast", "speed"), "a small rocket"),
    (("git", "version", "branch", "merge"), "branching git nodes"),
    (("linux", "penguin"), "a subtle penguin silhouette"),
    (("calendar", "schedule", "time", "clock"), "a clock face"),
    (("gpu", "compute", "chip", "hardware"), "a glowing microchip"),
]
_FIELD_HINTS: dict[str, list[tuple[tuple[str, ...], str]]] = {
    "platform": [(("linux", "gnome", "kde", "freedesktop", "ubuntu", "arch", "fedora"), "Linux desktop (freedesktop / Papirus-like)"),
                 (("macos", "mac ", "apple", "osx"), "macOS (Big Sur squircle, soft 3D)"),
                 (("windows", "win11", "fluent"), "Windows 11 Fluent"), (("android",), "Android adaptive icon"),
                 (("ios", "iphone", "ipad"), "iOS app icon"), (("favicon", "website", "web app", "pwa"), "Web favicon / PWA"),
                 (("game", "ability", "inventory", "rpg"), "Game item / ability icon")],
    "style": [(("pixel", "8-bit", "16-bit", "retro game"), "Pixel art"), (("glass", "frosted"), "Glassmorphism (frosted glass)"),
              (("clay",), "3D clay render"), (("isometric",), "Isometric 3D"), (("outline", "line icon", "line art"), "Line icon (outline)"),
              (("neon", "cyberpunk", "synthwave"), "Neon glow"), (("3d", "glossy"), "Soft 3D glossy"), (("anime", "chibi", "kawaii"), "Anime chibi mascot"),
              (("photo", "realistic", "photoreal"), "Photorealistic"), (("watercolor", "watercolour"), "Soft watercolor"),
              (("oil painting", "painterly", "painted"), "Painterly oil painting"), (("matte painting", "cinematic"), "Cinematic matte painting"),
              (("ghibli", "anime landscape", "hand-painted"), "Hand-painted anime landscape"), (("low-poly", "low poly"), "Low-poly 3D"),
              (("vector", "flat"), "Flat vector illustration"), (("abstract", "gradient"), "Minimal abstract gradient"),
              (("stylized", "hand painted"), "Stylized hand-painted")],
    "time": [(("sunrise", "dawn"), "Sunrise"), (("sunset", "dusk"), "Sunset"), (("golden hour",), "Golden hour"), (("night", "moon", "stars"), "Night"),
             (("blue hour", "twilight"), "Blue hour"), (("overcast", "cloudy"), "Overcast daylight"), (("sunny", "noon", "midday", "day"), "Midday")],
    "weather": [(("fog", "foggy", "mist"), "Fog"), (("rain", "rainy"), "Rain"), (("snow", "snowy"), "Snow"), (("storm",), "Storm clouds"),
                (("haze", "hazy"), "Light haze"), (("sunny", "clear"), "A few fluffy clouds")],
    "season": [(("summer",), "Summer"), (("spring", "blossom", "cherry"), "Spring"), (("autumn", "fall", "leaves"), "Autumn"),
               (("winter", "snow"), "Winter")],
    "use": [(("ultrawide", "21:9"), "Ultrawide wallpaper (21:9)"), (("phone", "mobile", "9:16", "lock screen"), "Phone wallpaper (9:16)"),
            (("hero", "landing", "website"), "Website hero"), (("ide", "editor", "app background", "subtle", "behind code"), "App / IDE background (subdued)"),
            (("login", "splash"), "Login / splash screen"), (("game", "parallax", "level"), "Game background (parallax-friendly)"),
            (("banner", "header", "twitter", "social"), "Social banner (3:1)"), (("repo", "wallpaper", "desktop"), "Desktop wallpaper (16:9)")],
    "mood": [(("cozy", "cosy", "warm"), "Cozy"), (("peaceful", "calm", "serene", "gentle", "quiet"), "Peaceful"), (("epic", "grand"), "Epic"),
             (("mysterious", "dark", "eerie"), "Mysterious"), (("cheerful", "happy", "bright", "sunny"), "Cheerful"),
             (("friendly", "approachable"), "Friendly"), (("professional", "enterprise", "business"), "Professional"),
             (("playful", "fun", "vibe"), "Playful"), (("futuristic", "ai", "sci-fi"), "Futuristic"), (("hacker", "terminal"), "Hacker / terminal")],
    "tiling": [(("horizontal", "side-scroll", "x only"), "Seamless horizontally only")],
    "subject": [(("chat", "dialog", "dialogue", "text box", "textbox", "subtitle"), "Chat / dialogue box"),
                (("speech", "bubble"), "Speech bubble"), (("menu", "pause", "settings"), "Menu panel"),
                (("window",), "Window (with title bar)"), (("card",), "Card (portrait)"), (("button",), "Button"),
                (("slot", "inventory"), "Inventory slot"), (("tooltip",), "Tooltip"), (("banner", "ribbon"), "Banner ribbon"),
                (("hud", "health bar", "status bar"), "HUD bar"), (("nameplate", "name tag", "name plate"), "Nameplate")],
    "theme": [(("fantasy", "rpg", "medieval", "dungeon", "elven", "dragon"), "Fantasy RPG (gold and dark wood)"),
              (("sci-fi", "scifi", "space", "hud", "futuristic", "hologram"), "Sci-fi HUD (holographic)"),
              (("cyberpunk", "neon"), "Cyberpunk neon"), (("modern", "clean", "minimal", "app", "saas"), "Clean modern UI"),
              (("glass", "frosted"), "Glassmorphism"), (("jrpg", "retro", "8-bit", "16-bit", "snes"), "Retro JRPG"),
              (("steampunk", "brass", "victorian"), "Steampunk brass"), (("parchment", "scroll", "paper", "ink"), "Parchment and ink"),
              (("cute", "pastel", "kawaii", "cozy"), "Cute pastel"), (("noir", "deco", "detective", "1920"), "Art deco noir"),
              (("horror", "gothic", "vampire", "blood"), "Gothic horror")],
    "center": [(("transparent", "hollow", "empty", "see-through", "see through"), "Transparent (hollow)"),
               (("parchment", "paper", "scroll"), "Parchment texture")],
    "view": [(("isometric",), "Isometric"), (("top-down", "top down", "overhead"), "Top-down"), (("side",), "Side view"),
             (("three-quarter", "3/4"), "Three-quarter view")],
}
_DEFAULTS = {
    "icon": {"style": "Modern flat vector with soft gradients", "platform": "Generic app icon", "shape": "Rounded square (squircle)",
             "palette": "Deep indigo with electric cyan", "background": "Transparent (cut out)", "lighting": "Subtle inner glow",
             "detail": "Minimal (reads at 16px)", "mood": "Friendly", "text": "None", "outline": "None",
             "exports": "16,24,32,48,64,128,256,512 (Linux hicolor)", "quality": "Best quality"},
    "background": {"style": "Photorealistic", "use": "Desktop wallpaper (16:9)", "time": "Golden hour", "weather": "A few fluffy clouds",
                   "season": "", "lighting": "Warm soft light", "palette": "Natural vivid greens and blues", "camera": "Wide panoramic, eye level",
                   "depth": "Atmospheric perspective haze", "space": "None needed", "mood": "Peaceful", "detail": "Highly detailed",
                   "final": "1920x1080", "quality": "Best quality"},
    "texture": {"style": "Photoreal PBR albedo", "tiling": "Seamless both directions", "scale": "Medium (about 1 m square)",
                "palette": "Natural", "lighting": "Flat, even, no shadows (albedo)", "detail": "Highly detailed", "final": "1024x1024",
                "quality": "Best quality"},
    "frame": {"subject": "Chat / dialogue box", "theme": "Fantasy RPG (gold and dark wood)", "style": "Hand-painted game UI",
              "border": "Ornate filigree", "corners": "Ornamented corner pieces", "center": "Transparent (hollow)", "parts": "None",
              "background": "Transparent (cut out)", "palette": "Gold and deep brown", "detail": "Moderate",
              "final": "Auto (by frame type)", "quality": "Best quality"},
    "sprite": {"style": "Hand-painted game art", "view": "Three-quarter view", "background": "Transparent (cut out)", "palette": "Vibrant",
               "outline": "Thin dark outline", "detail": "Moderate", "final": "512x512", "quality": "Best quality"},
}
_LINUX_TECH_PALETTES = ["Deep indigo with electric cyan", "Teal and mint", "Black and neon green (terminal)"]


def _hits(text: str, words) -> int:
    return sum(1 for w in words if re.search(rf"(?<![a-z]){re.escape(w.strip())}", text))


def _offline_fields(kind: str, brief: str, repo: dict | None) -> tuple[dict[str, str], str]:
    low = f" {brief.lower()} {' '.join((repo or {}).get('keywords', []))} {(repo or {}).get('description', '').lower()} "
    keys = {f[0] for f in FIELDS[kind]}
    out = dict(_DEFAULTS[kind])
    for key, hints in _FIELD_HINTS.items():
        if key not in keys:
            continue
        opts = {o.lower() for o in next(f[2] for f in FIELDS[kind] if f[0] == key)}
        scored = sorted(((_hits(low, ws), val) for ws, val in hints if val.lower() in opts), reverse=True)
        if scored and scored[0][0]:
            out[key] = scored[0][1]
    body = _LEAD.sub("", brief.strip()).strip(" .")
    body = _FOR_THING.sub("", body, count=1)
    body = re.sub(r"\s+", " ", body)
    if kind in ("icon", "sprite"):
        motifs = [m for ws, m in _MOTIFS if _hits(low, ws)]
        if kind == "icon":
            out["subject"] = (" fused with ".join(motifs[:2]) + (f", with {motifs[2]} as an accent" if len(motifs) > 2 else "")) if motifs \
                else f"a simple symbolic mark for {body[:80]}"
            out["concept"] = body[:200]
            if "Linux" in out.get("platform", "") and _hits(low, ("code", "ide", "terminal", "dev")):
                out["palette"] = random.choice(_LINUX_TECH_PALETTES)
            if _hits(low, ("vibe", "flow", "music")):
                out["mood"] = "Playful"
        else:
            out["subject"] = body[:200]
    elif kind == "background":
        parts = re.split(r",\s*|\.\s+|;\s*|\s+(?:and\s+)?in the distance\s+", body, maxsplit=1)
        out["subject"] = parts[0][:240]
        out["focal"] = parts[1][:300] if len(parts) > 1 else ""
        if _hits(low, ("sunny", "summer day", "bright day")):
            out["lighting"], out["palette"] = "Bright natural sunlight", "Natural vivid greens and blues"
            if out["time"] == "Golden hour":
                out["time"] = "Midday"
        if _hits(low, ("night", "neon", "dark")):
            out["lighting"], out["palette"] = "Neon glow" if "neon" in low else "Soft diffuse light", "Dark with neon accents" if "neon" in low else "Cool muted blues"
    elif kind == "frame":
        theme_palette = {"Sci-fi": "Steel and cyan", "Cyberpunk": "Magenta and cyan neon", "Clean": "White and soft grey",
                         "Glass": "White and soft grey", "Cute": "Pastel pink and lilac", "Art deco": "Black and gold",
                         "Gothic": "Bone and crimson", "Parchment": "Gold and deep brown"}
        out["palette"] = next((v for k, v in theme_palette.items() if out["theme"].startswith(k)), out["palette"])
        if out["theme"].startswith(("Clean", "Glass")):
            out["border"], out["corners"], out["detail"] = "Thin clean line", "Rounded", "Minimal"
            out["style"] = "Flat vector" if out["style"] == "Hand-painted game UI" else out["style"]
        elif out["theme"].startswith(("Sci-fi", "Cyberpunk")):
            out["border"], out["corners"] = "Glowing edges", "Chamfered (cut)"
        elif out["theme"].startswith("Retro"):
            out["style"], out["border"], out["corners"] = "Pixel art", "Double line", "Rounded"
        if out["subject"].startswith("Speech"):
            out["parts"] = "Speech tail at bottom-left"
        elif out["subject"].startswith("Window"):
            out["parts"] = "Title bar with close button"
        out["extra"] = ""
        out["_body"] = body[:240]
    else:
        out["subject"] = body[:200]
    abstract = any(w in out.get("style", "").lower() for w in ("abstract", "tech", "gradient", "vector"))
    if repo and repo.get("colors") and "palette" in keys and (kind in ("icon", "sprite") or abstract):
        out["palette"] = "brand colors " + ", ".join(repo["colors"][:3])
    if repo and kind == "icon" and repo.get("name"):
        out["concept"] = f"{repo['name']}: {out.get('concept') or repo.get('description', '')}"[:240]
    body_note = out.pop("_body", "")
    concept = _offline_concept(kind, out) + (f" Brief: {body_note}." if body_note else "")
    return out, concept


def _offline_concept(kind: str, f: dict[str, str]) -> str:
    if kind == "icon":
        return (f"A {f.get('mood', 'friendly').lower()} {f.get('style', '').lower()} icon: {f.get('subject', '')}, "
                f"on a {f.get('shape', '').lower()} in {f.get('palette', '').lower()}, simple enough to read at small sizes.")
    if kind == "background":
        return (f"{f.get('subject', '')}" + (f", with {f['focal']}" if f.get("focal") else "") +
                f". {f.get('time', '')}, {f.get('weather', '').lower()}, {f.get('mood', '').lower()} mood.")
    if kind == "frame":
        return (f"A {f.get('theme', '').lower()} {f.get('subject', '').lower()} frame, {f.get('style', '').lower()}, "
                f"{f.get('border', '').lower()} border with {f.get('corners', '').lower()} corners; "
                f"center: {f.get('center', '').lower()}.")
    return f"{f.get('subject', '')}, {f.get('style', '').lower()}."


_EXPAND_SYSTEM = (
    "You are a senior visual designer and art director for an all-ages creative studio. A creator gives you a rough one-line brief for a graphic "
    "asset. Expand it into a strong, specific design direction, then fill in every field.\n"
    "Rules: honor everything the brief states exactly (objects, places, colors, time of day, platform). Invent the "
    "rest so it is coherent, tasteful and fits the purpose. For icons think like an icon designer: one clear metaphor, "
    "bold simple shapes that read at 16-32 px, follow the platform's conventions, at most 2-3 main colors. "
    "For backgrounds think like a matte painter: clear focal point, depth, light direction, and leave room for UI if asked. "
    "Each field value is a short phrase (max ~15 words) written specifically for THIS brief in your own words: no "
    "generic stock phrases, no filler. Use \"\" when a field does not apply or the brief gives nothing to go on.\n"
    "Reply with JSON only: {\"title\": short name, \"concept\": 2-4 vivid sentences describing the finished image, "
    "\"fields\": {key: value, ...}}"
)


def expand_brief(brief: str, kind: str = "auto", repo_path: str = "", llm: str = "", use_llm: bool = True) -> dict:
    """Step 1. Returns {"kind", "title", "concept", "fields", "notes", "llm", "repo"}."""
    brief = (brief or "").strip()
    if not brief:
        raise ValueError("Write a short brief first.")
    kind = detect_kind(brief) if kind in ("", "auto") else kind
    if kind not in FIELDS:
        raise ValueError(f"Unknown asset kind: {kind}")
    notes, repo = [], None
    if repo_path:
        repo = scan_repo(repo_path)
        bits = [f"name '{repo['name']}'"] + ([f"colors {', '.join(repo['colors'][:3])}"] if repo["colors"] else []) + \
               ([f"{len(repo['existing_art'])} existing icon/logo file(s)"] if repo["existing_art"] else [])
        notes.append("Read the repo: " + "; ".join(bits) + ".")
    fields, concept = {}, ""
    title, used = "", ""
    model, why = pick_llm(read_code=bool(repo), requested=llm) if use_llm else (None, "LLM off: offline matcher.")
    if model:
        spec = "\n".join(f"- {k} ({label})" + (f": {tip}" if tip else "")
                         for k, label, opts, tip in FIELDS[kind] if k not in ("quality",))
        user = (f"ASSET KIND: {KIND_LABELS[kind]}\nBRIEF: {brief}\n"
                + (f"\nTHE PROJECT THIS IS FOR (read from its repo):\n{repo['summary']}\n" if repo else "")
                + f"\nFIELDS:\n{spec}\n\nReturn the JSON now.")
        data = llm_json(model, _EXPAND_SYSTEM, user, ctx=8192 if repo else 4096)
        if isinstance(data, dict) and data.get("_refused"):
            ref_msg = str(data.get("_note") or f"{model} refused this brief.")
            return {"kind": kind, "title": "", "concept": "", "fields": {}, "notes": [ref_msg], "llm": model,
                    "refused": True,
                    "repo": {k: repo[k] for k in ("path", "name", "description", "colors", "existing_art")} if repo else None}
        got = data.get("fields") if isinstance(data, dict) else None
        if isinstance(got, dict):
            keys = {f[0] for f in FIELDS[kind]}
            n = 0
            for k, v in got.items():
                if k in keys and isinstance(v, (str, int, float)) and k != "quality":
                    fields[k] = str(v).strip()[:300]
                    n += 1
            concept = str(data.get("concept") or "").strip()[:1200]
            title = str(data.get("title") or "").strip()[:80]
            used = model
            notes.insert(0, f"{model} expanded the brief ({n} fields). Why this LLM: {why}")
        else:
            fields, concept = _offline_fields(kind, brief, repo)
            notes.insert(0, f"{model} failed ({LAST_LLM_ERROR['text'] or 'no usable JSON'}), so the offline matcher filled the fields.")
    else:
        fields, concept = _offline_fields(kind, brief, repo)
        notes.insert(0, why)
    return {"kind": kind, "title": title, "concept": concept, "fields": fields, "notes": notes, "llm": used,
            "repo": {k: repo[k] for k in ("path", "name", "description", "colors", "existing_art")} if repo else None}


# ── Step 2: analyze -> model, settings, prompt ────────────────────────────────
MODEL_SETTINGS = {
    "flux_dev": {"steps": 24, "cfg": 1.0, "guidance": 3.5, "sampler": "euler", "scheduler": "simple"},
    "flux_schnell": {"steps": 4, "cfg": 1.0, "guidance": 0.0, "sampler": "euler", "scheduler": "simple"},
    "flux2_klein": {"steps": 4, "cfg": 1.0, "guidance": 0.0, "sampler": "euler", "scheduler": "simple"},
    "qwen_image": {"steps": 8, "cfg": 1.0, "guidance": 0.0, "sampler": "euler", "scheduler": "simple", "lightning": True},
    **(addons.REGISTRY.models.get("asset_settings") or {}),
}
SAMPLERS = ("euler", "euler_ancestral", "dpmpp_2m", "dpmpp_2m_sde", "uni_pc")
SCHEDULERS = ("simple", "karras", "normal", "beta", "sgm_uniform")
_USE_CANVAS = {
    "ultrawide": ((1536, 640), "3440x1440"), "phone": ((768, 1344), "1080x1920"), "banner": ((1536, 512), "1500x500"),
    "square": ((1024, 1024), "2048x2048"),
}
_FALLBACK_ORDER = list(addons.REGISTRY.models.get("asset_fallback_order") or ["flux2_klein", "flux_dev", "flux_schnell", "qwen_image"])
NL_ENGINES = ("flux", "klein", "qwen")


def spills(model: str) -> bool:
    """True for models bigger than an 8 GB card: they run partly from system RAM (shown in red)."""
    return bool(ASSET_MODELS.get(model, {}).get("spills"))


def _has(text: str, *words: str) -> bool:
    return any(w in text for w in words)


def _choose_model(kind: str, f: dict[str, str], concept: str) -> tuple[str, str]:
    model, why = _choose_model_base(kind, f, concept)
    alltext = f"{concept} {f.get('extra', '')} {f.get('subject', '')}".lower()
    wants_text = bool(_lettering(f.get("text", ""))) or any(w in alltext for w in ("lettering", "the text", "the word", "logo text", "title text"))
    if model in ("flux_dev", "flux_schnell"):
        if wants_text and model_installed("qwen_image"):
            return "qwen_image", (why.split(":")[0] + ": Qwen-Image renders lettering most reliably and follows long prompts best. "
                                  "It's larger than 8 GB, so it runs partly from system RAM (slower).")
        if model_installed("flux2_klein"):
            return "flux2_klein", (why.split(":")[0] + ": FLUX.2 klein 4B reads the prompt through a Qwen3 LLM encoder, so it "
                                   "follows detailed prompts far better than Flux.1's T5, and fits fully in 8 GB (4 steps).")
    return model, why


def _choose_model_base(kind: str, f: dict[str, str], concept: str) -> tuple[str, str]:
    chooser = addons.REGISTRY.models.get("asset_choose_model")
    if chooser:
        picked = chooser(kind, f, concept)
        if picked:
            return picked
    style = (f.get("style") or "").lower()
    quality = (f.get("quality") or "").lower()
    alltext = f"{style} {concept.lower()} {(f.get('extra') or '').lower()}"
    fast = "fast" in quality or "draft" in quality
    if _has(style, "pixel"):
        return ("flux_schnell" if fast else "flux_dev"), "Pixel art: FLUX renders crisp pixel-art compositions, then snapped to a true pixel grid."
    if kind == "texture":
        return ("flux_schnell" if fast else "flux_dev"), "Texture: FLUX.1 renders even top-down material patterns cleanly."
    if kind == "icon":
        if fast:
            return "flux_schnell", "Icon draft: Flux schnell in 4 steps (re-run on Flux dev for the final)."
        why = "Icon: Flux.1 dev follows layout and shape instructions closely and makes clean vector/3D shapes."
        if _lettering(f.get("text", "")):
            why += " It can also spell a few letters."
        return "flux_dev", why
    if kind == "frame":
        if fast:
            return "flux_schnell", "Frame draft: Flux schnell (4 steps)."
        return "flux_dev", "UI frame: Flux.1 dev keeps borders straight and symmetrical and leaves the center empty when asked."
    if kind == "sprite":
        if fast:
            return "flux_schnell", "Sprite draft: Flux schnell (4 steps)."
        return "flux_dev", "Sprite: Flux.1 dev isolates a single object cleanly, which makes the cut-out easy."
    elements = len([x for x in re.split(r",| and | with | next to | beside |;", f"{f.get('subject', '')}, {f.get('focal', '')}") if x.strip()])
    if fast:
        return "flux_schnell", "Background draft: Flux schnell (4 steps)."
    if _has(style, "photo") and elements <= 2:
        return "flux_dev", "Photoreal scene with few elements: Flux.1 dev renders natural landscapes and lighting cleanly."
    if _has(alltext, "text", "letter", "words", "sign"):
        return "flux_dev", "Contains lettering: Flux.1 dev is the only installed model that can spell."
    return "flux_dev", f"Background with {elements} specific elements: Flux.1 dev places each described object where it's asked."


def _parse_size(text: str) -> tuple[int, int] | None:
    m = re.search(r"(\d{2,5})\s*[x×]\s*(\d{2,5})", text or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def _canvas(kind: str, f: dict[str, str]) -> tuple[int, int, str]:
    """(render width, render height, final size 'WxH' or '')."""
    if kind == "background":
        use = (f.get("use") or "").lower()
        key = next((k for k in _USE_CANVAS if k in use or (k == "phone" and "9:16" in use) or (k == "banner" and "3:1" in use)), "")
        (w, h), final = _USE_CANVAS.get(key, ((1344, 768), "1920x1080"))
        want = _parse_size(f.get("final") or "")
        if want:
            final = f"{want[0]}x{want[1]}"
            ratio = want[0] / want[1]
            h = int(round((1_048_576 / ratio) ** 0.5 / 64)) * 64
            w = int(round(h * ratio / 64)) * 64
        elif "same" in (f.get("final") or "").lower():
            final = ""
        return max(512, min(w, 1792)), max(512, min(h, 1792)), final
    if kind == "frame":
        ftype = (f.get("subject") or "").lower()
        key = next((k for k in _FRAME_CANVAS if k in ftype or (k == "chat" and "dialog" in ftype)), "")
        (w, h), final = _FRAME_CANVAS.get(key, ((1344, 768), "1200x686"))
        want = _parse_size(f.get("final") or "")
        if want:
            final = f"{want[0]}x{want[1]}"
            ratio = want[0] / want[1]
            h = int(round((1_048_576 / ratio) ** 0.5 / 64)) * 64
            w = int(round(h * ratio / 64)) * 64
        return max(512, min(w, 1792)), max(512, min(h, 1792)), final
    want = _parse_size(f.get("final") or "")
    final = f"{want[0]}x{want[1]}" if want else ("1024x1024" if kind == "icon" else "")
    return 1024, 1024, final


def _exports(f: dict[str, str]) -> str:
    raw = (f.get("exports") or "")
    if "none" in raw.lower():
        return ""
    return ",".join(re.findall(r"\d{2,4}", raw.split("(")[0]))


def _join(*parts: str) -> str:
    return " ".join(p.strip().rstrip(".") + "." for p in parts if p and p.strip())


def _avoid_phrase(avoid: str) -> str:
    return f"Without {avoid.strip()}" if avoid and avoid.strip() else ""


def _lettering(text: str) -> str:
    """Text field -> prompt phrase."""
    t = (text or "").strip()
    if not t or t.lower().startswith("none"):
        return ""
    quoted = re.search(r'["\u201c]([^"\u201d]{1,24})["\u201d]', t)
    if quoted:
        return f'with the text "{quoted.group(1)}" in clean bold letters'
    if t.lower().startswith("single letter"):
        return "with a single bold letter as a monogram"
    if t.lower().startswith("short word"):
        return "with a short word in clean bold letters"
    m = re.match(r"(?i)monogram\s+(\w)", t)
    if m:
        return f'with a bold letter "{m.group(1).upper()}" as a monogram'
    return f'with the text "{t[:24]}" in clean bold letters'


def python_prompt(kind: str, f: dict[str, str], concept: str, model: str) -> tuple[str, str]:
    """(prompt, negative) assembled without an LLM, in the model's preferred form."""
    def g(k: str) -> str:
        v = (f.get(k) or "").strip()
        return re.sub(r"\s*\([^)]*\)", "", v).strip() if k in ("detail", "use", "scale") else v

    flux = ASSET_MODELS[model]["engine"] in NL_ENGINES
    known = set(re.findall(r"[a-z]{3,}", " ".join(f.values()).lower()))
    words = re.findall(r"[a-z]{3,}", (concept or "").lower())
    if words and sum(w in known for w in words) / len(words) > 0.6:
        concept = ""
    cutout = "transparent" in g("background").lower()
    neg_base = {"icon": "photo, photograph, busy background, multiple icons, icon sheet, mockup, device frame, hand, blurry, jpeg artifacts",
                "background": "people, person, text, watermark, logo, frame, border, blurry, oversaturated",
                "texture": "seams, visible edges, vignette, perspective, objects, text, watermark, frame, border, shadows",
                "sprite": "multiple objects, busy background, scenery, cropped, text, watermark, blurry",
                "frame": "text, letters, words, characters, people, scenery inside, icons inside, perspective, tilted, "
                         "cropped, mockup, screenshot, asymmetrical, blurry, watermark"}[kind]
    negative = ", ".join(x for x in (neg_base, g("avoid")) if x)
    if kind == "icon":
        bg = "on a plain solid white background" if cutout or "white" in g("background").lower() else \
             f"on a {g('background').lower()} background" if g("background") else ""
        lettering = _lettering(g("text"))
        if flux:
            prompt = _join(f"A {g('style').lower()} app icon in the style of {g('platform')}",
                           f"The icon is {g('subject')}" + (f", {lettering}" if lettering else ""),
                           f"It sits on a {g('shape').lower()}" if g("shape") and "freeform" not in g("shape").lower() else "Freeform shape with no container plate",
                           f"Color palette: {g('palette')}", g("lighting"), f"{g('detail')} detail" if g("detail") else "",
                           f"{g('mood')} feel" if g("mood") else "", g("outline") if g("outline").lower() != "none" else "",
                           concept, "Single centered icon with generous padding, crisp clean edges, professional icon design",
                           bg, "No text" if not lettering else "", g("extra"), _avoid_phrase(g("avoid")))
        else:
            prompt = ", ".join(x for x in ("app icon", g("style"), g("subject"), lettering, g("shape"), g("palette"), g("lighting"),
                                           g("mood"), g("outline") if g("outline").lower() != "none" else "", "single centered icon",
                                           "clean vector shapes", "crisp edges", bg, g("extra")) if x)
            if not lettering:
                negative += ", text, letters, words"
    elif kind == "background":
        use = g("use")
        if flux:
            prompt = _join(f"A {g('style').lower()} {('image for a ' + use.lower()) if use else 'background image'}",
                           f"{g('subject')}", g("focal"),
                           ", ".join(x for x in (g("time"), g("weather"), g("season")) if x),
                           g("lighting"), f"Colors: {g('palette')}" if g("palette") else "", g("camera"), g("depth"),
                           g("space") if g("space") and not g("space").lower().startswith("none") else "",
                           f"{g('mood')} mood" if g("mood") else "", g("detail"), concept, g("extra"),
                           "No text, no watermark", _avoid_phrase(g("avoid")))
        else:
            prompt = ", ".join(x for x in (g("style"), g("subject"), g("focal"), g("time"), g("weather"), g("season"), g("lighting"),
                                           g("palette"), g("camera"), g("depth"),
                                           g("space") if g("space") and not g("space").lower().startswith("none") else "",
                                           f"{g('mood')} atmosphere" if g("mood") else "", g("detail"), "scenery, no humans",
                                           g("extra")) if x)
    elif kind == "frame":
        hollow = "transparent" in g("center").lower() or "hollow" in g("center").lower()
        center = "the inside is completely empty, a perfectly flat plain white area with nothing in it" if hollow else \
            f"the inside is an empty {g('center').lower()} with nothing in it"
        outside = "on a plain solid black background" if hollow else \
            ("on a plain solid white background" if cutout or "white" in g("background").lower() else
             f"on a {g('background').lower()} background" if g("background") else "")
        parts = g("parts") if g("parts") and not g("parts").lower().startswith("none") else ""
        if flux:
            prompt = _join(f"A {g('style').lower()} game UI asset: an empty {g('theme')} {g('subject').lower()} frame",
                           "Straight-on flat front view, perfectly symmetrical and centered, the whole frame visible with a small margin",
                           f"Border: {g('border').lower()}" if g("border") else "", f"Corners: {g('corners').lower()}" if g("corners") else "",
                           parts, f"Colors: {g('palette')}" if g("palette") else "", f"{g('detail')} detail" if g("detail") else "",
                           concept, center, "No text, no icons, no characters", outside, g("extra"), _avoid_phrase(g("avoid")))
        else:
            prompt = ", ".join(x for x in ("game ui frame", "empty " + g("subject").lower(), g("theme"), g("style"), g("border"),
                                           g("corners"), parts, g("palette"), g("detail"), "flat front view, symmetrical, centered",
                                           "empty plain flat white center" if hollow else f"empty {g('center').lower()}",
                                           outside, g("extra")) if x)
    elif kind == "texture":
        prompt = ", ".join(x for x in ("seamless tileable texture", g("subject"), g("style"), g("scale"), g("palette"),
                                       g("lighting"), g("detail"), "top-down orthographic view, uniform coverage, fills the entire frame",
                                       g("extra")) if x)
    else:
        bg = "on a plain solid white background" if cutout or "white" in g("background").lower() else \
             f"on a {g('background').lower()}" if g("background") else ""
        if flux:
            prompt = _join(f"A single {g('style').lower()} game asset: {g('subject')}", g("view"), f"Colors: {g('palette')}",
                           g("outline") if g("outline").lower() != "none" else "", f"{g('detail')} detail", concept,
                           f"Isolated and centered, whole object in frame {bg}", g("extra"), _avoid_phrase(g("avoid")))
        else:
            prompt = ", ".join(x for x in ("single game asset", g("subject"), g("style"), g("view"), g("palette"),
                                           g("outline") if g("outline").lower() != "none" else "", "isolated, centered, full object",
                                           bg, g("extra")) if x)
    return re.sub(r"\s+", " ", prompt).strip(), negative


_CORE_PROMPT_SYSTEM = (
    "You write prompts for all-ages image diffusion models. Given an asset brief, its design fields and the target model, "
    "write the single best prompt for that model. Keep every concrete detail from the fields and concept; never add "
    "objects that contradict them.\n"
    "FLUX models (also FLUX.2 and Qwen-Image): 2-5 natural sentences, most important thing first (what it is, then the subject, layout, colors, "
    "lighting, style). Say what the background is. No tag lists, no weights.\n"
    "Also write a short negative prompt of comma-separated tags (or leave empty for FLUX).\n"
    "Reply with JSON only: {\"prompt\": \"...\", \"negative\": \"...\"}"
)
_PROMPT_SYSTEM = addons.REGISTRY.models.get("asset_prompt_system") or _CORE_PROMPT_SYSTEM


def analyze(kind: str, fields: dict[str, str], concept: str = "", llm: str = "", use_llm: bool = True,
            read_code: bool = False) -> dict:
    """Step 2. Everything the render needs, each choice with a reason."""
    if kind not in FIELDS:
        raise ValueError(f"Unknown asset kind: {kind}")
    f = {k: str(v or "") for k, v in (fields or {}).items()}
    model, why = _choose_model(kind, f, concept)
    reasons = [f"Model: {why}"]
    ckpt_renderer = addons.REGISTRY.models.get("asset_checkpoint_renderer")
    if not model_installed(model):
        alt = next((m for m in _FALLBACK_ORDER if m != model and model_installed(m) and
                    (kind != "texture" or not ckpt_renderer or ASSET_MODELS[m]["engine"] not in NL_ENGINES)), None)
        if alt:
            reasons.append(f"{ASSET_MODELS[model]['label']} isn't installed here, so {ASSET_MODELS[alt]['label']} was picked instead "
                           "(start_graphical_studio.sh --model-sync --assets).")
            model = alt
    st = dict(MODEL_SETTINGS[model])
    quality = f.get("quality", "").lower()
    if "balanced" in quality and model not in ("flux_schnell", "flux2_klein", "qwen_image"):
        st["steps"] = max(12, int(st["steps"] * 0.7))
        reasons.append(f"Balanced: {st['steps']} steps instead of {MODEL_SETTINGS[model]['steps']}.")
    elif ("fast" in quality or "draft" in quality) and ASSET_MODELS[model]["engine"] not in NL_ENGINES:
        st["steps"] = 18
        reasons.append("Fast draft: 18 steps.")
    if model == "flux_dev":
        if kind == "icon":
            st["guidance"] = 4.0 if _lettering(f.get("text", "")) else 3.5
        elif kind == "background" and "photo" in f.get("style", "").lower():
            st["guidance"] = 2.8
            reasons.append("Photoreal on Flux: guidance 2.8 (lower looks more natural, less plastic).")
    w, h, final = _canvas(kind, f)
    reasons.append(f"Canvas {w}x{h}: about 1 megapixel, what these models are trained on" + (f", then resized to {final}." if final else "."))

    remove_bg = "none"
    hollow = kind == "frame" and any(w in f.get("center", "").lower() for w in ("transparent", "hollow"))
    anime_models = addons.REGISTRY.models.get("anime_asset_models", set())
    if kind in ("icon", "sprite", "frame") and ("transparent" in f.get("background", "").lower() or hollow):
        remove_bg = "anime" if model in anime_models else "general"
        reasons.append("Transparent outside: cut out (rembg, CPU) to a PNG with alpha.")
    if hollow:
        reasons.append("Hollow center: rendered as a flat white interior on black, then the interior is flood-filled to "
                       "transparent; the 9-slice margins (left/top/right/bottom) are measured and logged.")
    tile = "none"
    if kind == "texture" and ASSET_MODELS[model]["engine"] not in NL_ENGINES:
        tile = "x" if "horizontal" in f.get("tiling", "").lower() else "both"
        reasons.append(f"Seamless tiling: {'horizontal only' if tile == 'x' else 'both directions'} (circular padding in the model and VAE).")
    pixelate = 0
    if model == "pixel" or _has(f.get("style", "").lower(), "pixel"):
        detail = f.get("detail", "").lower()
        pixelate = 32 if "minimal" in detail or "simple" in detail else 8 if "detailed" in detail else 16
        reasons.append(f"Pixel grid: {pixelate}px cells ({1024 // pixelate}x{1024 // pixelate} art pixels), palette reduced to 48 colors.")
    exports = _exports(f) if kind == "icon" else ""
    if exports:
        reasons.append(f"Icon set: {exports.replace(',', ', ')} px PNGs and a .ico, next to the master.")
    if model == "flux2_klein":
        reasons.append("FLUX.2 klein: 4 distilled steps, CFG 1 with the FLUX.2 schedule; it ignores negatives, so avoids go into the prompt.")
    elif model == "qwen_image":
        reasons.append("Qwen-Image: Lightning LoRA, 8 steps at CFG 1 (untick Lightning for ~28 steps at CFG 2.5: better, much slower). "
                       "Runs partly from system RAM on 8 GB, so expect several minutes.")
    elif ASSET_MODELS[model]["engine"] == "flux":
        reasons.append(f"Sampler {st['sampler']}/{st['scheduler']}, {st['steps']} steps, CFG 1"
                       + (f", Flux guidance {st['guidance']}" if model == "flux_dev" else "")
                       + ": Flux is guidance-distilled, so it ignores negative prompts; avoids go into the prompt as words.")
    else:
        reasons.append(f"Sampler {st['sampler']}/{st['scheduler']}, {st['steps']} steps, CFG {st['cfg']}: the model card's sweet spot.")

    prompt, negative = python_prompt(kind, f, concept, model)
    notes, used, refused = [], "", False
    lm, lwhy = pick_llm(read_code=read_code, requested=llm) if use_llm else (None, "LLM off: Python wrote the prompt.")
    if lm:
        prompt_style = "FLUX" if ASSET_MODELS[model]["engine"] in NL_ENGINES else "checkpoint tags"
        user = (f"TARGET MODEL: {ASSET_MODELS[model]['label']} ({prompt_style})\n"
                f"ASSET KIND: {KIND_LABELS[kind]}\nCONCEPT: {concept}\nFIELDS:\n"
                + "\n".join(f"- {FIELD_LABELS[kind].get(k, k)}: {v}" for k, v in f.items() if v and k not in ("quality", "exports", "final"))
                + ("\nPOST-PROCESS: the background will be cut out, so render the subject on a plain solid white background."
                   if remove_bg != "none" else "")
                + ("\nPOST-PROCESS: the image must tile seamlessly; fill the frame evenly, no focal object, no perspective."
                   if tile != "none" else "")
                + "\n\nReturn the JSON now.")
        data = llm_json(lm, _PROMPT_SYSTEM, user, ctx=4096, temperature=0.4)
        if isinstance(data, dict) and data.get("_refused"):
            prompt, refused = "", True
            notes.append(str(data.get("_note") or f"{lm} refused this request."))
        elif data and isinstance(data.get("prompt"), str) and len(data["prompt"].strip()) > 20:
            prompt = data["prompt"].strip()[:3000]
            llm_neg = data.get("negative") if isinstance(data.get("negative"), str) else ""
            negative = ", ".join(dict.fromkeys(x.strip() for x in f"{llm_neg}, {f.get('avoid', '')}".split(",") if x.strip()))
            used = lm
            notes.append(f"{lm} wrote the prompt for {ASSET_MODELS[model]['label']}. Why this LLM: {lwhy}")
        else:
            notes.append(f"{lm} failed ({LAST_LLM_ERROR['text'] or 'no usable prompt'}); Python assembled it from the fields.")
    else:
        notes.append(f"{lwhy} The prompt was assembled from the fields.")
    out = {"kind": kind, "model": model, "model_label": ASSET_MODELS[model]["label"], "width": w, "height": h,
           **st, "seed": random.randint(1000, 999_999), "tile": tile, "remove_bg": remove_bg, "pixelate": pixelate, "hollow": hollow,
           "final_size": final, "export_sizes": exports, "prompt": prompt, "negative": negative,
           "reasons": reasons, "notes": notes, "llm": used}
    if refused:
        out["refused"] = True
    return out


# ── Step 3: command ───────────────────────────────────────────────────────────
def output_path(kind: str, title: str, prompt: str) -> str:
    words = re.findall(r"[a-zA-Z0-9]+", (title or prompt or "asset").lower())[:5]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(ASSETS_DIR, kind, f"{kind}_{'_'.join(words) or 'asset'}_{stamp}.png")


def build_command(plan: dict, out_path: str) -> list[str]:
    """generate_asset.py argv for an analyze() plan (as edited). Values are validated here."""
    model = plan["model"] if plan.get("model") in ASSET_MODELS else "flux_dev"

    def num(key, lo, hi, cast=float, default=0):
        try:
            v = cast(plan.get(key, default))
        except (TypeError, ValueError):
            v = default
        return max(lo, min(hi, v))

    step = 16 if ASSET_MODELS[model]["engine"] in ("klein", "qwen") else 8
    w = int(num("width", 256, 2048, int, 1024)) // step * step
    h = int(num("height", 256, 2048, int, 1024)) // step * step
    cmd = [VENV_PYTHON, ASSET_SCRIPT, "--model", model, "--prompt", str(plan.get("prompt", "")).strip() or "an icon",
           "--negative", str(plan.get("negative", "")).strip(), "--output", out_path,
           "--width", str(w), "--height", str(h), "--steps", str(int(num("steps", 1, 80, int, 24))),
           "--cfg", f"{num('cfg', 1.0, 15.0, float, 1.0):g}", "--guidance", f"{num('guidance', 0.0, 10.0, float, 3.5):g}",
           "--seed", str(int(num("seed", 0, 2**31 - 1, int, 42026))),
           "--sampler", plan.get("sampler") if plan.get("sampler") in SAMPLERS else "euler",
           "--scheduler", plan.get("scheduler") if plan.get("scheduler") in SCHEDULERS else "simple",
           "--tile", plan.get("tile") if plan.get("tile") in ("none", "both", "x") else "none",
           "--remove-bg", plan.get("remove_bg") if plan.get("remove_bg") in ("none", "general", "anime") else "none",
           "--pixelate", str(int(num("pixelate", 0, 64, int, 0)))]
    if plan.get("lightning") and model == "qwen_image":
        cmd.append("--lightning")
    if plan.get("hollow"):
        cmd.append("--hollow")
    if _parse_size(str(plan.get("final_size") or "")):
        fw, fh = _parse_size(plan["final_size"])
        cmd += ["--final-size", f"{max(16, min(fw, 8192))}x{max(16, min(fh, 8192))}"]
    sizes = ",".join(re.findall(r"\d{1,4}", str(plan.get("export_sizes") or "")))
    if sizes:
        cmd += ["--export-sizes", sizes]
    return cmd


def model_choices() -> list[tuple[str, str, bool]]:
    """(key, label, installed) for the model picker."""
    return [(k, v["label"], model_installed(k)) for k, v in ASSET_MODELS.items()]


addons.attach_compat("studio_assets", sys.modules[__name__])
