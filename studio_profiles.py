"""Saved Character Profiles and automatic facial-identity variation for Graphical Studio."""

import json
import os
import random
import re
import shutil

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILES_JSON = os.path.join(ROOT_DIR, "character_profiles.json")
PROFILES_DIR = os.path.join(ROOT_DIR, "character_profiles")
PHOTO_META_JSON = os.path.join(ROOT_DIR, ".cache", "photo_meta.json")

PROFILE_MODE_VARY = "🎲 Vary Person Each Run (Auto Variety)"
PROFILE_MODE_NONE = "None (Prompt Only)"

_FACE_SHAPES = [
    "soft oval face shape with gently rounded cheeks",
    "delicate heart-shaped face with tapered chin",
    "defined sculpted jawline and high prominent cheekbones",
    "diamond face structure with refined cheekbones",
    "slender elongated face with graceful bone structure",
    "youthful softly contoured cheeks and balanced chin",
    "slightly angular editorial jawline and crisp cheek hollows",
]

_NOSE_BROW = [
    "delicate slightly upturned button nose and softly arched natural brows",
    "straight classic nose bridge and full feathered eyebrows",
    "petite refined nose and sleek sculpted eyebrows",
    "subtle graceful nose bridge and expressive thick natural brows",
    "softly rounded nose tip and neatly arched dark brows",
    "narrow high-bridged nose and clean straight brows",
]

_EYE_MOUTH_CUES = [
    "almond-shaped expressive eyes and soft full natural lips",
    "wide bright round eyes and defined Cupid's bow lips",
    "slightly upturned cat-like eyes and warm relaxed smile lines",
    "deep-set soulful eyes and balanced natural plush lips",
    "long-lashed softly hooded eyes and subtle confident half-smile",
    "bright sparkling eyes and charming faint cheek dimples",
]

_UNIQUE_MARKS = [
    "distinct individual facial identity",
    "tiny subtle beauty mark near cheekbone",
    "faint natural nose-bridge freckles",
    "subtle dimple on left cheek",
    "unique authentic non-generic facial features",
    "natural slight asymmetry for realistic human individuality",
    "softly sculpted collarbone and unique expressive profile",
]

_HERITAGE_BLENDS = [
    "subtle Mediterranean facial features",
    "subtle Northern European Scandinavian facial features",
    "subtle Slavic Eastern European facial features",
    "subtle Irish-Celtic facial features",
    "subtle Latin American facial features",
    "subtle mixed-heritage American facial features",
    "subtle French-Italian facial features",
    "subtle Californian coastal American look",
    "subtle East-West mixed facial features",
    "subtle Brazilian warm facial features",
]

_HERITAGE_GUARD_WORDS = (
    "latina", "latino", "hispanic", "asian", "japanese", "korean", "chinese",
    "indian", "black", "african", "ebony", "nordic", "scandinavian", "slavic",
    "irish", "italian", "french", "brazilian", "olive", "porcelain", "caramel",
    "dark skin", "deep warm", "mediterranean",
)


def generate_random_person_variation(prompt_text: str = "", rng: random.Random | None = None) -> str:
    """Create a fresh, non-clashing facial-identity clause to break checkpoint same-face syndrome."""
    r = rng or random
    low = (prompt_text or "").lower()
    parts = [
        r.choice(_FACE_SHAPES),
        r.choice(_NOSE_BROW),
        r.choice(_EYE_MOUTH_CUES),
    ]
    mark = r.choice(_UNIQUE_MARKS)
    if "freckle" in mark and "freckle" in low:
        mark = "distinct individual facial identity"
    parts.append(mark)
    if not any(w in low for w in _HERITAGE_GUARD_WORDS):
        parts.append(r.choice(_HERITAGE_BLENDS))
    return ", ".join(parts)


def load_profiles() -> dict[str, dict]:
    try:
        with open(PROFILES_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def save_profiles(profiles: dict[str, dict]):
    os.makedirs(os.path.dirname(PROFILES_JSON), exist_ok=True)
    with open(PROFILES_JSON, "w", encoding="utf-8") as f:
        json.dump(profiles, f, indent=2)


def get_profile_dropdown_values() -> list[str]:
    names = sorted(load_profiles().keys(), key=str.lower)
    return [PROFILE_MODE_VARY, PROFILE_MODE_NONE] + [f"👤 {n}" for n in names]


def parse_profile_selection(selection: str) -> tuple[str, str]:
    """Return (mode, profile_name) where mode is 'vary', 'none', or 'profile'."""
    s = (selection or "").strip()
    if s == PROFILE_MODE_VARY:
        return "vary", ""
    if s.startswith("👤 "):
        return "profile", s[2:].strip()
    return "none", ""


def resolve_profile_ref_image(profile: dict) -> str:
    rel = (profile.get("ref_image") or "").strip()
    if not rel:
        return ""
    if os.path.isabs(rel) and os.path.isfile(rel):
        return rel
    abs_p = os.path.join(ROOT_DIR, rel)
    return abs_p if os.path.isfile(abs_p) else ""


def save_character_profile(
    name: str,
    traits: str,
    source_image: str = "",
    ref_weight: float = 0.72,
    model_key: str = "",
    seed: int = 0,
) -> dict:
    clean_name = re.sub(r"\s+", " ", (name or "").strip())
    if not clean_name:
        raise ValueError("Profile name cannot be empty.")
    rel_img = ""
    if source_image and os.path.isfile(source_image):
        os.makedirs(PROFILES_DIR, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "_", clean_name.lower()).strip("_") or "character"
        ext = os.path.splitext(source_image)[1].lower() or ".jpg"
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            ext = ".jpg"
        dest = os.path.join(PROFILES_DIR, f"{slug}{ext}")
        if os.path.abspath(source_image) != os.path.abspath(dest):
            shutil.copy2(source_image, dest)
        rel_img = os.path.relpath(dest, ROOT_DIR)

    profiles = load_profiles()
    entry = {
        "name": clean_name,
        "traits": (traits or "").strip(),
        "ref_image": rel_img,
        "ref_weight": round(float(ref_weight), 2),
        "model": model_key,
        "seed": int(seed) if seed else 0,
    }
    profiles[clean_name] = entry
    save_profiles(profiles)
    return entry


def delete_character_profile(name: str) -> bool:
    profiles = load_profiles()
    if name not in profiles:
        return False
    entry = profiles.pop(name)
    save_profiles(profiles)
    rel = entry.get("ref_image", "")
    if rel and not os.path.isabs(rel):
        p = os.path.join(ROOT_DIR, rel)
        if os.path.isfile(p) and os.path.abspath(p).startswith(os.path.abspath(PROFILES_DIR)):
            try:
                os.remove(p)
            except Exception:
                pass
    return True


def record_photo_meta(out_path: str, meta: dict):
    """Remember exact prompt/variation/seed/model used to create a photo so Save Profile captures it."""
    if not out_path:
        return
    os.makedirs(os.path.dirname(PHOTO_META_JSON), exist_ok=True)
    all_meta = {}
    try:
        with open(PHOTO_META_JSON, "r", encoding="utf-8") as f:
            loaded = json.load(f)
            if isinstance(loaded, dict):
                all_meta = loaded
    except Exception:
        pass
    key = os.path.basename(out_path)
    all_meta[key] = meta
    # Keep metadata map compact (latest 300 photos)
    if len(all_meta) > 300:
        for old_k in list(all_meta.keys())[:-300]:
            all_meta.pop(old_k, None)
    try:
        with open(PHOTO_META_JSON, "w", encoding="utf-8") as f:
            json.dump(all_meta, f, indent=2)
    except Exception:
        pass


def get_photo_meta(photo_path: str) -> dict:
    if not photo_path:
        return {}
    try:
        with open(PHOTO_META_JSON, "r", encoding="utf-8") as f:
            all_meta = json.load(f)
            if isinstance(all_meta, dict):
                return all_meta.get(os.path.basename(photo_path), {})
    except Exception:
        pass
    return {}


def extract_person_traits_from_prompt(prompt_text: str, variation_clause: str = "") -> str:
    """Extract person-defining cues (gender, hair, eyes, skin, build, age, face) cleanly for a profile."""
    from studio_prompt_catalog import PERSON_FIELDS, ascertain_fields_from_prompt, extract_clause

    asc = ascertain_fields_from_prompt(prompt_text or "")
    clauses = []
    for key, _, _, _ in PERSON_FIELDS:
        cl = extract_clause(asc.get(key, ""))
        if cl:
            clauses.append(cl)
    if (variation_clause or "").strip():
        clauses.append(variation_clause.strip())
    if not clauses and (prompt_text or "").strip():
        return prompt_text.strip()
    return ", ".join(clauses)
