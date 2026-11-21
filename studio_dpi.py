"""Automatic cross-machine DPI & UI scaling helper for Graphical Studio (Tkinter)."""

import json
import os
import re
import shutil
import subprocess

SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui_settings.json")

# Base design dimensions at 1.0x (96 DPI)
BASE_WIN_W = 1260
BASE_WIN_H = 880

SCALE_OPTIONS = [
    ("auto", "Auto (Match Display DPI)"),
    ("0.75", "75% (Compact)"),
    ("0.85", "85%"),
    ("0.90", "90%"),
    ("1.00", "100% (Default 96 DPI)"),
    ("1.15", "115%"),
    ("1.25", "125%"),
    ("1.40", "140%"),
    ("1.50", "150%"),
    ("1.75", "175%"),
    ("2.00", "200% (4K / HiDPI)"),
]

CURRENT_SCALE: float = 1.0
LAST_DETECTED_DPI: float = 96.0
LAST_AUTO_SCALE: float = 1.0
_LISTENERS: list = []

_BASE_NAMED_FONTS = {
    "TkDefaultFont": 13,
    "TkTextFont": 13,
    "TkFixedFont": 12,
    "TkMenuFont": 13,
    "TkHeadingFont": 13,
    "TkCaptionFont": 13,
    "TkSmallCaptionFont": 12,
    "TkIconFont": 13,
    "TkTooltipFont": 12,
}

# Shared tkfont.Font instances (initialized on root) using negative pixel sizes so
# Linux Xft / XWayland never overrides font scaling regardless of Xft.dpi.
_CUSTOM_FONTS: dict = {}
_CUSTOM_FONT_SPECS = {
    "ui": ("Sans", 13, "normal"),
    "ui_bold": ("Sans", 13, "bold"),
    "ui_heading": ("Sans", 12, "bold"),
    "small": ("Sans", 11, "normal"),
    "small_bold": ("Sans", 11, "bold"),
    "mono": ("Monospace", 12, "normal"),
}


def get_font(key: str):
    """Return a shared, live-scaling tkfont.Font object by semantic role."""
    if key in _CUSTOM_FONTS:
        return _CUSTOM_FONTS[key]
    fam, base_px, weight = _CUSTOM_FONT_SPECS.get(key, ("Sans", 13, "normal"))
    return (fam, -s(base_px, 8), weight) if weight != "normal" else (fam, -s(base_px, 8))


def s(px: int | float, minimum: int = 1) -> int:
    """Scale a pixel dimension by the active UI scale factor."""
    return max(minimum, int(round(px * CURRENT_SCALE)))


def _read_settings() -> dict:
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _write_settings(updates: dict):
    data = _read_settings()
    data.update(updates)
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def load_saved_scale() -> str:
    env_override = os.environ.get("GRAPHICAL_STUDIO_SCALE", "").strip().lower()
    if env_override:
        return env_override
    val = str(_read_settings().get("ui_scale", "auto")).strip().lower()
    valid = {k for k, _ in SCALE_OPTIONS}
    if val in valid:
        return val
    try:
        f = float(val)
        if 0.6 <= f <= 2.5:
            return f"{f:.2f}"
    except ValueError:
        pass
    return "auto"


def save_scale(scale_pref: str):
    _write_settings({"ui_scale": str(scale_pref)})


def detect_monitor_size(root) -> tuple[int, int]:
    """Return usable single-monitor (width, height) in Tk screen pixels."""
    _, mon_size = _detect_linux_physical_dpi(root, fallback_root_size=False)
    if mon_size:
        return mon_size
    sw = max(640, int(root.winfo_screenwidth()))
    sh = max(480, int(root.winfo_screenheight()))
    # On side-by-side multi-monitor X11 virtual desktops, winfo_screenwidth() spans
    # all outputs (e.g. 3343x1200). Cap single-monitor aspect ratio cleanly.
    if sw > int(sh * 2.25):
        sw = min(sw, int(round(sh * 16.0 / 9.0)))
    return sw, sh


def _detect_linux_physical_dpi(root, fallback_root_size: bool = True) -> tuple[float, tuple[int, int] | None]:
    """Read physical DPI and primary monitor pixel size via xrandr / Linux DRM EDID.

    Works even when desktop compositor scaling is intentionally left at 1.0x
    (e.g. for WINE games) and when multiple monitors are attached side-by-side.
    """
    # 1. Try xrandr --query (gives exact active pixel mode + physical mm per output)
    if shutil.which("xrandr"):
        try:
            out = subprocess.check_output(
                ["xrandr", "--query"], text=True, stderr=subprocess.DEVNULL, timeout=1.5
            )
            primary_dpi = None
            primary_size = None
            first_dpi = None
            first_size = None
            pat = re.compile(
                r"^\S+\s+connected\s+(primary\s+)?(\d+)x(\d+)\+\d+\+\d+.*?(\d+)mm\s+x\s+(\d+)mm",
                re.MULTILINE,
            )
            for m in pat.finditer(out):
                is_prim = bool(m.group(1))
                pw, ph = int(m.group(2)), int(m.group(3))
                mm_w, mm_h = int(m.group(4)), int(m.group(5))
                if pw >= 640 and ph >= 480 and mm_w >= 120 and mm_h >= 80:
                    dpi = 0.5 * (pw / (mm_w / 25.4) + ph / (mm_h / 25.4))
                    if first_dpi is None:
                        first_dpi, first_size = dpi, (pw, ph)
                    if is_prim:
                        primary_dpi, primary_size = dpi, (pw, ph)
                        break
            if primary_dpi is not None:
                return primary_dpi, primary_size
            if first_dpi is not None:
                return first_dpi, first_size
        except Exception:
            pass

    if not fallback_root_size:
        return 0.0, None

    # 2. Fallback: Linux kernel DRM EDID (works on Wayland even if xrandr lacks mm)
    try:
        import glob

        # Prefer active internal panel (eDP) if present, else first connected output
        candidates = sorted(glob.glob("/sys/class/drm/card*-*/edid"))
        candidates.sort(key=lambda p: (0 if "eDP" in p else 1, p))
        sw = max(640, int(root.winfo_screenwidth()))
        sh = max(480, int(root.winfo_screenheight()))
        if sw > int(sh * 2.25):
            sw = min(sw, int(round(sh * 16.0 / 9.0)))
        for edid_path in candidates:
            st_path = os.path.join(os.path.dirname(edid_path), "status")
            if not os.path.isfile(st_path):
                continue
            with open(st_path, "r", encoding="utf-8", errors="ignore") as f:
                if f.read().strip() != "connected":
                    continue
            with open(edid_path, "rb") as f:
                data = f.read()
            if len(data) < 69:
                continue
            # Prefer exact mm from DTD (bytes 66-68), fall back to cm (bytes 21-22)
            mm_w = data[66] | ((data[68] & 0xF0) << 4)
            mm_h = data[67] | ((data[68] & 0x0F) << 8)
            if mm_w < 120 or mm_h < 80:
                mm_w, mm_h = data[21] * 10, data[22] * 10
            if mm_w >= 120 and mm_h >= 80:
                # Match output vertical height (reliable even on multi-monitor horizontal spans)
                dpi_y = sh / (mm_h / 25.4)
                dpi_x = sw / (mm_w / 25.4)
                dpi = dpi_y if abs(dpi_x - dpi_y) > 25.0 else 0.5 * (dpi_x + dpi_y)
                if 70.0 <= dpi <= 360.0:
                    return dpi, (sw, sh)
    except Exception:
        pass

    return 0.0, None


def detect_raw_dpi(root) -> float:
    """Dynamically detect effective display DPI (zero machine-specific hardcoding)."""
    logical_dpi = 96.0

    # 1. Dedicated desktop toolkit scale environment variables (if non-default)
    for env_key in ("GDK_SCALE", "QT_SCALE_FACTOR", "ELM_SCALE"):
        raw = os.environ.get(env_key, "").strip()
        if raw:
            try:
                f = float(raw)
                if 0.5 <= f <= 4.0 and abs(f - 1.0) > 0.04:
                    logical_dpi = max(logical_dpi, 96.0 * f)
            except ValueError:
                pass

    # 2. X11 / XWayland Xft.dpi (set automatically when DE scaling is active)
    if shutil.which("xrdb"):
        try:
            out = subprocess.check_output(
                ["xrdb", "-query"], text=True, stderr=subprocess.DEVNULL, timeout=1.5
            )
            m = re.search(r"Xft\.dpi:\s*([0-9.]+)", out)
            if m:
                dpi = float(m.group(1))
                if 60.0 <= dpi <= 480.0:
                    logical_dpi = max(logical_dpi, dpi)
        except Exception:
            pass

    # 3. Tk's reported logical DPI (works natively on Windows/macOS and scaled X11)
    try:
        d = float(root.winfo_fpixels("1i"))
        if 60.0 <= d <= 480.0:
            logical_dpi = max(logical_dpi, d)
    except Exception:
        pass

    # 4. True physical DPI of the active primary monitor (catches unscaled HiDPI panels
    #    where DE scaling is kept at 1.0x for WINE/games, and multi-monitor XWayland spans)
    phys_dpi, _ = _detect_linux_physical_dpi(root)
    if 70.0 <= phys_dpi <= 360.0:
        return max(logical_dpi, phys_dpi)

    # 5. Generic Tk screenmm fallback (single-monitor Windows/macOS/X11)
    try:
        sw = int(root.winfo_screenwidth())
        sh = int(root.winfo_screenheight())
        mm_w = int(root.winfo_screenmmwidth())
        mm_h = int(root.winfo_screenmmheight())
        if sw <= int(sh * 2.25) and mm_w >= 120 and mm_h >= 80:
            phys = 0.5 * (sw / (mm_w / 25.4) + sh / (mm_h / 25.4))
            if 70.0 <= phys <= 360.0:
                return max(logical_dpi, phys)
    except Exception:
        pass

    return logical_dpi


def detect_auto_scale(root) -> float:
    """Compute an automatic UI scale that honors display DPI while keeping the window on-screen."""
    global LAST_DETECTED_DPI, LAST_AUTO_SCALE
    dpi = detect_raw_dpi(root)
    LAST_DETECTED_DPI = dpi
    dpi_scale = dpi / 96.0
    # Standard ~90-102 DPI desktop monitors stay cleanly at 1.00x
    if 0.90 <= dpi_scale <= 1.06:
        dpi_scale = 1.00

    sw, sh = detect_monitor_size(root)
    # Ensure the base 1260x880 layout fits comfortably inside the active monitor with taskbar margin
    fit_cap = min((sw * 0.94) / BASE_WIN_W, (sh * 0.88) / BASE_WIN_H)
    scale = min(dpi_scale, fit_cap)
    scale = max(0.70, min(2.25, scale))
    # Snap to clean 0.05 increments so fonts and borders look crisp
    scale = round(scale * 20.0) / 20.0
    LAST_AUTO_SCALE = scale
    return scale


def resolve_scale(root, pref: str | None = None) -> float:
    pref_s = (pref if pref is not None else load_saved_scale()).strip().lower()
    auto = detect_auto_scale(root)
    if pref_s in ("", "auto"):
        return auto
    try:
        return max(0.65, min(2.50, float(pref_s)))
    except ValueError:
        return auto


def fit_window_geometry(win, base_w: int, base_h: int, min_w: int, min_h: int):
    """Apply scaled window geometry and minsize clamped safely to the current monitor."""
    sw, sh = detect_monitor_size(win)
    max_w = max(640, int(sw * 0.95))
    max_h = max(480, int(sh * 0.90))
    w = min(s(base_w), max_w)
    h = min(s(base_h), max_h)
    mw = min(s(min_w), w)
    mh = min(s(min_h), h)
    win.minsize(mw, mh)
    win.geometry(f"{w}x{h}")


def register_scale_listener(fn):
    if fn not in _LISTENERS:
        _LISTENERS.append(fn)


def apply_ui_scale(root, pref: str | None = None, persist: bool = False) -> float:
    """Apply DPI-aware Tk pixel font scaling and notify registered layout listeners."""
    global CURRENT_SCALE
    import tkinter.font as tkfont

    pref_s = (pref if pref is not None else load_saved_scale()).strip().lower()
    scale = resolve_scale(root, pref_s)
    CURRENT_SCALE = scale

    # Update all Tk built-in named fonts using NEGATIVE pixel sizes (-px).
    # Unlike positive point sizes, negative pixel sizes are honored identically on
    # Linux Xft/XWayland, Windows, and macOS even when Xft.dpi or tk scaling is fixed.
    for fname, base_px in _BASE_NAMED_FONTS.items():
        try:
            f = tkfont.nametofont(fname)
            f.configure(size=-s(base_px, 8))
        except Exception:
            pass

    # Create or live-update shared custom font objects (auto-updates every widget bound to them)
    for key, (fam, base_px, weight) in _CUSTOM_FONT_SPECS.items():
        px = -s(base_px, 8)
        if key not in _CUSTOM_FONTS:
            try:
                _CUSTOM_FONTS[key] = tkfont.Font(root=root, family=fam, size=px, weight=weight)
            except Exception:
                pass
        else:
            try:
                _CUSTOM_FONTS[key].configure(size=px)
            except Exception:
                pass

    # Ensure Menus, Entry, Combobox popdowns, and standard widgets inherit scaled default font
    try:
        ui_f = _CUSTOM_FONTS.get("ui")
        if ui_f is not None:
            root.option_add("*Font", ui_f)
            root.option_add("*TCombobox*Listbox.font", ui_f)
            root.option_add("*Menu.font", ui_f)
    except Exception:
        pass

    if persist:
        save_scale(pref_s)

    for cb in list(_LISTENERS):
        try:
            cb(scale)
        except Exception:
            pass

    return scale
