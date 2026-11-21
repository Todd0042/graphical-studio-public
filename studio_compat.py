"""Builder-to-tab compatibility rules, best-setting selection, and model routing."""

import re
import sys

import addons
from studio_helpers import CORE_PHOTO_MODEL_SETTINGS, get_photo_model_options


# Styles handled well by anime-focused checkpoints/prompts.
ANIME_TERMS = ("anime", "jrpg", "manga", "visual novel", "cel shad", "cel-shad", "2.5d", "comic",
               "pixel", "concept art", "oil painting", "illustration")
REALISTIC_TERMS = ("realistic", "cinema", "vlog", "noir", "tiktok", "editorial", "analog", "polaroid", "raw photo", "35mm")


def _has_any(text: str, terms) -> bool:
    return any(re.search(rf"(?<![a-z]){re.escape(t)}", text) for t in terms)


def analyze_builder_intent(values: dict[str, str], extra_text: str = "") -> dict:
    """Classify what the picture is: from the dropdowns plus any free text (custom vision / final prompt)."""
    style = (values.get("style") or "").lower()
    framing = (values.get("framing") or "").lower()
    scene = (values.get("scene") or "").lower()
    gender = (values.get("gender") or "").lower()
    text = (extra_text or "").lower()

    is_anime = _has_any(f"{style} {text}", ANIME_TERMS)
    is_realistic = _has_any(style, REALISTIC_TERMS) and not is_anime
    is_body_framing = any(k in framing for k in ("cowboy", "upper body", "full body", "three-quarter", "mirror selfie"))
    is_wide = any(k in (framing + " " + scene) for k in ("wide", "penthouse", "beach", "street", "coffee", "rooftop", "tavern", "ruins", "starship")) and not is_body_framing
    has_people = not ("no humans" in f"{gender} {scene} {text}" or "empty environment" in gender or "no people" in text)
    intent = {
        "is_anime": is_anime,
        "is_realistic": is_realistic,
        "is_body_framing": is_body_framing,
        "is_wide": is_wide,
        "has_people": has_people,
    }
    classify = addons.REGISTRY.catalog.get("classify_intent")
    if classify:
        return classify(values, extra_text, intent)
    return intent


def best_photo_model(intent: dict) -> str:
    """Choose the best photo model key for the classified intent."""
    chooser = addons.REGISTRY.catalog.get("choose_photo_model")
    if chooser:
        return chooser(intent, "flux2_klein")
    return "flux2_klein"


def content_negatives(intent: dict) -> list[str]:
    adds = []
    if intent["is_body_framing"]:
        adds.extend(["close-up", "headshot", "portrait", "cropped"])
    extra_fn = addons.REGISTRY.catalog.get("extra_content_negatives")
    if extra_fn:
        adds.extend(extra_fn(intent))
    return adds


# Per-model render settings.
PHOTO_MODEL_SETTINGS = dict(addons.REGISTRY.models.get("photo_settings") or CORE_PHOTO_MODEL_SETTINGS)
# Extra negatives a dropdown choice needs to hold its look: field -> short label -> negatives.
FIELD_NEGATIVES = {
    "style": {
        "Dark Monochrome Anime": ["bright background", "pastel colors"],
        "Inverted Lineart (White on Black)": ["shading", "color", "gradient", "white background", "detailed background"],
    },
    "color_treatment": {
        "Monochrome Greyscale": ["colorful", "saturated colors"],
        "High-Contrast Black & White": ["colorful", "saturated colors", "sepia"],
        "Spot Color (Greyscale + Kept Color)": ["multicolored", "colorful background", "saturated skin"],
        "Muted / Desaturated": ["oversaturated", "neon colors"],
    },
    "bg_type": {label: ["detailed background", "scenery", "furniture", "room interior"]
                for label in ("Solid Color", "Linear Gradient", "Radial Glow / Vignette", "Repeating Gradient Bands",
                              "Two-Tone Split", "Polka Dots", "Halftone Dots", "Geometric Pattern")},
    "bg_color": {
        "Pure Black": ["white background", "bright background", "grey background"],
        "Very Dark Grey (Charcoal)": ["white background", "bright background"],
    },
}
WIDE_POSITIONS = ("Far Left", "Left Third", "Right Third", "Far Right", "Small Figure, Vast Space")


def recommended_photo_settings(values: dict[str, str], extra_text: str = "") -> dict:
    """Everything the photo generator needs, chosen from what the builder prompt describes."""
    intent = analyze_builder_intent(values, extra_text)
    model = best_photo_model(intent)
    if (values.get("composition") or "").split(":", 1)[0].strip() in WIDE_POSITIONS:
        preset = "16:9 HD Background (1280x720)"  # the empty side needs a wide canvas
    elif intent["is_body_framing"]:
        preset = "Character Bust Portrait (832x1024)"
    elif "icon" in (values.get("framing") or "").lower():
        preset = "Square 1:1 Icon (1024x1024)"
    else:
        preset = "16:9 HD Background (1280x720)"
    return {"model": model, "preset": preset, **PHOTO_MODEL_SETTINGS[model],
            "vary_person": intent["has_people"], "neg_additions": content_negatives(intent) + style_negatives(values),
            "intent": intent}


def style_negatives(values: dict[str, str]) -> list[str]:
    """Negatives the chosen style, color treatment and background need (no duplicates)."""
    out: list[str] = []
    for field, by_label in FIELD_NEGATIVES.items():
        label = (values.get(field) or "").split(":", 1)[0].strip()
        out += [n for n in by_label.get(label, []) if n not in out]
    return out


def evaluate_photo_compat(values: dict[str, str], extra_text: str = "") -> dict:
    """Return best model/preset/cfg, restricted models, reduced-quality warnings, and negative guards."""
    intent = analyze_builder_intent(values, extra_text)
    all_models = get_photo_model_options()
    allowed, restricted, reduced = [], [], {}
    filter_fn = addons.REGISTRY.catalog.get("filter_photo_compat")

    for key, label in all_models:
        if key == "all":
            continue
        if filter_fn:
            restrict_reason, reduced_warn = filter_fn(intent, key, label)
            if restrict_reason:
                restricted.append((key, label, restrict_reason))
                continue
            if reduced_warn:
                reduced[key] = reduced_warn
        allowed.append((key, label))

    best_key = best_photo_model(intent)
    if not any(k == best_key for k, _ in allowed) and allowed:
        best_key = allowed[0][0]
    rec = recommended_photo_settings(values, extra_text)
    best_preset = rec["preset"]
    fallback_key = addons.REGISTRY.models.get("default_photo_model") or "flux2_klein"
    best_cfg = PHOTO_MODEL_SETTINGS.get(best_key, PHOTO_MODEL_SETTINGS[fallback_key])["cfg"]
    neg_adds = content_negatives(intent)

    return {
        "intent": intent,
        "best_model": best_key,
        "best_preset": best_preset,
        "best_cfg": best_cfg,
        "allowed_models": allowed,
        "restricted_models": restricted,
        "reduced_warnings": reduced,
        "neg_additions": neg_adds,
    }


addons.attach_compat("studio_compat", sys.modules[__name__])
