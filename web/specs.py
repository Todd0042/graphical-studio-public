"""Validate web requests into job plans, reusing the desktop app's own builders.

Two stages: prepare_* (at submit) validate everything into a JSON-safe plan; the job then runs
inside its execution turn (finalize):
  photo      render the prompt as typed, after the same Python cleanup as the desktop Generate button
  reconcile  Prompt Builder send: the local LLM reconciles the chosen dropdowns against the
             custom-text vision (studio_reconcile.py) and picks model + settings
Everything a browser sends is checked against allow-lists and numeric bounds before it
reaches argv; commands are argv lists (never a shell string).
"""

from __future__ import annotations

import random
import sys
from typing import Any

import addons
from studio_prompt_catalog import FIELD_BY_KEY
from studio_models import default_prompt_llm, prompt_llms, resolve_prompt_llm
from studio_reconcile import reconcile_for_target
from studio_vibe import fill_from_vision

from studio_profiles import generate_random_person_variation
import studio_assets
from studio_rectifier import rectify_builder_fields, rectify_freeform_prompt
from studio_helpers import (
    CORE_PHOTO_MODEL_SETTINGS,
    PHOTO_DEFAULT_NEGATIVE,
    PHOTO_PRESETS,
    build_photo_cli_command,
    get_photo_model_options,
    list_photo_loras,
    slugify_photo_prompt,
)

PHOTO_SAMPLERS = ("dpmpp_2m", "euler", "uni_pc")
PHOTO_SCHEDULERS = ("karras", "simple", "normal")
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
    if addons.REGISTRY.models.get("photo_registry"):
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


def prepare_photo(data: dict, resolve_upload) -> dict[str, Any]:
    models = [k for k, _ in get_photo_model_options()]
    has_ckpt = bool(addons.REGISTRY.models.get("photo_registry"))
    default_m = addons.REGISTRY.models.get("default_photo_model") or "flux2_klein"
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
            raise SpecError("Custom LoRAs are not supported for the selected models")
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


# ---- Asset Studio (icons, backgrounds, textures, sprites): the desktop tab's engine, studio_assets.py ----------
ASSET_KINDS = tuple(studio_assets.KIND_LABELS)
_ASSET_TEXT = {"prompt": MAX_PROMPT, "negative": MAX_NEGATIVE, "final_size": 20, "export_sizes": 80, "title": 120}
_ASSET_FIELD_MAX = 300


def asset_options() -> dict[str, Any]:
    return {
        "kinds": [{"key": k, "label": v} for k, v in studio_assets.KIND_LABELS.items()],
        "models": [{"key": k, "label": label, "installed": ok} for k, label, ok in studio_assets.model_choices()],
        "samplers": list(studio_assets.SAMPLERS), "schedulers": list(studio_assets.SCHEDULERS),
    }


def prepare_asset_plan(data: dict) -> dict[str, Any]:
    """Step 1 (a local-LLM job): a one-line brief -> editable fields and a full render plan with reasons."""
    brief = _text(data, "brief", 1000)
    if not brief:
        raise SpecError("Describe the asset first (e.g. 'app icon for a budgeting app, friendly, flat')")
    fields = data.get("fields")
    if fields is not None and not isinstance(fields, dict):
        raise SpecError("fields must be an object")
    clean = {str(k)[:40]: str(v)[:_ASSET_FIELD_MAX] for k, v in (fields or {}).items() if isinstance(v, (str, int, float))}
    return {"kind": "asset_plan", "prompt": brief, "brief": brief, "notes": [], "settings": {},
            "asset_kind": _choice(data, "asset_kind", ("auto", *ASSET_KINDS), "auto"),
            "fields": clean, "concept": _text(data, "concept", 1000), "llm": _llm_choice(data)}


def prepare_asset(data: dict, _resolve_upload=None) -> dict[str, Any]:
    """Step 2 (exclusive GPU job): render an edited plan with generate_asset.py."""
    raw = data.get("plan")
    if not isinstance(raw, dict):
        raise SpecError("Plan the asset first, then generate it")
    kind = raw.get("kind") if raw.get("kind") in ASSET_KINDS else None
    if not kind:
        raise SpecError("Unknown asset kind")
    plan: dict[str, Any] = {"kind": kind}
    for key in ("model", "sampler", "scheduler", "tile", "remove_bg"):
        plan[key] = str(raw.get(key) or "")[:40]
    for key in ("width", "height", "steps", "cfg", "guidance", "seed", "pixelate"):
        if isinstance(raw.get(key), (int, float)) and not isinstance(raw.get(key), bool):
            plan[key] = raw[key]
    for key, limit in _ASSET_TEXT.items():
        plan[key] = str(raw.get(key) or "")[:limit]
    plan["hollow"], plan["lightning"] = bool(raw.get("hollow")), bool(raw.get("lightning"))
    if not plan["prompt"].strip():
        raise SpecError("The plan has no prompt")
    if plan["model"] not in studio_assets.ASSET_MODELS:
        raise SpecError("Unknown asset model")
    out = studio_assets.output_path(kind, plan["title"], plan["prompt"])
    settings = {k: plan.get(k) for k in ("kind", "model", "width", "height", "steps", "seed")}
    return {"kind": "asset", "prompt": plan["prompt"], "notes": [], "settings": settings, "asset_plan": plan, "output": out,
            "library": _library_entry(data, "asset", plan["prompt"])}


def _valid_targets() -> tuple[str, ...]:
    extra = tuple(addons.REGISTRY.web.get("builder_targets") or ())
    return ("photo", *extra)


def prepare_reconcile(data: dict) -> dict[str, Any]:
    """Prompt Builder send: the creator's dropdown choices + custom-text vision."""
    target = _choice(data, "target", _valid_targets(), "photo")
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
    """Fill dropdowns from my vision: the LLM picks dropdown values from the vision text."""
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
    """What the session's first step needs: the chosen LLM loaded (Ollama), or exclusive device access."""
    llm_kinds = {"reconcile", "fill", "asset_plan", *tuple(addons.REGISTRY.web.get("llm_job_kinds") or ())}
    if plan["kind"] in llm_kinds:
        k = addons.llm_ui_strings()["result_model_key"]
        model, why = resolve_prompt_llm(plan.get(k) or plan.get("llm"))
        plan[f"{k}_resolved"] = model or ""
        if why:
            plan["notes"].append(why)
        return f"ollama:{model}" if model else "none"
    return "exclusive"


def builder_preview(data: dict) -> dict[str, Any]:
    """Live preview: the prompt the dropdowns (+ vision) make right now, with the Python conflict notes."""
    target = _choice(data, "target", _valid_targets(), "photo")
    vision = _text(data, "vision", 2000)
    values = _builder_values(data.get("values"))
    extras = [("extra_notes", vision)] if vision else None
    prompt, notes = rectify_builder_fields(values, extra_clauses=extras, include_motion=(target != "photo"))
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
    """What the library stores for this job."""
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
    """Inside the execution turn: produce what the job needs."""
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
    if kind == "asset_plan":
        use = bool(resolved)
        if plan["fields"]:  # the creator already edited the fields: only re-plan the render
            exp = {"kind": plan["asset_kind"] if plan["asset_kind"] in ASSET_KINDS else "icon", "title": "",
                   "concept": plan["concept"], "fields": plan["fields"], "notes": []}
        else:
            exp = studio_assets.expand_brief(plan["brief"], plan["asset_kind"], llm=resolved or "", use_llm=use)
        if exp["kind"] not in ASSET_KINDS:
            raise SpecError("Couldn't tell what kind of asset that is; pick one")
        render = studio_assets.analyze(exp["kind"], exp["fields"], exp["concept"], llm=resolved or "", use_llm=use)
        render["title"] = exp.get("title") or ""
        notes = list(exp.get("notes") or []) + list(render.get("notes") or [])
        return {"notes": notes, "kind": exp["kind"], "title": exp.get("title") or "", "concept": exp["concept"],
                "fields": exp["fields"], "plan": render, "refused": bool(render.get("refused"))}
    if kind == "asset":
        cmd = studio_assets.build_command(plan["asset_plan"], plan["output"])
        return {"effective_prompt": plan["prompt"], "notes": [], "cmd": cmd, "output": plan["output"],
                "cfg": plan["asset_plan"]}
    finalizer = (addons.REGISTRY.web.get("job_finalizers") or {}).get(kind)
    if finalizer:
        return finalizer(plan)
    if kind != "photo":
        raise SpecError(f"Unsupported job kind: {kind}")
    cfg = dict(plan["cfg"])
    prompt, rect_notes = rectify_freeform_prompt(cfg["prompt"], use_extra_llm=False)
    cfg["prompt"] = prompt or cfg["prompt"]
    notes = [f"Conflict rectifier: {n}" for n in rect_notes]
    return {"effective_prompt": cfg["prompt"], "notes": notes, "cmd": build_photo_cli_command(cfg),
            "output": cfg["output"], "cfg": cfg}


addons.attach_compat("web.specs", sys.modules[__name__])
