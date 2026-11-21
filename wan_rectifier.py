"""Domain-weighted prompt conflict rectifier (deterministic Python + optional local instruct LLM).

Prioritizes each dropdown's authoritative domain based on its chosen option's lead keywords
(e.g. Attire governs outfit state, Framing governs shot scale, Lighting governs
time-of-day/light mood, Style governs rendering medium, Gender governs subject count/sex).
"""

import json
import os
import re
import sys
import urllib.request

import addons

# Authoritative priority order when two domains disagree without a direct owner
DOMAIN_WEIGHTS = {
    "extra_notes": 200,  # User's Custom Text is ALWAYS absolute truth over every dropdown
    "gender": 100,
    "attire": 95,
    "style": 92,
    "framing": 90,
    "composition": 89,
    "color_treatment": 88,
    "spot_color": 87,
    "bg_type": 79,
    "bg_color": 79,
    "lighting": 85,
    "pose": 82,
    "surface_prop": 80,
    "scene": 78,
    "hair_color": 76,
    "hair_style": 76,
    "eyes": 75,
    "skin": 74,
    "makeup_acc": 73,
    "build": 72,
    "age": 70,
    "expression": 68,
    "motion": 66,
    "camera_move": 64,
    "physics": 62,
    "symmetry": 60,
    "rating": 55,
}

# Semantic conflict groups: each group maps sub-intent -> regex patterns that express that sub-intent.
# When a domain owner picks sub-intent X, patterns matching OTHER sub-intents in the same group
# are pruned from lower-priority/non-owner clauses.
_BASE_CONFLICT_GROUPS = {
    "clothing_state": {
        "owners": ("attire", "rating"),
        "modes": {
            "clothed": [
                r"\bcrop(?:ped)?\s+(?:ribbed\s+)?(?:baby-tee|top|tank|hoodie|cardigan|tee|sweater)\b",
                r"\bbaby-tee\b", r"\bhoodie\b", r"\bflannel\b", r"\bsweater\b",
                r"\bcardigan\b", r"\bt-?shirt\b", r"\bcrew-neck tee\b", r"\bgraphic tee\b",
                r"\bblazer\b", r"\bsuit\b", r"\bbutton-down\b", r"\boxford\b",
                r"\b(?:slip |sun)?dress\b", r"\bgown\b", r"\bmini skirt\b", r"\bskirt\b",
                r"\b(?:baggy |dark |blue |denim |high-waisted )?jeans\b",
                r"\bjoggers\b", r"\bleggings\b", r"\brunning shorts\b", r"\bshorts\b",
                r"\bchinos\b", r"\bpants\b", r"\btrousers\b",
                r"\bmoto jacket\b", r"\bbiker jacket\b", r"\btrench coat\b", r"\bcoat\b",
                r"\bcloak\b", r"\btechwear\b", r"\bleather armor\b", r"\barmor\b",
                r"\bkimono\b", r"\buniform\b",
                r"\bspacesuit\b", r"\bbodysuit\b", r"\btunic\b", r"\bblouse\b", r"\bshirt\b",
                r"\bcamisole\b", r"\bcami\b", r"\bsports bra\b", r"\bthigh socks\b",
                r"\btasteful modest presentation\b", r"\bmodest\b",
                r"\brating_safe\b", r"\bfamily-friendly\b",
            ],
        },
    },
    "render_medium": {
        "owners": ("style", "skin"),
        "modes": {
            "photoreal": [
                r"\braw candid photo\b", r"\bphotorealistic\b", r"\blive-action\b",
                r"\bsony a7r\b", r"\b35mm\b", r"\b85mm\b", r"\biphone\b", r"\bwebcam\b",
                r"\bkodak portra\b", r"\bpolaroid\b", r"\bfilm grain\b", r"\bauthentic skin texture\b",
                r"\bnatural pores\b",
            ],
            "anime_2d": [
                r"\banime\b", r"\bcel[- ]shad(?:ed|ing)\b", r"\bjrpg\b",
                r"\bcrisp ink linework\b", r"\bcomic book\b", r"\bhalftone\b",
                r"\bvisual novel\b",
            ],
            "pixel_art": [
                r"\bpixel art\b", r"\b16-bit\b", r"\bpixel cluster\b",
            ],
            "painterly": [
                r"\boil painting\b", r"\bbrushstrokes?\b", r"\bcanvas finish\b",
                r"\bpainterly\b", r"\bhand-painted\b",
            ],
            "cg_3d": [
                r"\bunreal engine\b", r"\b3d (?:character )?render\b", r"\bpbr\b",
            ],
        },
    },
    "camera_scale": {
        "owners": ("framing", "pose"),
        "modes": {
            "closeup": [
                r"\bextreme close-up\b", r"\bclose-up\b", r"\bface,\s*eyes,\s*and collarbones\b",
                r"\bheadshot\b",
            ],
            "medium": [
                r"\bupper body\b", r"\bwaist-up\b", r"\bchest-up\b", r"\bmedium close-up\b",
            ],
            "cowboy_threequarter": [
                r"\bcowboy shot\b", r"\bthighs-up\b", r"\bthree-quarter\b", r"\bknees-up\b",
            ],
            "full_wide": [
                r"\bfull body\b", r"\bhead-to-toe\b", r"\bfull standing figure\b",
                r"\bfull-length\b", r"\bwide-angle scenic\b",
            ],
        },
    },
    "time_lighting": {
        "owners": ("lighting", "scene"),
        "modes": {
            "daylight": [
                r"\bbright morning daylight\b", r"\bnatural daylight\b", r"\bsunlit\b",
                r"\bmorning window light\b", r"\bsunbeams?\b", r"\bdappled sunlight\b",
            ],
            "sunset_golden": [
                r"\bgolden hour\b", r"\blate-afternoon\b", r"\bsunset\b", r"\bdusk\b",
                r"\btwilight\b", r"\bblue hour\b",
            ],
            "night_dark": [
                r"\bneon rainy night\b", r"\bmoonlit\b", r"\bnight mist\b", r"\blate-night\b",
                r"\bmidnight\b", r"\bnight\b", r"\bdim romantic\b", r"\bcandlelight\b",
            ],
        },
    },
    "subject_sex": {
        "owners": ("gender",),
        "modes": {
            "empty": [r"\bno humans\b", r"\bempty atmospheric scenery\b", r"\bempty scenery\b", r"\bwithout people\b", r"\bno people\b"],
            "female": [
                r"\b1woman\b", r"\b2women\b", r"\bfemale\b", r"\bwoman\b", r"\bgirl\b", r"\blady\b",
                r"\bgirl-next-door\b", r"\bfeminine curves\b", r"\bhourglass\b", r"\bheroine\b",
            ],
            "male": [
                r"\b1man\b", r"\b2men\b", r"\bmale\b", r"\bman\b", r"\bguy\b", r"\bboy\b",
                r"\bbearded\b", r"\bhandsome\b", r"\bbroad-chested\b", r"\bwarrior protagonist\b",
            ],
            "mixed": [r"\b1man and 1woman\b", r"\bcouple\b", r"\btwo young adults\b", r"\bgroup of friends\b"],
        },
    },
    "posture_state": {
        "owners": ("pose", "motion"),
        "modes": {
            "standing": [r"\bstanding\b", r"\bleaning against wall\b", r"\bupright\b"],
            "sitting": [r"\bsitting\b", r"\bseated\b", r"\bcross-legged\b"],
            "lying": [r"\blying\b", r"\breclining\b"],
            "walking": [r"\bwalking\b", r"\bmid-stride\b", r"\bstepping\b"],
            "crouching": [r"\bcrouching\b", r"\bkneeling\b", r"\bcrouched\b"],
        },
    },
}

CONFLICT_GROUPS = (
    addons.REGISTRY.extend_conflict_groups(_BASE_CONFLICT_GROUPS)
    if addons.REGISTRY.extend_conflict_groups
    else _BASE_CONFLICT_GROUPS
)


def _lead_focus(raw_value: str) -> str:
    """Extract the high-priority leading words of a dropdown selection (label + first 6 words)."""
    clean = (raw_value or "").strip()
    if not clean or clean.lower().startswith("none"):
        return ""
    if ":" in clean:
        head, tail = clean.split(":", 1)
        tail_words = " ".join(tail.strip().split()[:8])
        return f"{head.strip()} {tail_words}".lower()
    return " ".join(clean.split()[:10]).lower()


def _classify_mode(text: str, modes: dict[str, list[str]], lead_text: str = "") -> str | None:
    """Classify which sub-intent a text expresses, weighting the leading words 3x higher."""
    low = (text or "").lower()
    lead = (lead_text or "").lower()
    best_mode, best_score = None, 0.0
    for mode, pats in modes.items():
        score = 0.0
        for pat in pats:
            if lead and re.search(pat, lead):
                score += 3.0
            if re.search(pat, low):
                score += 1.0
        if score > best_score:
            best_score = score
            best_mode = mode
    return best_mode


def _prune_patterns(clause: str, patterns: list[str]) -> tuple[str, list[str]]:
    """Remove sub-phrases matching any conflicting regex while keeping remaining comma tags intact."""
    parts = [p.strip() for p in clause.split(",") if p.strip()]
    kept = []
    removed = []
    for part in parts:
        low = part.lower()
        if any(re.search(pat, low) for pat in patterns):
            removed.append(part)
        else:
            kept.append(part)
    return ", ".join(kept), removed


def rectify_builder_fields(
    field_values: dict[str, str],
    extra_clauses: list[tuple[str, str]] | None = None,
    include_motion: bool = True,
) -> tuple[str, list[str]]:
    """Rectify conflicts across structured Builder dropdowns + optional extra clauses."""
    from wan_prompt_catalog import ALL_FIELDS, SCENE_ATTIRE_FIELDS, PERSON_FIELDS, THEME_FIELDS, extract_clause

    ordered_fields = ALL_FIELDS if include_motion else (THEME_FIELDS + PERSON_FIELDS + SCENE_ATTIRE_FIELDS)
    entries: list[dict] = []
    for key, label, _, _ in ordered_fields:
        raw = field_values.get(key, "")
        clause = extract_clause(raw)
        if clause:
            entries.append({
                "key": key,
                "label": label,
                "raw": raw,
                "lead": _lead_focus(raw),
                "clause": clause,
                "weight": DOMAIN_WEIGHTS.get(key, 50),
            })

    for src_key, text in (extra_clauses or []):
        t = (text or "").strip()
        if t:
            entries.append({
                "key": src_key,
                "label": src_key.replace("_", " ").title(),
                "raw": t,
                "lead": _lead_focus(t),
                "clause": t,
                "weight": DOMAIN_WEIGHTS.get(src_key, 45),
            })

    if not entries:
        return "", []

    notes: list[str] = []
    by_key = {e["key"]: e for e in entries}

    # Special rule 1: Empty Environment ("no humans") removes all person/attire/pose/expression/motion boxes
    # UNLESS Custom Text (extra_notes) explicitly introduces a person/character!
    custom_ent = by_key.get("extra_notes")
    custom_sex = _classify_mode(custom_ent["clause"], CONFLICT_GROUPS["subject_sex"]["modes"], custom_ent["lead"]) if custom_ent else None
    g_entry = by_key.get("gender")
    if g_entry and _classify_mode(g_entry["clause"], CONFLICT_GROUPS["subject_sex"]["modes"], g_entry["lead"]) == "empty" and custom_sex not in ("female", "male", "mixed"):
        person_keys = {"symmetry", "age", "build", "hair_color", "hair_style", "eyes", "skin", "makeup_acc", "attire", "pose", "motion", "expression", "variation", "profile"}
        dropped = [e["label"] for e in entries if e["key"] in person_keys]
        if dropped:
            entries = [e for e in entries if e["key"] not in person_keys]
            notes.append(f"Subject (Empty Environment) dropped person fields: {', '.join(dropped)}")

    # Apply every semantic conflict group: Custom Text (extra_notes) ALWAYS checks first as absolute truth,
    # followed by the group's authoritative dropdown owners.
    for group_name, spec in CONFLICT_GROUPS.items():
        owners = ("extra_notes",) + tuple(spec["owners"])
        modes = spec["modes"]

        winner = None
        winner_mode = None
        for own_key in owners:
            cand = next((e for e in entries if e["key"] == own_key), None)
            if cand is None:
                continue
            m = _classify_mode(cand["clause"], modes, cand["lead"])
            if m is not None:
                winner = cand
                winner_mode = m
                break

        if winner is None or winner_mode is None:
            continue

        mode_drop = spec.get("mode_drop", {})
        if winner_mode in mode_drop:
            bad_pats = mode_drop[winner_mode]
        elif group_name == "subject_sex" and winner_mode == "mixed":
            bad_pats = modes["empty"]
        else:
            bad_pats = []
            for m_name, pats in modes.items():
                if m_name != winner_mode:
                    bad_pats.extend(pats)

        if not bad_pats:
            continue

        for ent in entries:
            if ent is winner:
                continue
            if ent["key"] == "extra_notes":
                continue
            if winner["key"] != "extra_notes" and ent["key"] not in owners and ent["weight"] > winner["weight"] and winner["key"] != spec["owners"][0]:
                continue
            new_clause, removed = _prune_patterns(ent["clause"], bad_pats)
            if removed:
                ent["clause"] = new_clause
                win_head = "Custom Text" if winner["key"] == "extra_notes" else (winner["raw"].split(":", 1)[0].strip() if ":" in winner["raw"] else winner["label"])
                notes.append(f"{winner['label']} ({win_head}) overrode {ent['label']}: removed '{'; '.join(removed[:2])}'")

    # Final deduplication across comma-separated tags (preserve order, keep first occurrence)
    seen: set[str] = set()
    final_tags: list[str] = []
    for ent in entries:
        if not ent["clause"].strip():
            continue
        for tag in (p.strip() for p in ent["clause"].split(",")):
            if not tag:
                continue
            norm = re.sub(r"\s+", " ", tag.lower())
            if norm not in seen:
                seen.add(norm)
                final_tags.append(tag)

    return ", ".join(final_tags), notes


def _custom_text_survived(output: str, custom_text: str) -> bool:
    """Return True if output preserves at least 1/3 of custom_text's distinctive words (5+ chars)."""
    _skip = {'their', 'while', 'would', 'could', 'should', 'other', 'about',
             'which', 'these', 'those', 'being', 'having', 'where', 'there',
             'light', 'leather', 'scene', 'style', 'camera', 'modern'}
    words = [w for w in re.findall(r'\b[a-z]{5,}\b', custom_text.lower()) if w not in _skip]
    if not words:
        return True
    out_low = output.lower()
    matched = sum(1 for w in words if w in out_low)
    return matched >= max(1, len(words) // 3)


def rectify_freeform_prompt(
    prompt_text: str,
    priority_hints: dict[str, str] | None = None,
    use_extra_llm: bool = False,
    custom_text: str = "",
    **kwargs,
) -> tuple[str, list[str]]:
    """Rectify conflicts in an already-assembled prompt (plus optional priority dropdown hints)."""
    notes: list[str] = []
    text = (prompt_text or "").strip()
    custom = (custom_text or "").strip()
    if not text:
        return "", notes

    hints = dict(priority_hints or {})
    if not hints:
        from wan_prompt_catalog import ascertain_fields_from_prompt
        hints = ascertain_fields_from_prompt(text)
    if custom:
        hints["extra_notes"] = custom

    cleaned = text
    for group_name, spec in CONFLICT_GROUPS.items():
        owners = ("extra_notes",) + tuple(spec["owners"])
        modes = spec["modes"]
        winner_key, winner_raw, winner_mode = None, "", None
        for own_key in owners:
            raw = hints.get(own_key, "")
            if not raw or raw.lower().startswith("none"):
                continue
            m = _classify_mode(raw, modes, _lead_focus(raw))
            if m is not None:
                winner_key, winner_raw, winner_mode = own_key, raw, m
                break
        if not winner_mode:
            continue

        mode_drop = spec.get("mode_drop", {})
        if winner_mode in mode_drop:
            bad_pats = mode_drop[winner_mode]
        elif group_name == "subject_sex" and winner_mode == "mixed":
            bad_pats = modes["empty"]
        else:
            bad_pats = [p for m_name, pats in modes.items() if m_name != winner_mode for p in pats]

        from wan_prompt_catalog import extract_clause
        protected = custom.lower() if winner_key == "extra_notes" else extract_clause(winner_raw).lower()
        custom_low = custom.lower()
        parts = [p.strip() for p in cleaned.split(",") if p.strip()]
        kept, removed = [], []
        for part in parts:
            low = part.lower()
            if (custom_low and (low in custom_low or custom_low in low)) or (low and low in protected):
                kept.append(part)
            elif any(re.search(pat, low) for pat in bad_pats):
                removed.append(part)
            else:
                kept.append(part)
        if removed:
            cleaned = ", ".join(kept)
            win_head = "Custom Text" if winner_key == "extra_notes" else winner_raw.split(":", 1)[0].strip()
            notes.append(f"{winner_key.title()} ({win_head}) pruned conflicting tags: '{'; '.join(removed[:2])}'")

    seen: set[str] = set()
    deduped = []
    for part in (p.strip() for p in cleaned.split(",")):
        norm = re.sub(r"\s+", " ", part.lower())
        if part and norm not in seen:
            seen.add(norm)
            deduped.append(part)
    cleaned = ", ".join(deduped)

    if use_extra_llm or any(kwargs.values()):
        polished, llm_note = _try_llm_polish(cleaned, hints, custom_text=custom)
        if polished:
            if not custom or _custom_text_survived(polished, custom):
                cleaned = polished
                if llm_note:
                    notes.append(llm_note)
            else:
                actor = addons.llm_ui_strings()["actor_name"]
                notes.append(f"{actor} ran but dropped custom text — Python-cleaned result kept")

    return cleaned, notes


def _split_secondary_tags(prompt_text: str, custom_text: str) -> str:
    """Return prompt_text with custom_text's own clauses removed so the LLM sees clean secondary tags."""
    if not custom_text:
        return prompt_text
    c_low = custom_text.strip().lower()
    c_parts = {re.sub(r"\s+", " ", p.strip().lower()) for p in custom_text.split(",") if p.strip()}
    kept = []
    for part in (p.strip() for p in prompt_text.split(",") if p.strip()):
        norm = re.sub(r"\s+", " ", part.lower())
        if norm in c_parts or norm == c_low or (len(norm) > 3 and norm in c_low):
            continue
        kept.append(part)
    return ", ".join(kept)


def _build_llm_messages(prompt_text: str, priority_hints: dict[str, str], custom_text: str = "") -> tuple[str, str]:
    if addons.REGISTRY.rectifier_llm_messages:
        return addons.REGISTRY.rectifier_llm_messages(prompt_text, priority_hints, custom_text)
    custom = (custom_text or priority_hints.get("extra_notes") or "").strip()
    if custom:
        secondary = _split_secondary_tags(prompt_text, custom)
        sys_msg = (
            "You are a diffusion prompt editor for an all-ages creative studio. "
            "You are given ABSOLUTE TRUTH (user custom text) and SECONDARY TAGS (from dropdown menus).\n"
            "YOUR JOB:\n"
            "1. Keep EVERY detail in ABSOLUTE TRUTH intact.\n"
            "2. Inspect each tag in SECONDARY TAGS against ABSOLUTE TRUTH:\n"
            "   - DELETE any secondary tag that contradicts ABSOLUTE TRUTH (wrong gender/person, age, hair, eye color, clothing, pose, setting/location, lighting/time).\n"
            "   - MODIFY/ADAPT any secondary tag that partially clashes so it fits ABSOLUTE TRUTH seamlessly.\n"
            "   - KEEP secondary tags that do NOT conflict and complement the scene.\n"
            "3. Output ONLY the final clean comma-separated prompt on a single line. No explanations, labels, or quotes.\n\n"
            "Example:\n"
            "ABSOLUTE TRUTH: an old bearded wizard in dark purple robes inside a candlelit library\n"
            "SECONDARY TAGS: photorealistic, 85mm lens, 1woman, blonde hair, bright blue eyes, pink sundress, sunny beach, daylight\n"
            "OUTPUT: photorealistic, 85mm lens, an old bearded wizard in dark purple robes inside a candlelit library, warm dim candlelight"
        )
        user_msg = (
            f"ABSOLUTE TRUTH: {custom}\n"
            f"SECONDARY TAGS: {secondary or '(none)'}\n"
            f"OUTPUT:"
        )
        return sys_msg, user_msg

    priorities = "\n".join(
        f"- {k.upper()} (priority {DOMAIN_WEIGHTS.get(k, 50)}): {v.split(':', 1)[0].strip()} -> lead intent: {_lead_focus(v)}"
        for k, v in priority_hints.items()
        if k != "extra_notes" and v and not v.lower().startswith("none")
    )
    sys_msg = (
        "You are a diffusion prompt conflict rectifier. "
        "Eliminate contradictions between tags while keeping compatible tags. "
        "Resolve conflicts by domain ownership: ATTIRE owns clothing, FRAMING owns shot scale, "
        "LIGHTING owns time/light, STYLE owns medium, GENDER owns subject. "
        "Output ONLY the final clean comma-separated prompt on one line, with no labels, quotes, or commentary."
    )
    user_msg = (
        f"Domain priorities:\n{priorities or '(none)'}\n\n"
        f"Prompt to rectify:\n{prompt_text}"
    )
    return sys_msg, user_msg


_REFUSAL_PHRASES = (
    "i cannot", "i can't", "i apologize", "sorry,", "inappropriate",
    "as an ai", "cannot fulfill", "i'm unable", "i am unable",
)


def _is_llm_refusal(out: str) -> bool:
    low = (out or "").strip().lower()
    return any(bad in low for bad in _REFUSAL_PHRASES)


def _strip_llm_wrapper(out: str) -> str:
    out = re.sub(r"<think>[\s\S]*?</think>", "", out or "", flags=re.IGNORECASE).strip()
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    out = lines[0] if lines else ""
    out = re.sub(r"^(?:rectified|final|cleaned|revised)?\s*prompt\s*:\s*", "", out, flags=re.IGNORECASE).strip()
    out = re.sub(r"^output\s*:\s*", "", out, flags=re.IGNORECASE).strip()
    return out.strip('"\'` ')


def _sanitize_llm_output(out: str) -> str | None:
    if not out:
        return None
    out = _strip_llm_wrapper(out)
    if len(out) < 10 or _is_llm_refusal(out):
        return None
    return out


def _try_ollama_instruct(sys_msg: str, user_msg: str, *, max_tokens: int = 260, ctx: int = 2048,
                         temperature: float = 0.1, timeout: float | None = None, parse=None,
                         verb: str = "rectified", model: str) -> tuple[str | None, str, bool]:
    """Run an allow-listed Ollama instruct model. Returns (cleaned_output, note, refused)."""
    ollama_url = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    if not ollama_url.startswith("http"):
        ollama_url = "http://" + ollama_url
    body = json.dumps({
        "model": model,
        "stream": False,
        "keep_alive": "15s",
        "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": ctx},
        "messages": [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg},
        ],
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            f"{ollama_url}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout or 20.0) as resp:
            raw = json.loads(resp.read()).get("message", {}).get("content", "")
    except Exception:
        return None, "", False
    stripped = _strip_llm_wrapper(raw)
    if _is_llm_refusal(stripped):
        return None, f"{model} refused the request.", True
    cleaned = (parse or _sanitize_llm_output)(raw)
    if cleaned:
        return cleaned, f"✨ {model} {verb} via Ollama", False
    return None, "", False


def run_prompt_llm_checked(sys_msg: str, user_msg: str, model: str | None = None, **kwargs) -> tuple[str | None, str, str, bool]:
    """Run the active prompt LLM. Returns (output, note, model_used, refused)."""
    if addons.REGISTRY.run_llm_override:
        out, note, used = addons.REGISTRY.run_llm_override(sys_msg, user_msg, model=model, **kwargs)
        return out, note, used, False

    from wan_models import resolve_prompt_llm

    use, why = resolve_prompt_llm(model)
    if not use:
        return None, why, "", False
    out, note, refused = _try_ollama_instruct(sys_msg, user_msg, model=use, **kwargs)
    if refused:
        return None, note, use, True
    if out:
        return out, " ".join(n for n in (note, why) if n), use, False
    return None, f"{use} didn't return a usable answer." + (f" {why}" if why else ""), use, False


def run_prompt_llm(sys_msg: str, user_msg: str, model: str | None = None, **kwargs) -> tuple[str | None, str, str]:
    out, note, used, _ = run_prompt_llm_checked(sys_msg, user_msg, model=model, **kwargs)
    return out, note, used


def _try_llm_polish(prompt_text: str, priority_hints: dict[str, str], custom_text: str = "") -> tuple[str | None, str]:
    sys_msg, user_msg = _build_llm_messages(prompt_text, priority_hints, custom_text=custom_text)
    out, note, _ = run_prompt_llm(sys_msg, user_msg)
    return out, note


if addons.REGISTRY.attach_rectifier_compat:
    addons.REGISTRY.attach_rectifier_compat(sys.modules[__name__])
