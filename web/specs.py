"""Validate web requests into job plans, reusing the desktop app's own builders.

Two stages: prepare_* (at submit) validate everything into a JSON-safe plan; the job then runs
inside its GPU turn (finalize):
  photo / video  render the prompt as typed, after the same Python cleanup as the desktop
                 Generate button (no LLM)
  reconcile      Prompt Builder send: the local LLM reconciles the chosen dropdowns against the
                 custom-text vision (wan_reconcile.py) and picks model + settings
Everything a browser sends is checked against allow-lists and numeric bounds before it
reaches argv; commands are argv lists (never a shell string).
"""

from __future__ import annotations

import os
import random
import sys
from typing import Any

import addons
from wan_prompt_catalog import FIELD_BY_KEY
from wan_models import default_prompt_llm, prompt_llms, resolve_prompt_llm
from wan_reconcile import reconcile_for_target
from wan_vibe import fill_from_vision

from wan_profiles import generate_random_person_variation
from wan_rectifier import rectify_builder_fields, rectify_freeform_prompt
from wan_studio_helpers import (
    CAUTION_MODELS, CORE_PHOTO_MODEL_SETTINGS, DEFAULT_NEGATIVE, I2V_VERSIONS, MODEL_OPTIONS,
    PHOTO_DEFAULT_NEGATIVE, PHOTO_PRESETS, PRESETS, VIDEO_MODEL_SETTINGS,
    build_cli_command, build_photo_cli_command, duration_to_frames, get_photo_model_options,
    list_photo_loras, slugify_photo_prompt, slugify_prompt,
)

PHOTO_SAMPLERS = ("dpmpp_2m", "euler", "uni_pc")
PHOTO_SCHEDULERS = ("karras", "simple", "normal")
VIDEO_SAMPLERS = ("uni_pc", "euler", "dpmpp_2m")
VIDEO_SCHEDULERS = ("simple", "normal", "karras")
REF_MODES = ("none", "person", "background")
MAX_PROMPT = 4000
MAX_NEGATIVE = 2000


class SpecError(ValueError):
    """User-facing validation error."""


def _num(data: dict, key: str, default: float, lo: float, hi: float, as_int: bool = False) -> Any:
    raw = data.get(key, default)
    try:
        val = float(raw)
    except (TypeError, ValueError):
        raise SpecError(f"{key} must be a number")
    if not (lo <= val <= hi):
        raise SpecError(f"{key} must be between {lo:g} and {hi:g}")
    return int(round(val)) if as_int else val


def _text(data: dict, key: str, limit: int, default: str = "") -> str:
    val = data.get(key, default)
    if not isinstance(val, str):
        raise SpecError(f"{key} must be text")
    val = val.replace("\x00", "").strip()
    if len(val) > limit:
        raise SpecError(f"{key} is too long (max {limit} characters)")
    return val


def _choice(data: dict, key: str, options: tuple[str, ...] | list[str], default: str) -> str:
    val = str(data.get(key, default) or default)
    if val not in options:
        raise SpecError(f"Unsupported {key}: {val}")
    return val


def _dims(data: dict, lo: int, hi: int, multiple: int, default: tuple[int, int]) -> tuple[int, int]:
    w = _num(data, "width", default[0], lo, hi, as_int=True)
    h = _num(data, "height", default[1], lo, hi, as_int=True)
    if w % multiple or h % multiple:
        raise SpecError(f"width and height must be multiples of {multiple}")
    return w, h


def _seed(data: dict) -> int:
    if data.get("random_seed", True):
        return random.randint(1000, 999_999)
    return _num(data, "seed", 42026, 0, 2**31 - 1, as_int=True)


def photo_options() -> dict[str, Any]:
    if addons.REGISTRY.photo_model_registry:
        return {
            "models": [{"key": k, "label": label} for k, label in get_photo_model_options()],
            "presets": [{"label": label, "width": w, "height": h} for label, (w, h) in PHOTO_PRESETS.items()],
            "samplers": PHOTO_SAMPLERS, "schedulers": PHOTO_SCHEDULERS, "loras": list_photo_loras(),
            "ref_modes": REF_MODES, "default_negative": PHOTO_DEFAULT_NEGATIVE,
        }
    return {
        "models": [{"key": k, "label": label, "settings": CORE_PHOTO_MODEL_SETTINGS[k]}
                   for k, label in get_photo_model_options()],
        "presets": [{"label": label, "width": w, "height": h} for label, (w, h) in PHOTO_PRESETS.items()],
        "samplers": ("euler", "dpmpp_2m", "uni_pc"),
        "schedulers": ("simple", "karras", "normal"),
        "loras": [],
        "ref_modes": ("none",),
        "default_negative": PHOTO_DEFAULT_NEGATIVE,
        "supports_ref": False,
        "supports_lora": False,
    }


def video_options() -> dict[str, Any]:
    if not addons.REGISTRY.video_enabled:
        raise SpecError("Video generation is not available in the public edition")
    return {
        "models": [{"key": k, "label": label, "caution": k in CAUTION_MODELS, "settings": VIDEO_MODEL_SETTINGS[k]}
                   for k, label in MODEL_OPTIONS],
        "presets": [{"label": label, "width": w, "height": h, "duration": d, "fps": f} for label, (w, h, d, f) in PRESETS.items()],
        "samplers": VIDEO_SAMPLERS, "schedulers": VIDEO_SCHEDULERS, "default_negative": DEFAULT_NEGATIVE,
    }


def prepare_photo(data: dict, resolve_upload) -> dict[str, Any]:
    models = [k for k, _ in get_photo_model_options()]
    has_ckpt = bool(addons.REGISTRY.photo_model_registry)
    default_m = addons.REGISTRY.default_photo_model or "flux2_klein"
    model = _choice(data, "model", models, default_m)
    base_prompt = _text(data, "prompt", MAX_PROMPT)
    if not base_prompt:
        raise SpecError("Prompt is required")
    negative = _text(data, "negative", MAX_NEGATIVE, PHOTO_DEFAULT_NEGATIVE) or PHOTO_DEFAULT_NEGATIVE
    mult = 8 if (has_ckpt or model not in ("flux2_klein", "qwen_image")) else 16
    width, height = _dims(data, 512, 1536, mult, (1280, 720))

    if has_ckpt:
        loras = photo_options()["loras"]
        lora = str(data.get("lora") or "")
        if lora and lora not in loras:
            raise SpecError("Unknown LoRA")
        ref_mode = _choice(data, "ref_mode", REF_MODES, "none")
        ref_path = resolve_upload(str(data.get("ref_upload") or "")) if ref_mode != "none" else ""
        if ref_mode != "none" and not ref_path:
            raise SpecError("Upload a reference image for the selected reference mode")
        def_st = {"steps": 28, "cfg": 6.5, "sampler": "dpmpp_2m", "scheduler": "karras"}
        samplers, schedulers, min_steps = PHOTO_SAMPLERS, PHOTO_SCHEDULERS, 5
    else:
        if data.get("lora"):
            raise SpecError("Custom LoRAs are not enabled in the public edition")
        lora = ""
        ref_mode = _choice(data, "ref_mode", ("none",), "none")
        ref_path = ""
        def_st = CORE_PHOTO_MODEL_SETTINGS[model]
        samplers, schedulers, min_steps = ("euler", "dpmpp_2m", "uni_pc"), ("simple", "karras", "normal"), 1

    notes: list[str] = []
    prompt = base_prompt
    variation = ""
    if data.get("vary_person") and "no humans" not in base_prompt.lower():
        variation = generate_random_person_variation(base_prompt)
        prompt = f"{prompt}, {variation}"
        notes.append(f"Auto person variety: {variation}")

    cfg = {
        "model": model, "prompt": prompt, "negative": negative,
        "width": width, "height": height,
        "steps": _num(data, "steps", def_st["steps"], min_steps, 60, as_int=True),
        "cfg": _num(data, "cfg", def_st["cfg"], 1.0, 15.0),
        "seed": _seed(data),
        "sampler": _choice(data, "sampler", samplers, def_st["sampler"]),
        "scheduler": _choice(data, "scheduler", schedulers, def_st["scheduler"]),
        "ref_image": ref_path, "ref_mode": ref_mode,
        "ref_weight": _num(data, "ref_weight", 0.75, 0.1, 1.2),
        "lora": lora, "lora_strength": _num(data, "lora_strength", 0.85, 0.0, 1.5),
    }
    cfg["output"] = slugify_photo_prompt(base_prompt, _text(data, "output_name", 80), model)
    settings = {k: cfg[k] for k in ("model", "width", "height", "steps", "cfg", "seed", "sampler", "scheduler", "lora", "ref_mode")}
    return {
        "kind": "photo", "prompt": base_prompt, "notes": notes, "settings": settings, "cfg": cfg,
        "library": _library_entry(data, "photo", base_prompt, variation=variation, reference=ref_path),
        "meta": {"base_prompt": base_prompt, "variation": variation, "profile": "", "model": model,
                 "seed": cfg["seed"], "source": "web"},
    }


def prepare_video(data: dict, resolve_upload) -> dict[str, Any]:
    if not addons.REGISTRY.video_enabled:
        raise SpecError("Video generation is not available in the public edition")
    version = _choice(data, "version", [k for k, _ in MODEL_OPTIONS], "2.2")
    base_prompt = _text(data, "prompt", MAX_PROMPT)
    if not base_prompt:
        raise SpecError("Prompt is required")
    negative = _text(data, "negative", MAX_NEGATIVE, DEFAULT_NEGATIVE) or DEFAULT_NEGATIVE
    width, height = _dims(data, 256, 1280, 16, (768, 432))
    fps = _num(data, "fps", 16, 8, 24, as_int=True)
    duration = _num(data, "duration", 4.0, 0.0, 6.0)
    start_image = resolve_upload(str(data.get("start_upload") or ""))
    if start_image and version not in I2V_VERSIONS:
        raise SpecError(addons.REGISTRY.video_ui_strings.get("video_start_i2v_error", "Selected model does not support Start Image (I2V)"))

    frames, actual_sec = duration_to_frames(duration, fps)
    cfg = {
        "version": version, "prompt": base_prompt, "negative": negative,
        "width": width, "height": height, "duration_sec": duration, "fps": fps,
        "steps": _num(data, "steps", VIDEO_MODEL_SETTINGS[version]["steps"], 2, 40, as_int=True),
        "cfg": _num(data, "cfg", 5.0, 1.0, 10.0),
        "seed": _seed(data),
        "sampler": _choice(data, "sampler", VIDEO_SAMPLERS, "uni_pc"),
        "scheduler": _choice(data, "scheduler", VIDEO_SCHEDULERS, "simple"),
        "image": start_image,
    }
    cfg["output_name"] = _text(data, "output_name", 80)
    settings = {k: cfg[k] for k in ("version", "width", "height", "fps", "steps", "cfg", "seed", "sampler", "scheduler")}
    settings.update(frames=frames, seconds=actual_sec, start_image=bool(start_image))
    return {
        "kind": "video", "prompt": base_prompt, "notes": [], "settings": settings, "cfg": cfg,
        "library": _library_entry(data, "video", base_prompt, reference=start_image),
    }


def prepare_reconcile(data: dict) -> dict[str, Any]:
    """Prompt Builder send: the creator's dropdown choices + custom-text vision, for photo (or video)."""
    targets = ("photo", "video") if addons.REGISTRY.video_enabled else ("photo",)
    target = _choice(data, "target", targets, "photo")
    vision = _text(data, "vision", 2000)
    values = _builder_values(data.get("values"))
    if not values and not vision:
        raise SpecError("Pick some dropdowns or write your vision first")
    llm = _llm_choice(data)
    k = addons.llm_ui_strings()["result_model_key"]
    return {"kind": "reconcile", "prompt": vision or "(dropdowns only)", "notes": [],
            "settings": {"target": target, k: llm},
            "values": values, "vision": vision, "target": target, k: llm}


def prepare_fill(data: dict) -> dict[str, Any]:
    """Fill dropdowns from my vision: the LLM picks dropdown values from the vision text.
    Only empty dropdowns unless replace is set; the creator reviews them afterwards."""
    vision = _text(data, "vision", 2000)
    if not vision:
        raise SpecError("Write your vision first")
    raw = data.get("values") if isinstance(data.get("values"), dict) else {}
    llm = _llm_choice(data)
    k = addons.llm_ui_strings()["result_model_key"]
    return {"kind": "fill", "prompt": vision, "notes": [], "settings": {"replace": bool(data.get("replace")), k: llm},
            "values": _builder_values(raw), "vision": vision, "replace": bool(data.get("replace")), k: llm}


def _llm_choice(data: dict) -> str:
    k = addons.llm_ui_strings()["result_model_key"]
    name = str(data.get("llm") or data.get(k) or "")
    return name if name in {d["name"] for d in prompt_llms()} else default_prompt_llm()


def turn_needs(plan: dict[str, Any]) -> str:
    """What the GPU turn's first step needs: the chosen LLM loaded (Ollama), or the whole card.
    Resolves the LLM now (falling back to an installed one) and records it in the plan."""
    pp = addons.pair_provider()
    if plan["kind"] in ("reconcile", "fill") or (pp and plan["kind"] == pp.kind):
        k = addons.llm_ui_strings()["result_model_key"]
        model, why = resolve_prompt_llm(plan.get(k) or plan.get("llm"))
        plan[f"{k}_resolved"] = model or ""
        if why:
            plan["notes"].append(why)
        return f"ollama:{model}" if model else "none"
    return "exclusive"


def builder_preview(data: dict) -> dict[str, Any]:
    """Live preview: the prompt the dropdowns (+ vision) make right now, with the Python conflict notes."""
    targets = ("photo", "video") if addons.REGISTRY.video_enabled else ("photo",)
    target = _choice(data, "target", targets, "photo")
    vision = _text(data, "vision", 2000)
    values = _builder_values(data.get("values"))
    extras = [("extra_notes", vision)] if vision else None
    prompt, notes = rectify_builder_fields(values, extra_clauses=extras, include_motion=(target == "video"))
    return {"prompt": prompt, "notes": notes}


def _builder_values(raw: Any) -> dict[str, str]:
    """Only real dropdown choices from the catalog; "None" picks are dropped."""
    values: dict[str, str] = {}
    for key, val in (raw.items() if isinstance(raw, dict) else ()):
        field = FIELD_BY_KEY.get(str(key))
        if field and str(val) in field[3] and not str(val).lower().startswith("none"):
            values[str(key)] = str(val)
    return values


def _library_entry(data: dict, target: str, prompt: str, variation: str = "", reference: str = "") -> dict[str, Any]:
    """What the library stores for this job: the builder state behind the prompt (if the form was filled
    by a Prompt Builder send), so "Import into Prompt Builder" can bring it all back later."""
    raw = data.get("builder") if isinstance(data.get("builder"), dict) else {}
    values = _builder_values(raw.get("values"))
    vision = _text(raw, "vision", 2000)
    builder = None
    if values or vision:
        k = addons.llm_ui_strings()["result_model_key"]
        chosen = str(raw.get("llm") or raw.get(k) or "")
        builder = {"values": values, "vision": vision, "target": target,
                   "reconciled_prompt": _text(raw, "reconciled_prompt", MAX_PROMPT),
                   "final_prompt": _text(raw, "final_prompt", MAX_PROMPT),
                   k: chosen if chosen in {d["name"] for d in prompt_llms()} else ""}
    return {"source": "web-builder" if builder else "web", "builder": builder, "prompt": prompt,
            "variation": variation, "reference": reference}


def finalize(plan: dict[str, Any]) -> dict[str, Any]:
    """Inside the GPU turn: produce what the job needs.

    reconcile -> {"prompt", "notes", ..., model/version + settings}
    photo/video -> {"effective_prompt", "notes", "cmd", "output", "cfg"}
    """
    kind = plan["kind"]
    k = addons.llm_ui_strings()["result_model_key"]
    resolved = plan.get(f"{k}_resolved") or plan.get("llm_resolved") or None
    if kind == "reconcile":
        values, vision, target = plan["values"], plan["vision"], plan["target"]
        return reconcile_for_target(values, vision, target, resolved)
    if kind == "fill":
        values, notes = fill_from_vision(plan["values"], plan["vision"], replace=plan["replace"],
                                         use_llm=bool(resolved), model=resolved)
        return {"values": values, "notes": notes}
    pp = addons.pair_provider()
    if pp and kind == pp.kind:
        return pp.finalize_pair(plan)
    cfg = dict(plan["cfg"])
    # Same Python cleanup as the desktop Generate button; otherwise rendered as typed.
    prompt, rect_notes = rectify_freeform_prompt(cfg["prompt"], use_extra_llm=False)
    cfg["prompt"] = prompt or cfg["prompt"]
    notes = [f"Conflict rectifier: {n}" for n in rect_notes]
    if kind == "photo":
        return {"effective_prompt": cfg["prompt"], "notes": notes, "cmd": build_photo_cli_command(cfg),
                "output": cfg["output"], "cfg": cfg}
    cfg["output"] = slugify_prompt(cfg["prompt"], cfg.pop("output_name", ""), cfg["version"])
    return {"effective_prompt": cfg["prompt"], "notes": notes, "cmd": build_cli_command(cfg), "output": cfg["output"], "cfg": cfg}


if addons.REGISTRY.attach_specs_compat:
    addons.REGISTRY.attach_specs_compat(sys.modules[__name__])
