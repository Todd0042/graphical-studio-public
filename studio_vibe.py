"""Generate every Builder dropdown from custom text alone, matching its vibe.

Primary path: the local instruct LLM picks one catalog option per field.
Offline fallback: keyword vibe profiles + direct-mention matching.
"""

import re

import addons
from studio_prompt_catalog import ALL_FIELDS, FIELD_BY_KEY


def _label(opt: str) -> str:
    return opt.split(":", 1)[0].strip()


def _opt(key: str, label: str) -> str:
    for opt in FIELD_BY_KEY[key][3]:
        if _label(opt) == label:
            return opt
    raise KeyError(f"{key}: no option labelled {label!r}")


def is_default(key: str, value: str) -> bool:
    v = (value or "").strip()
    return not v or v == FIELD_BY_KEY[key][3][0] or v.lower().startswith("none")


def is_custom_text_only(values: dict[str, str], notes: str) -> bool:
    """True when custom text is filled in but every dropdown is still at its default."""
    return bool((notes or "").strip()) and all(is_default(k, values.get(k, "")) for k, _, _, _ in ALL_FIELDS)


# ── Offline fallback: vibe profiles ──────────────────────────────────────────
# Each profile: trigger words -> field labels. Fields a profile leaves out come from _NEUTRAL.
_NEUTRAL = {
    "style": "American Realistic Photo", "lighting": "Golden Hour Sunlight", "framing": "Upper Body (Waist-Up)",
    "gender": "Solo Woman", "symmetry": "Everyday Natural Pretty", "age": "Mid 20s Adult", "build": "Slender Athletic",
    "hair_color": "Warm Caramel Brown", "hair_style": "Soft Loose Shoulder Waves", "eyes": "Hazel (Green-Gold Flecks)",
    "skin": "Natural Realistic Texture", "makeup_acc": "Soft Everyday Dewy Glam", "attire": "Fitted White Tee & Blue Jeans",
    "pose": "Standing Relaxed (Hip Shift)", "surface_prop": "Open Unobstructed Floor / Ground", "scene": "Botanical Park Walkway",
}

_VIBES = [
    ({"noir", "detective", "crime", "gritty", "moody", "mysterious", "shadow", "shadows", "smoky", "rain", "rainy", "night", "dark", "brooding"}, {
        "style": "Dark Neo-Noir Cinema", "lighting": "Dramatic Chiaroscuro Rim", "framing": "Three-Quarter (Knees-Up)",
        "symmetry": "Angular High-Fashion", "age": "Early 30s Prime", "hair_color": "Jet Raven Black", "hair_style": "Sleek Straight Tucked Behind Ear",
        "eyes": "Ice-Blue / Storm Grey", "makeup_acc": "Winged Eyeliner & Bold Lip", "attire": "Leather Moto Jacket & Dark Jeans",
        "pose": "Leaning Back / Angled Relaxed", "surface_prop": "Against Wall / Doorframe", "scene": "Urban Rain-Slicked Alley",
    }),
    ({"cyberpunk", "neon", "synthwave", "futuristic", "future", "cyber", "techwear", "hacker", "dystopian", "sci", "scifi", "space", "starship", "android", "robot"}, {
        "style": "Cyberpunk Synthwave Art", "lighting": "RGB Neon Accent Backlight", "framing": "Cowboy Shot (Thighs-Up)",
        "symmetry": "Angular High-Fashion", "age": "Late 20s Adult", "hair_color": "Midnight Blue / Teal Tips", "hair_style": "Wolf Cut Shaggy Layers",
        "eyes": "Glowing Arcane / Cyber Irises", "skin": "Smooth Stylized Finish", "makeup_acc": "Subtle Tattoos & Piercings", "attire": "Cyberpunk Techwear Jacket",
        "pose": "Standing Tall Confident", "scene": "Urban Rain-Slicked Alley",
    }),
    ({"fantasy", "medieval", "elf", "elven", "wizard", "sorceress", "knight", "dragon", "quest", "adventurer", "magic", "magical", "tavern", "enchanted", "ruins", "rpg", "warrior"}, {
        "style": "Hand-Painted Fantasy Concept", "lighting": "Warm Hearth Ember Glow", "framing": "Full Body (Head-to-Toe)",
        "gender": "Fantasy Adventurer Woman", "symmetry": "High Symmetry (Classic)", "hair_color": "Copper Auburn Red", "hair_style": "Long Flowing Layered",
        "eyes": "Emerald Green", "makeup_acc": "Layered Delicate Gold Jewelry", "attire": "Fantasy Leather RPG Armor", "pose": "Standing Tall Confident",
        "surface_prop": "Holding Fantasy Weapon / Lantern", "scene": "Ancient Forest Ruins",
    }),
    ({"beach", "summer", "ocean", "sea", "coast", "tropical", "sunny", "vacation", "surf", "seaside", "island", "sand"}, {
        "style": "American Realistic Photo", "lighting": "Golden Hour Sunlight", "framing": "Full Body (Head-to-Toe)",
        "hair_color": "Golden Honey Blonde", "hair_style": "Beach Tousled Waves", "eyes": "Crystal Ocean Blue", "skin": "Warm Sun-Kissed Olive",
        "makeup_acc": "Stylish Sunglasses", "attire": "Floral Summer Sundress", "pose": "Mid-Stride Walking Forward", "scene": "Sandy Ocean Coastline",
    }),
    ({"cozy", "comfy", "lazy", "sunday", "home", "homey", "relaxed", "relaxing", "chill", "snug", "rainy-day", "blanket", "sweater", "morning", "coffee"}, {
        "style": "35mm Analog Film (Kodak Portra)", "lighting": "Dappled Filtered Sunlight", "framing": "Upper Body (Waist-Up)",
        "hair_style": "Casual Messy Bun", "makeup_acc": "Bare-Faced / Minimal Natural", "attire": "Cozy Knit Pullover Sweater",
        "pose": "Seated Lounging Back", "surface_prop": "Holding Iced Coffee / Mug", "scene": "Modern Apartment Living Room",
    }),
    ({"romantic", "evening", "dinner", "elegant", "formal", "luxury"}, {
        "style": "Cinematic Film Still", "lighting": "Warm Hearth Ember Glow", "framing": "Medium Close-Up (Chest-Up)",
        "symmetry": "Soft Oval Delicate", "hair_color": "Rich Chestnut Brunette", "hair_style": "Voluminous Bouncy Curls", "eyes": "Warm Chocolate Brown",
        "makeup_acc": "Smoky Evening Glam", "attire": "Tailored Formal Evening Dress", "pose": "Looking Back Over Shoulder",
        "surface_prop": "By Floor-to-Ceiling Window / Balcony", "scene": "Upscale Hotel Suite",
    }),
    ({"gym", "workout", "fitness", "athletic", "sporty", "running", "training", "yoga", "exercise", "athlete"}, {
        "style": "Creator 4K Webcam", "lighting": "Bright Morning Daylight", "framing": "Three-Quarter (Knees-Up)",
        "build": "Toned Fitness / Core", "hair_style": "High Sleek Ponytail", "skin": "Post-Workout Dewy Flush", "makeup_acc": "Bare-Faced / Minimal Natural",
        "attire": "Athletic Tank & Leggings", "pose": "Stretching Arms Overhead", "scene": "Boutique Fitness Gym",
    }),
    ({"vlog", "vlogger", "streamer", "stream", "gamer", "gaming", "creator", "influencer", "youtube", "tiktok", "selfie", "webcam", "podcast"}, {
        "style": "Casual Smartphone Vlog", "lighting": "Soft Front Ring-Light + Warm Fill", "framing": "Medium Close-Up (Chest-Up)",
        "age": "Early 20s Adult", "hair_style": "Curtain Bangs + Long Layers", "makeup_acc": "Over-Ear Studio Headphones",
        "attire": "Oversized Graphic Tee & Cargos", "pose": "Seated Upright Relaxed", "surface_prop": "Next to Desk Microphone & Monitors",
        "scene": "Creator / Gaming Studio Room",
    }),
    ({"fashion", "editorial", "vogue", "model", "runway", "luxury", "glamour", "glam", "chic", "couture", "magazine", "high-fashion", "executive", "powerful", "boss"}, {
        "style": "Editorial Magazine Portrait", "lighting": "Diffused Studio Softbox", "framing": "Three-Quarter (Knees-Up)",
        "symmetry": "Top Model Sculpted", "build": "Tall Slender Model", "hair_color": "Platinum Ice Blonde", "hair_style": "Chin-Length Sleek Bob",
        "makeup_acc": "Winged Eyeliner & Bold Lip", "attire": "Tailored Executive Blazer Suit", "pose": "Standing Tall Confident",
        "scene": "Minimalist Photo Studio",
    }),
    ({"retro", "vintage", "80s", "90s", "70s", "nostalgic", "nostalgia", "diner", "polaroid", "throwback", "americana"}, {
        "style": "90s Instant Polaroid", "lighting": "Direct On-Camera Flash", "framing": "Cowboy Shot (Thighs-Up)",
        "hair_color": "Dirty Blonde / Balayage", "hair_style": "Voluminous Bouncy Curls", "makeup_acc": "Winged Eyeliner & Bold Lip",
        "attire": "Buttoned Cardigan & High-Waist Jeans", "pose": "Seated Upright Relaxed", "surface_prop": "At Counter / Kitchen Island",
        "scene": "Retro American Diner",
    }),
    ({"anime", "manga", "kawaii", "cute", "jrpg", "visual-novel", "chibi"}, {
        "style": "Anime Visual Novel", "lighting": "Bright Morning Daylight", "framing": "Upper Body (Waist-Up)",
        "symmetry": "Heart-Shaped Youthful", "age": "18-21 Young Adult", "hair_color": "Pastel Pink / Rose Gold", "hair_style": "Twin Braids / Space Buns",
        "eyes": "Large Round Bright Eyes", "skin": "Smooth Stylized Finish", "attire": "Layered Tank & Open Flannel",
        "pose": "Dynamic Dance Movement",
    }),
    ({"nature", "forest", "park", "garden", "spring", "flowers", "floral", "meadow", "botanical", "peaceful", "serene", "calm", "dreamy", "ethereal"}, {
        "style": "Editorial Magazine Portrait", "lighting": "Dappled Filtered Sunlight", "framing": "Three-Quarter (Knees-Up)",
        "symmetry": "Soft Oval Delicate", "hair_color": "Strawberry Blonde / Ginger", "hair_style": "Long Flowing Layered",
        "skin": "Fair with Light Freckles", "makeup_acc": "Bare-Faced / Minimal Natural", "attire": "Floral Summer Sundress",
        "pose": "Mid-Stride Walking Forward", "scene": "Botanical Park Walkway",
    }),
]

_MALE_OVERRIDES = {
    "symmetry": "Strong Chiseled Structure", "build": "Muscular Broad-Shouldered", "hair_style": "Clean Short Textured Cut",
    "makeup_acc": "None / Custom", "attire": "Open-Collar Button-Down & Chinos", "hair_color": "Dark Espresso Brown",
}
_FEMALE_ONLY_ATTIRE = {
    "Floral Summer Sundress", "Tailored Formal Evening Dress", "Buttoned Cardigan & High-Waist Jeans",
    "Athletic Tank & Leggings", "Cozy Knit Pullover Sweater",
}
_PERSON_KEYS = {"symmetry", "age", "build", "hair_color", "hair_style", "eyes", "skin", "makeup_acc", "attire", "pose"}
_MALE_WORDS = {"man", "men", "guy", "male", "boy", "dude", "gentleman", "husband", "boyfriend", "he", "him", "his", "king", "prince"}
_EMPTY_WORDS = {"empty", "landscape", "no people", "nobody", "unoccupied", "deserted", "scenery"}
_GENERIC_LABEL_WORDS = {
    "none", "custom", "with", "and", "the", "soft", "warm", "dark", "light", "natural", "modern", "casual", "subtle", "slow",
    "smooth", "long", "short", "high", "low", "open", "front", "back", "rich", "deep", "bright", "cool", "clean", "fair",
    "solo", "together", "small", "full", "upper", "relaxed", "tone", "texture", "finish", "style", "shot",
    "island", "counter", "ground", "floor", "body", "face", "eyes", "glow", "adult", "prime", "only", "slight", "into",
}
_ALIASES = {"redhead": {"auburn"}, "brunet": {"brunette"}, "suit": {"blazer"}}
_LLM_ORDER = [k for k in (
    "scene", "gender", "style", "lighting", "age", "attire", "pose", "surface_prop",
    "framing", "symmetry", "build", "hair_color", "hair_style", "eyes", "skin", "makeup_acc",
) if k in FIELD_BY_KEY]

_vibe_overlay = addons.REGISTRY.catalog.get("vibe_overlay")
if _vibe_overlay:
    if "neutral" in _vibe_overlay:
        _NEUTRAL = _vibe_overlay["neutral"]
    if "vibes" in _vibe_overlay:
        _VIBES = _vibe_overlay["vibes"]
    if "female_only_attire" in _vibe_overlay:
        _FEMALE_ONLY_ATTIRE = _vibe_overlay["female_only_attire"]
    if "person_keys" in _vibe_overlay:
        _PERSON_KEYS = _vibe_overlay["person_keys"]
    if "aliases" in _vibe_overlay:
        _ALIASES = {**_ALIASES, **_vibe_overlay["aliases"]}
    if "generic_label_words" in _vibe_overlay:
        _GENERIC_LABEL_WORDS = set(_vibe_overlay["generic_label_words"])
    if "llm_order" in _vibe_overlay:
        _LLM_ORDER = [k for k in _vibe_overlay["llm_order"] if k in FIELD_BY_KEY]


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9][a-z0-9'-]*", (text or "").lower()))


def _words(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z0-9]+", (text or "").lower()):
        out.add(w)
        if len(w) > 4 and w.endswith("s"):
            out.add(w[:-1])
    return out


def _mentioned_fields(notes: str) -> dict[str, str]:
    """Options whose distinctive label words appear in the text (strict: ties are ignored)."""
    text = _words(notes)
    for alias, adds in _ALIASES.items():
        if alias in text:
            text |= adds
    found = {}
    for key, _, _, opts in ALL_FIELDS:
        scored = []
        for opt in opts[1:]:
            lw = {w for w in _words(_label(opt)) if len(w) >= 4 and w not in _GENERIC_LABEL_WORDS}
            hits = len(lw & text)
            if hits:
                scored.append((hits, opt))
        scored.sort(key=lambda x: -x[0])
        if scored and (len(scored) == 1 or scored[0][0] > scored[1][0]):
            found[key] = scored[0][1]
    return found


def _best_profile(notes: str) -> dict[str, str]:
    """The vibe profile with the most trigger hits ({} when none hit or two profiles tie)."""
    toks = _tokens(notes)
    scores = sorted(((len(toks & triggers), i) for i, (triggers, _) in enumerate(_VIBES)), reverse=True)
    if not scores or scores[0][0] == 0 or (len(scores) > 1 and scores[0][0] == scores[1][0]):
        return {}
    return _VIBES[scores[0][1]][1]


def _fallback_fields(notes: str) -> dict[str, str]:
    toks = _tokens(notes)
    low = (notes or "").lower()
    labels = {**_NEUTRAL, **_best_profile(notes)}

    mentioned = _mentioned_fields(notes)
    gender = mentioned.get("gender") or _opt("gender", labels["gender"])
    if "gender" not in mentioned:
        if toks & _MALE_WORDS and not toks & {"woman", "women", "girl", "she", "her", "female", "lady"}:
            gender = _opt("gender", "Fantasy Adventurer Man" if _label(gender).startswith("Fantasy") else "Solo Man")
        elif any(w in low for w in _EMPTY_WORDS):
            gender = _opt("gender", "Empty Environment (No People)")
    g_label = _label(gender)
    if "Man" in g_label.split() or g_label in ("Solo Man", "Two Men Together"):
        for k, lab in _MALE_OVERRIDES.items():
            if k == "attire" and labels.get("attire") not in _FEMALE_ONLY_ATTIRE:
                continue
            labels[k] = lab

    out = {}
    for key, _, _, opts in ALL_FIELDS:
        if key == "gender":
            out[key] = gender
        elif key in mentioned:
            out[key] = mentioned[key]
        elif g_label.startswith("Empty") and key in _PERSON_KEYS:
            out[key] = opts[0]
        elif key in labels:
            out[key] = _opt(key, labels[key])
        else:
            out[key] = opts[0]
    return out


# ── Primary: local instruct LLM picks one option per field ─────────────────

def _llm_messages(notes: str) -> tuple[str, str]:
    sys_msg = addons.REGISTRY.llm.get("vibe_system_prompt") or (
        "You are a creative director for an all-ages AI image studio. "
        "Given a short custom description, choose the ONE best option for EVERY category so the whole scene is coherent "
        "and captures the description's vibe, mood, era and setting. Anything the description states explicitly must be honored "
        "(subject, gender, hair, clothing or outfit, place, time of day). Fill in everything it does not mention with choices "
        "that fit its vibe, and vary your picks: do not default to the first option in a list. "
        "Rules: all person traits must fit ONE believable subject of the chosen gender and age "
        "(no makeup, dresses or feminine hairstyles on a man unless described). "
        "Pose, prop, scene, lighting and attire must all make sense together in the same place and time "
        "(e.g. no kitchen counter in a forest, no sundress in armor-themed fantasy). "
        "If the scene has no people, answer None for every person, attire and pose category.\n"
        "Reply format: first 'VIBE: <at most 15 words>', then fill in EVERY line of the ANSWER TEMPLATE as 'key=Option Name', "
        "copying an option name exactly from that category's list. No prose, no explanations."
    )
    lines = [f"DESCRIPTION: {notes.strip()}", "CATEGORIES:"]
    for key in _LLM_ORDER:
        _, label, _, opts = FIELD_BY_KEY[key]
        lines.append(f"{key} ({label}): " + " | ".join(_label(o) for o in opts))
    lines.append("ANSWER TEMPLATE (fill in all " + str(len(_LLM_ORDER)) + "): VIBE= | " + " | ".join(f"{k}=" for k in _LLM_ORDER))
    lines.append("ANSWER:")
    return sys_msg, "\n".join(lines)


def _match_option(key: str, answer: str) -> str | None:
    opts = FIELD_BY_KEY[key][3]
    ans = re.sub(r"^\d+\s*[=.)-]\s*", "", answer.strip().strip("'\"*` ")).strip()
    if not ans:
        return None
    if ans.isdigit():
        return opts[int(ans)] if int(ans) < len(opts) else None
    low = ans.lower()
    for opt in opts:
        if _label(opt).lower() == low:
            return opt
    if low.startswith("none"):
        return opts[0]
    aw = _words(ans) - {"and", "the", "with"}
    best, best_score = None, 0.0
    for opt in opts:
        lw = _words(_label(opt)) - {"and", "the", "with"}
        if not lw:
            continue
        score = len(aw & lw) / len(lw | aw)
        if score > best_score:
            best, best_score = opt, score
    return best if best_score >= 0.34 else None


def _parse_llm_picks(raw: str) -> dict[str, str]:
    raw = re.sub(r"<think>[\s\S]*?</think>", "", raw or "", flags=re.IGNORECASE)
    picks = {}
    for m in re.finditer(r"(?:^|[\n|])\s*[-*]?\s*([a-z_]+)\s*(?:\([^)]*\))?\s*[=:]\s*([^\n|]+)", raw):
        key, ans = m.group(1), m.group(2)
        if key in FIELD_BY_KEY and key not in picks:
            opt = _match_option(key, ans)
            if opt:
                picks[key] = opt
    return picks


_FEMININE_HAIR = {
    "Long Flowing Layered", "Curtain Bangs + Long Layers", "Soft Loose Shoulder Waves", "Voluminous Bouncy Curls", "Half-Up Half-Down",
    "Casual Messy Bun", "High Sleek Ponytail", "Low Wavy Ponytail", "Sleek Straight Tucked Behind Ear", "Chin-Length Sleek Bob",
    "Twin Braids / Space Buns", "Beach Tousled Waves",
}
_FEMININE_MAKEUP = {"Soft Everyday Dewy Glam", "Winged Eyeliner & Bold Lip", "Smoky Evening Glam"}


_MULTI_PERSON = {"Romantic Couple", "Two Women Together", "Two Men Together", "Two Friends Together", "Small Group"}
_MULTI_WORDS = {"two", "couple", "friend", "friends", "group", "together", "pair", "duo", "both", "they", "women", "men",
                "people", "crowd", "lovers", "girls", "guys", "sisters", "brothers", "team", "squad", "band", "trio"}


def _is_male(gender_value: str) -> bool:
    lab = _label(gender_value)
    return lab in ("Solo Man", "Two Men Together", "Fantasy Adventurer Man")


def _harmonize(picks: dict[str, str], fallback: dict[str, str], notes: str) -> dict[str, str]:
    """Fill gaps from the offline matcher and fix cross-field contradictions the LLM tends to make."""
    out = dict(picks)
    empty = _label(out.get("gender", "")).startswith("Empty")
    for key, _, _, opts in ALL_FIELDS:
        if key not in out or (is_default(key, out[key]) and key != "rating" and not (empty and key in _PERSON_KEYS)):
            out[key] = fallback[key]
    said_all = _words(notes)
    if _label(out["gender"]) in _MULTI_PERSON and not said_all & _MULTI_WORDS:
        out["gender"] = _opt("gender", "Solo Man" if _is_male(out["gender"]) else "Solo Woman")
    if _is_male(out["gender"]):
        if _label(out["symmetry"]) in ("Soft Oval Delicate", "Heart-Shaped Youthful"):
            out["symmetry"] = _opt("symmetry", "Strong Chiseled Structure")
        said = _words(notes)
        male_fb = _fallback_fields(notes + " man")
        if _label(out["hair_style"]) in _FEMININE_HAIR and not said & {"ponytail", "bun", "braid", "braids", "curls", "long"}:
            out["hair_style"] = male_fb["hair_style"]
        if _label(out["makeup_acc"]) in _FEMININE_MAKEUP and not said & {"makeup", "eyeliner", "lipstick"}:
            out["makeup_acc"] = FIELD_BY_KEY["makeup_acc"][3][0]
        if _label(out["attire"]) in _FEMALE_ONLY_ATTIRE and not said & {"dress", "skirt", "sundress"}:
            out["attire"] = male_fb["attire"]
    return out


def generate_fields_from_vibe(notes: str, use_llm: bool = True, model: str | None = None) -> tuple[dict[str, str], str]:
    """Return (field_key -> option value for every Builder field, status note). model: the LLM to use."""
    fallback = _fallback_fields(notes)
    if use_llm:
        from studio_rectifier import run_prompt_llm_checked

        sys_msg, user_msg = _llm_messages(notes)
        holder = {}

        def parse(raw):
            picks = _parse_llm_picks(raw)
            if len(picks) >= len(ALL_FIELDS) // 2:
                holder["picks"] = picks
                return "ok"
            return None

        _, note, _, refused = run_prompt_llm_checked(
            sys_msg, user_msg, model=model, max_tokens=520, ctx=6144, temperature=0.25,
            timeout=180, parse=parse, verb="generated details",
        )
        if refused and not addons.REGISTRY.llm.get("allow_refusal_bypass"):
            return {}, note or "The instruct LLM refused this request."
        picks = holder.get("picks")
        if picks:
            layered = dict(picks)
            for key, lab in _best_profile(notes).items():
                if key != "gender" and key in FIELD_BY_KEY:
                    layered[key] = _opt(key, lab)
            layered.update({k: v for k, v in _mentioned_fields(notes).items() if k != "gender" or "gender" not in picks})
            return _harmonize(layered, fallback, notes), note
    actor = addons.llm_ui_strings()["actor_name"]
    return fallback, f"✨ Generated details from custom-text vibe (offline matcher — {actor} not available)"


def fill_from_vision(values: dict[str, str], vision: str, replace: bool = False, use_llm: bool = True,
                     model: str | None = None) -> tuple[dict[str, str], list[str]]:
    """Fill dropdowns from the vision ("Fill dropdowns from my vision").

    Only dropdowns still on their default ("None ...") are filled unless replace=True; the creator's own
    picks stay. Returns (all builder values, notes).
    """
    generated, note = generate_fields_from_vibe(vision, use_llm=use_llm, model=model)
    out, filled = dict(values), 0
    for key, _, _, _ in ALL_FIELDS:
        if key in generated and (replace or is_default(key, values.get(key, ""))):
            if out.get(key) != generated[key]:
                filled += 1
            out[key] = generated[key]
    notes = [note] if note else []
    post_fill = addons.REGISTRY.llm.get("post_fill_vision")
    if post_fill:
        post_fill(values, vision, out, replace, notes)
    kept = sum(1 for k, _, _, _ in ALL_FIELDS if not is_default(k, values.get(k, "")))
    notes.append(f"Filled {filled} dropdown(s)" + ("" if replace or not kept else f"; kept your {kept} pick(s)") + ".")
    return out, notes


def validate_profiles():
    for _, profile in _VIBES:
        for k, lab in profile.items():
            if k in FIELD_BY_KEY:
                _opt(k, lab)
    for k, lab in {**_NEUTRAL, **_MALE_OVERRIDES}.items():
        if k in FIELD_BY_KEY:
            _opt(k, lab)


validate_profiles()
