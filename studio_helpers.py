"""Shared CLI builders, file scanners, and OS desktop helpers for Graphical Studio."""

from datetime import datetime
import os
import queue
import re
import subprocess
import sys
import threading

import addons

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
HOME_DIR = os.path.expanduser("~")

VENV_PYTHON = os.path.join(ROOT_DIR, ".venv", "bin", "python")
PHOTO_SCRIPT = os.path.join(ROOT_DIR, "generate_photo.py") if addons.REGISTRY.models.get("photo_cli_builder") else ""
ASSET_SCRIPT = os.path.join(ROOT_DIR, "generate_asset.py")
OUTPUTS_DIR = os.path.join(ROOT_DIR, "outputs")
PHOTOS_DIR = os.path.join(OUTPUTS_DIR, "photos")
THUMB_DIR = os.path.join(ROOT_DIR, ".cache", "tmp", "thumbs")
CHECKPOINTS_DIR = os.path.join(ROOT_DIR, "ComfyUI", "models", "checkpoints")
LORAS_DIR = os.path.join(ROOT_DIR, "ComfyUI", "models", "loras")


def list_photo_loras() -> list[str]:
    """Optional LoRAs compatible with the checkpoint photo generator."""
    if not addons.REGISTRY.models.get("supports_lora") or not os.path.isdir(LORAS_DIR):
        return []
    excl = (addons.REGISTRY.models.get("lora_exclude_prefix") or "").lower()
    return sorted(
        f for f in os.listdir(LORAS_DIR)
        if f.endswith(".safetensors") and (not excl or not f.lower().startswith(excl))
    )


CORE_PHOTO_MODEL_OPTIONS = [
    ("flux2_klein", "FLUX.2 klein 4B (Fast, 4 steps)"),
    ("flux_dev", "FLUX.1 dev (Best Prompt Adherence)"),
    ("flux_schnell", "FLUX.1 schnell (Fast Draft, 4 steps)"),
    ("qwen_image", "Qwen-Image 20B (Best Text & Detail, Slow)"),
]
CORE_PHOTO_MODEL_SETTINGS = {
    "flux2_klein": {"steps": 4, "cfg": 1.0, "guidance": 0.0, "sampler": "euler", "scheduler": "simple"},
    "flux_dev": {"steps": 24, "cfg": 1.0, "guidance": 3.5, "sampler": "euler", "scheduler": "simple"},
    "flux_schnell": {"steps": 4, "cfg": 1.0, "guidance": 0.0, "sampler": "euler", "scheduler": "simple"},
    "qwen_image": {"steps": 8, "cfg": 1.0, "guidance": 0.0, "sampler": "euler", "scheduler": "simple"},
}

PHOTO_MODEL_OPTIONS = list(addons.REGISTRY.models.get("photo_options") or CORE_PHOTO_MODEL_OPTIONS)

BUILTIN_CKPTS = set(addons.REGISTRY.models.get("builtin_ckpts") or set())

REF_TARGET_OPTIONS = [
    ("none", "None (Text Prompt Only)"),
    ("person", "Person (Keep Face & Identity)"),
    ("background", "Background (Keep Room & Vibe)"),
]

REF_STYLE_OPTIONS = [
    ("Keep Prompt Style", ""),
    ("JRPG / Anime (No Background / Green Screen)", "1person, waist-up JRPG anime visual novel character sprite, crisp dark ink outlines, Persona 5 cel shading, isolated on pure flat solid bright green (#00FF00) background, simple backdrop"),
    ("JRPG / Anime (Full Scene)", "High-detail Japanese JRPG anime visual novel scene, crisp dark ink linework, vibrant cel shading"),
    ("Photorealistic", "RAW candid photo, photorealistic photography, natural skin texture, shallow depth of field"),
    ("Neo-Noir", "Dark atmospheric neo-noir cinematic illustration, dramatic shadows, neon reflections"),
]


def get_photo_model_options() -> list[tuple[str, str]]:
    """Return built-in models plus any extra checkpoints when enabled."""
    opts = list(PHOTO_MODEL_OPTIONS)
    if addons.REGISTRY.models.get("photo_options") and os.path.isdir(CHECKPOINTS_DIR):
        for fn in sorted(os.listdir(CHECKPOINTS_DIR)):
            if fn.endswith(".safetensors") and fn not in BUILTIN_CKPTS:
                opts.insert(-1, (fn, f"Custom Checkpoint: {fn}"))
    return opts


PHOTO_PRESETS = {
    "16:9 HD Background (1280x720)": (1280, 720),
    "Character Bust Portrait (832x1024)": (832, 1024),
    "Outfit Torso Sheet (896x960)": (896, 960),
    "Square 1:1 Icon (1024x1024)": (1024, 1024),
}

ANIME_BG_STYLE = (
    "crisp dark ink linework, multi-layered cel shading, Makoto Shinkai and Persona 5 anime background aesthetic, "
    "atmospheric lighting, empty room, no humans, "
)
ANIME_GREENSCREEN_CHAR_STYLE = (
    "waist-up front-facing anime visual novel character portrait sprite, symmetrical level shoulders, "
    "isolated on pure flat solid bright green (#00FF00) chroma-key background, crisp dark cel-shaded outlines, "
)
AMERICAN_REALISTIC_STYLE = (
    "RAW candid photo, photorealistic, modern American lifestyle photography, shot on Sony A7R V 35mm f/1.8 lens, "
    "natural skin texture with subtle pores, soft indoor ring-light and warm ambient window light, shallow depth of field, "
)
PHOTO_DEFAULT_NEGATIVE = "blurry, deformed, bad proportions, text, watermark, signature, frame, border"


def _slugify_output(base_dir: str, prefix: str, prompt: str, custom_name: str, ext: str) -> str:
    raw = (custom_name or "").strip()
    if raw:
        stem = re.sub(r"[^a-zA-Z0-9._-]+", "_", raw).strip("._-")
    else:
        words = re.findall(r"[a-zA-Z0-9]+", (prompt or "asset").lower())[:5]
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        stem = f"{prefix}_{'_'.join(words) or 'item'}_{stamp}"
    if not stem.lower().endswith(ext):
        stem += ext
    return os.path.join(base_dir, stem)


def slugify_photo_prompt(prompt: str, custom_name: str = "", model: str | None = None) -> str:
    default_m = addons.REGISTRY.models.get("default_photo_model") or "flux2_klein"
    return _slugify_output(PHOTOS_DIR, f"photo_{model or default_m}", prompt, custom_name, ".jpg")


def build_photo_cli_command(cfg: dict) -> list[str]:
    cli_builder = addons.REGISTRY.models.get("photo_cli_builder")
    if cli_builder:
        return cli_builder(cfg)
    default_m = addons.REGISTRY.models.get("default_photo_model") or "flux2_klein"
    model = str(cfg.get("model", default_m)).strip()
    if model not in CORE_PHOTO_MODEL_SETTINGS:
        model = default_m
    st = CORE_PHOTO_MODEL_SETTINGS[model]
    prompt = str(cfg.get("prompt", "")).strip() or "Fortune 500 high-rise office at dusk"
    out_path = str(cfg.get("output") or "").strip() or slugify_photo_prompt(prompt, cfg.get("output_name", ""), model)
    mult = 16 if model in ("flux2_klein", "qwen_image") else 8
    width = (int(cfg.get("width", 1280)) // mult) * mult
    height = (int(cfg.get("height", 720)) // mult) * mult
    cmd = [
        VENV_PYTHON, ASSET_SCRIPT,
        "--model", model, "--prompt", prompt, "--negative", str(cfg.get("negative", PHOTO_DEFAULT_NEGATIVE)).strip(),
        "--output", out_path, "--width", str(width), "--height", str(height),
        "--steps", str(int(cfg.get("steps", st["steps"]))), "--cfg", f"{float(cfg.get('cfg', st['cfg'])):g}",
        "--guidance", f"{float(cfg.get('guidance', st['guidance'])):g}",
        "--seed", str(int(cfg.get("seed", 42026))), "--sampler", str(cfg.get("sampler", st["sampler"])),
        "--scheduler", str(cfg.get("scheduler", st["scheduler"])),
    ]
    if model == "qwen_image" and cfg.get("lightning", True):
        cmd.append("--lightning")
    return cmd


def _scan_dir_by_ext(target_dir: str, exts: tuple[str, ...], recursive: bool = False) -> list[dict]:
    """Files with these extensions in target_dir (and, with recursive=True, its subfolders, except the
    "<name>_sizes" folders that hold an asset's size exports)."""
    if not os.path.isdir(target_dir):
        return []
    if recursive:
        names = []
        for here, dirs, files in os.walk(target_dir):
            dirs[:] = [d for d in dirs if not d.endswith("_sizes")]
            names += [os.path.relpath(os.path.join(here, f), target_dir) for f in files]
    else:
        names = os.listdir(target_dir)
    rows = []
    for name in names:
        if not name.lower().endswith(exts):
            continue
        full = os.path.join(target_dir, name)
        if not os.path.isfile(full):
            continue
        st = os.stat(full)
        mb = st.st_size / (1024 * 1024)
        rows.append({
            "path": full,
            "name": name,
            "size": f"{mb:.2f} MB" if mb >= 1.0 else f"{st.st_size / 1024:.0f} KB",
            "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "ts": st.st_mtime,
        })
    rows.sort(key=lambda r: r["ts"], reverse=True)
    return rows


def scan_photo_outputs(photo_dir: str = PHOTOS_DIR) -> list[dict]:
    return _scan_dir_by_ext(photo_dir, (".jpg", ".jpeg", ".png", ".webp"))


def start_streaming_process(cmd: list[str], out_q: queue.Queue) -> subprocess.Popen:
    """Launch subprocess streaming \\r/\\n chunks into out_q as ('line', text) and ('done', rc)."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env={**os.environ, "PYTHONUNBUFFERED": "1"})

    def reader():
        buf = ""
        while True:
            ch = proc.stdout.read(1)
            if not ch:
                if buf:
                    out_q.put(("line", buf + "\n"))
                break
            if ch in ("\r", "\n"):
                if buf.strip():
                    out_q.put(("line", buf.strip() + "\n"))
                buf = ""
            else:
                buf += ch
        out_q.put(("done", proc.wait()))

    threading.Thread(target=reader, daemon=True).start()
    return proc


def open_path_default(path: str):
    subprocess.Popen(["xdg-open", path], start_new_session=True)


def reveal_in_file_manager(path: str | None, fallback_dir: str):
    import shutil

    cmd = addons.REGISTRY.desktop.get("shortcuts", {}).get("reveal_file_cmd", "")
    if cmd and shutil.which(cmd):
        if path and os.path.isfile(path):
            subprocess.Popen([cmd, "--select", path], start_new_session=True)
        else:
            os.makedirs(fallback_dir, exist_ok=True)
            subprocess.Popen([cmd, fallback_dir], start_new_session=True)
        return
    if path and os.path.isfile(path) and shutil.which("dbus-send"):
        uri = f"file://{os.path.abspath(path)}"
        res = subprocess.run(
            [
                "dbus-send", "--session", "--dest=org.freedesktop.FileManager1", "--type=method_call",
                "/org/freedesktop/FileManager1", "org.freedesktop.FileManager1.ShowItems",
                f"array:string:{uri}", "string:",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if res.returncode == 0:
            return
    target = os.path.dirname(path) if path and os.path.isfile(path) else fallback_dir
    os.makedirs(target, exist_ok=True)
    open_path_default(target)


addons.attach_compat("studio_helpers", sys.modules[__name__])
