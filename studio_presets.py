"""Builder presets: one click sets the dropdowns that belong together for a look.

A preset only touches its own fields (style, lighting, scene, composition...). Everything else, including
the person and the vision, stays as it is for fine-tuning. Unlike templates (the creator's saved full
builder states), presets are built in and partial. Values are dropdown labels (the text before ":"),
resolved to full catalog options at import time so a typo fails loudly.
"""

from __future__ import annotations

import addons
from studio_prompt_catalog import FIELD_BY_KEY

_PRESETS = [
    ("Dark Spot-Color Wallpaper",
     "Monochrome anime figure on pure black, only the eyes in color, subject on the right (desktop wallpaper).",
     {"style": "Dark Monochrome Anime", "color_treatment": "Spot Color (Greyscale + Kept Color)", "spot_color": "Eyes",
      "lighting": "Low-Key Spotlight Fade", "scene": "None / Custom", "bg_type": "Solid Color", "bg_color": "Pure Black",
      "composition": "Right Third", "surface_prop": "None / Custom"}),
    ("White-on-Black Lineart Wallpaper",
     "Inverted sketch: white linework on pure black, subject on the right.",
     {"style": "Inverted Lineart (White on Black)", "color_treatment": "High-Contrast Black & White", "spot_color": "None / Custom",
      "lighting": "None / Custom", "scene": "None / Custom", "bg_type": "Solid Color", "bg_color": "Pure Black",
      "composition": "Right Third", "surface_prop": "None / Custom"}),
    ("Dark Charcoal Portrait",
     "Muted figure on a very dark grey vignette, centered; keeps your style.",
     {"color_treatment": "Muted / Desaturated", "lighting": "Low-Key Spotlight Fade", "scene": "None / Custom",
      "bg_type": "Radial Glow / Vignette", "bg_color": "Very Dark Grey (Charcoal)", "composition": "Centered"}),
    ("Paint-Splash Poster",
     "Bold character over paint splashes on white, full color.",
     {"color_treatment": "Full Vibrant Color", "scene": "None / Custom", "bg_type": "Paint Splashes", "bg_color": "White",
      "composition": "Centered", "surface_prop": "None / Custom"}),
    ("Retro Gradient Bands",
     "Sunset-colored repeating gradient stripes behind the subject.",
     {"scene": "None / Custom", "bg_type": "Repeating Gradient Bands", "bg_color": "Sunset Orange to Purple",
      "surface_prop": "None / Custom"}),
    ("Neo-Noir Night",
     "Moody rain-soaked city at night with hard shadows.",
     {"style": "Dark Neo-Noir Cinema", "lighting": "Neon Rainy Night", "scene": "Urban Rain-Slicked Alley",
      "framing": "Three-Quarter (Knees-Up)"}),
    ("Cyberpunk Neon",
     "Synthwave colors, neon rim light, techwear.",
     {"style": "Cyberpunk Synthwave Art", "lighting": "RGB Neon Accent Backlight", "scene": "Urban Rain-Slicked Alley",
      "attire": "Cyberpunk Techwear Jacket"}),
    ("Fantasy JRPG Adventure",
     "Polished JRPG art in sunlit ruins, armored and armed.",
     {"style": "Modern JRPG Illustration", "lighting": "Golden Hour Sunlight", "scene": "Ancient Forest Ruins",
      "attire": "Fantasy Leather RPG Armor", "surface_prop": "Holding Fantasy Weapon / Lantern"}),
    ("Visual Novel Sprite",
     "Full-body VN character on green screen, easy to cut out for a game.",
     {"style": "Anime Visual Novel", "lighting": "Diffused Studio Softbox", "scene": "Green-Screen Backdrop (#00FF00)",
      "framing": "Full Body (Head-to-Toe)", "composition": "Centered",
      "surface_prop": "Open Unobstructed Floor / Ground", "bg_type": "None / Custom", "bg_color": "None / Custom"}),
    ("Creator / Streamer Room",
     "Webcam look in a creator room with ring light.",
     {"style": "Creator 4K Webcam", "lighting": "Soft Front Ring-Light + Warm Fill", "scene": "Creator / Gaming Studio Room",
      "surface_prop": "In Ergonomic Gaming / Desk Chair", "framing": "Upper Body (Waist-Up)"}),
    ("Studio Character Reference",
     "Clean full-body reference on a plain studio backdrop (keeps your style).",
     {"lighting": "Diffused Studio Softbox", "scene": "Minimalist Photo Studio", "framing": "Full Body (Head-to-Toe)",
      "composition": "Centered", "pose": "Standing Relaxed (Hip Shift)", "surface_prop": "Open Unobstructed Floor / Ground",
      "bg_type": "None / Custom", "bg_color": "None / Custom"}),
]


def _option(key: str, label: str) -> str:
    for opt in FIELD_BY_KEY[key][3]:
        if opt.split(":", 1)[0].strip() == label:
            return opt
    raise ValueError(f"preset option not in the catalog: {key} = {label!r}")


_extend_presets = addons.REGISTRY.catalog.get("extend_presets")
if _extend_presets:
    _PRESETS = _extend_presets(_PRESETS)

PRESETS = [{"name": name, "about": about, "values": {k: _option(k, lab) for k, lab in vals.items() if k in FIELD_BY_KEY}}
           for name, about, vals in _PRESETS]


def apply_preset(values: dict[str, str], name: str) -> tuple[dict[str, str], list[str]]:
    """values with the preset's fields set; returns (new values, the field keys it changed)."""
    preset = next(p for p in PRESETS if p["name"] == name)
    out = dict(values)
    out.update(preset["values"])
    return out, list(preset["values"])
