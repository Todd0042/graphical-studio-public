"""Reconcile Prompt Builder dropdowns against the creator's vision (the custom text) with a local LLM.

The LLM's job is only reconciliation: the dropdowns are the creator's choices, the custom text is
the overall vision. Dropdown tags that fit the vision stay, tags that partly clash are adapted,
tags that contradict the vision (or a higher-priority dropdown) are removed.
"""

from __future__ import annotations

import sys

import addons
from wan_prompt_catalog import assemble_builder_prompt
from wan_rectifier import _sanitize_llm_output, rectify_builder_fields, run_prompt_llm, run_prompt_llm_checked

_CORE_SYSTEM_PROMPT = (
    "You are a helpful diffusion prompt reconciler for an all-ages creative studio. "
    "You receive the creator's VISION (custom text: the overall intent of the image) and DROPDOWN TAGS "
    "(the creator's menu choices: style, color treatment, rating, lighting, framing, position, person, attire, scene, background).\n"
    "YOUR JOB:\n"
    "1. Keep the VISION's intent and every detail of it in the final prompt (you may reword it to fit).\n"
    "2. Check each dropdown tag against the VISION: keep tags that fit, adapt tags that partly clash, "
    "remove tags that contradict it (wrong subject, clothing state, setting, time of day, rating...).\n"
    "3. Resolve contradictions between dropdown tags by ownership: ATTIRE owns clothing, FRAMING owns "
    "shot scale, POSITION owns where the subject sits, LIGHTING owns time/light, STYLE owns rendering medium, "
    "COLOR TREATMENT owns saturation and palette (keep spot-color tags exactly), BACKGROUND type/color owns the "
    "backdrop (drop room/location details that contradict a plain or abstract background), SUBJECT owns who is in the image.\n"
    "4. Output ONLY the final comma-separated prompt on one line. No labels, quotes or commentary."
)

SYSTEM_PROMPT = addons.REGISTRY.reconcile_system_prompt or _CORE_SYSTEM_PROMPT


def reconcile_builder(values: dict[str, str], vision: str, include_motion: bool, use_llm: bool = True,
                      model: str | None = None) -> dict:
    """Return {"prompt", "notes", <used_key>, <model_key>} for a Prompt Builder reconcile."""
    ui = addons.llm_ui_strings()
    used_k, model_k = ui["result_used_key"], ui["result_model_key"]
    vision = (vision or "").strip()
    dropdown_prompt, _ = rectify_builder_fields(values, include_motion=include_motion)
    python_prompt = assemble_builder_prompt(values, include_motion=include_motion, extra_notes=vision)
    if not use_llm or not dropdown_prompt:
        return {"prompt": python_prompt or vision, "notes": [], used_k: False, model_k: ""}

    user_msg = f"VISION: {vision or '(none: just reconcile the dropdown tags with each other)'}\nDROPDOWN TAGS: {dropdown_prompt}\nOUTPUT:"
    notes: list[str] = []
    output, note, used, refused = run_prompt_llm_checked(
        SYSTEM_PROMPT, user_msg, model=model, max_tokens=320, ctx=4096, temperature=0.2,
        timeout=180, parse=_sanitize_llm_output, verb="reconciled",
    )
    if refused and not addons.REGISTRY.allow_refusal_fallback:
        return {"prompt": "", "notes": [note or "The instruct LLM refused this request."],
                used_k: False, model_k: used, "refused": True}
    actor = ui["actor_name"]
    if not output:
        why = f" ({note})" if note else ""
        return {"prompt": python_prompt, "notes": [f"{actor} unavailable{why}: used the Python-reconciled prompt."],
                used_k: False, model_k: ""}
    notes.append(note or f"{actor} reconciled the dropdowns with your vision.")

    if addons.REGISTRY.reconcile_post_check:
        output = addons.REGISTRY.reconcile_post_check(
            output, vision, dropdown_prompt, values, run_prompt_llm, user_msg, used, model, notes, _sanitize_llm_output
        )
    return {"prompt": output, "notes": notes, used_k: True, model_k: used}


def reconcile_for_target(values: dict[str, str], vision: str, target: str, model: str | None) -> dict:
    """Reconcile and pick the model + settings for what the prompt describes."""
    from wan_compat import recommended_photo_settings, recommended_video_settings

    if target == "video" and not addons.REGISTRY.video_enabled:
        raise ValueError("Video generation is not enabled in the public edition.")
    ui = addons.llm_ui_strings()
    used_k, model_k = ui["result_used_key"], ui["result_model_key"]
    rec = reconcile_builder(values, vision, include_motion=(target == "video"), use_llm=bool(model), model=model)
    text = f"{vision}, {rec['prompt']}"
    settings = (recommended_photo_settings if target == "photo" else recommended_video_settings)(values, text)
    settings.pop("intent", None)
    out = {**settings, "prompt": rec["prompt"], "notes": rec["notes"], used_k: rec[used_k],
           model_k: rec[model_k], "target": target}
    if rec.get("refused"):
        out["refused"] = True
    return out


if addons.REGISTRY.attach_reconcile_compat:
    addons.REGISTRY.attach_reconcile_compat(sys.modules[__name__])
