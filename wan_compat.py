"""Builder-to-tab compatibility rules, best-setting selection, and restriction checks."""

import re

import addons
from wan_studio_helpers import CORE_PHOTO_MODEL_SETTINGS, MODEL_OPTIONS, VIDEO_MODEL_SETTINGS, get_photo_model_options


# Styles handled well by anime-focused checkpoints/prompts.
ANIME_TERMS = ("anime", "jrpg", "manga", "visual novel", "cel shad", "cel-shad", "2.5d", "comic",
               "pixel", "concept art", "oil painting", "illustration")
REALISTIC_TERMS = ("realistic", "cinema", "vlog", "noir", "tiktok", "editorial", "analog", "polaroid", "raw photo", "35mm")
CLEAN_TERMS = ("rating_safe", "sfw", "family-friendly", "clean", "censored", "fully clothed")


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
    if addons.REGISTRY.classify_intent:
        return addons.REGISTRY.classify_intent(values, extra_text, intent)
    return intent


def best_photo_model(intent: dict) -> str:
    """Choose the best photo model key for the classified intent."""
    if addons.REGISTRY.choose_photo_model:
        return addons.REGISTRY.choose_photo_model(intent, "flux2_klein")
    return "flux2_klein"


def content_negatives(intent: dict) -> list[str]:
    adds = []
    if intent["is_body_framing"]:
        adds.extend(["close-up", "headshot", "portrait", "cropped"])
    if addons.REGISTRY.extra_content_negatives:
        adds.extend(addons.REGISTRY.extra_content_negatives(intent))
    return adds


# Per-model render settings.
PHOTO_MODEL_SETTINGS = dict(addons.REGISTRY.photo_model_settings or CORE_PHOTO_MODEL_SETTINGS)
VIDEO_SETTINGS = {**VIDEO_MODEL_SETTINGS["2.2"], "fps": 16} if "2.2" in VIDEO_MODEL_SETTINGS else {}
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
QUICK_MOTION_TERMS = ("wave", "nod", "blink", "glance", "turn", "flinch", "jump")


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


def recommended_video_settings(values: dict[str, str], extra_text: str = "") -> dict:
    if not addons.REGISTRY.video_enabled:
        raise RuntimeError("Video generation is not enabled in the public edition.")
    intent = analyze_builder_intent(values, extra_text)
    motion = " ".join((values.get(k) or "") for k in ("motion", "expression", "camera_move")).lower()
    duration = 2.0 if any(t in motion for t in QUICK_MOTION_TERMS) else 4.0
    return {"version": "2.2", "width": 768, "height": 432, "duration": duration, **VIDEO_SETTINGS,
            "neg_additions": content_negatives(intent) + style_negatives(values), "intent": intent}


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

    for key, label in all_models:
        if key == "all":
            continue
        if addons.REGISTRY.filter_photo_compat:
            restrict_reason, reduced_warn = addons.REGISTRY.filter_photo_compat(intent, key, label)
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
    fallback_key = addons.REGISTRY.default_photo_model or "flux2_klein"
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


def evaluate_video_compat(values: dict[str, str], has_start_image: bool, extra_text: str = "") -> dict:
    """Return best video model, restricted models, start-image requirement, and negative guards."""
    if not addons.REGISTRY.video_enabled:
        raise RuntimeError("Video generation is not enabled in the public edition.")
    intent = analyze_builder_intent(values, extra_text)
    overrides = addons.REGISTRY.video_compat_overrides(intent, has_start_image) if addons.REGISTRY.video_compat_overrides else {}
    restrict_21 = overrides.get("restrict_21") if addons.REGISTRY.video_compat_overrides else (
        "Text-only model does not support Start Image (I2V)" if has_start_image else None
    )
    allowed, restricted = [], []
    for ver, label in MODEL_OPTIONS:
        if ver == "2.1" and restrict_21:
            restricted.append((ver, label, restrict_21))
        else:
            allowed.append((ver, label))

    neg_adds = content_negatives(intent)
    needs_start_image = bool(overrides.get("needs_start_image", False))
    return {
        "intent": intent,
        "best_model": "2.2",
        "best_preset": "16:9 Cutscene (768x432, 4.0s @ 16 fps)",
        "best_cfg": 5.0,
        "best_steps": 20,
        "allowed_models": allowed,
        "restricted_models": restricted,
        "needs_start_image": needs_start_image,
        "neg_additions": neg_adds,
    }
