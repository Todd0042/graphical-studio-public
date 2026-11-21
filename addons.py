"""Optional extension registry for Graphical Studio.

Core ships clean image-only defaults and executes local tasks directly. When the optional ``extras``
package is present alongside the repository, ``addons`` loads it once at import time and exposes its
registered extensions. When ``extras`` is absent, every helper returns the safe core default.
"""

from __future__ import annotations

import os

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class AddonRegistry:
    enabled: bool = False
    manifest_overlay: Callable[[dict], dict] | None = None
    models: dict[str, Any] = field(default_factory=dict)
    llm: dict[str, Any] = field(default_factory=dict)
    catalog: dict[str, Any] = field(default_factory=dict)
    desktop: dict[str, Any] = field(default_factory=dict)
    web: dict[str, Any] = field(default_factory=dict)
    session: dict[str, Any] = field(default_factory=dict)
    compat: dict[str, Callable[[Any], None]] = field(default_factory=dict)


class DirectSession:
    """Direct local execution context when no external session extension is loaded."""

    def __init__(self, *_args, **_kwargs) -> None:
        self.lease_id: str | None = None

    @property
    def held(self) -> bool:
        return True

    def acquire(self) -> "DirectSession":
        return self

    def step(self, _needs: str) -> None:
        return None

    def release(self) -> None:
        return None

    def others_waiting(self) -> bool:
        return False

    def yield_if_waiting(self, _before_release=None) -> bool:
        return False

    def __enter__(self) -> "DirectSession":
        return self

    def __exit__(self, *_exc) -> None:
        return None


class _DirectDesktopSession:
    waiting = False

    @staticmethod
    def run(_job_id: str, _needs: str, start: Callable[[], None], _on_cancelled: Callable[[], None]) -> None:
        start()

    @staticmethod
    def cancel() -> bool:
        return False

    @staticmethod
    def release() -> None:
        return None


def _load_registry() -> AddonRegistry:
    reg = AddonRegistry()
    try:
        import extras  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        if exc.name == "extras":
            return reg
        raise
    if extras is not None and hasattr(extras, "register"):
        reg.enabled = True
        extras.register(reg)
    return reg


REGISTRY = _load_registry()


def is_addon_enabled() -> bool:
    return REGISTRY.enabled


def attach_compat(name: str, mod: Any) -> None:
    fn = REGISTRY.compat.get(name)
    if fn:
        fn(mod)


def merge_manifest(base: dict) -> dict:
    if REGISTRY.manifest_overlay:
        return REGISTRY.manifest_overlay(base)
    return base


def execution_session(job_id: str = "", *, needs: str = "exclusive", app_id: str = "graphical_studio", **kwargs):
    factory = REGISTRY.session.get("session_factory")
    if factory:
        return factory(job_id, needs=needs, app_id=app_id, **kwargs)
    return DirectSession()


def session_error() -> type[Exception]:
    return REGISTRY.session.get("session_error_type", RuntimeError)


def desktop_session(root, on_status: Callable[[str], None]):
    factory = REGISTRY.session.get("desktop_session_factory")
    if factory:
        return factory(root, on_status)
    return _DirectDesktopSession()


def desktop_status_label() -> str | None:
    fn = REGISTRY.session.get("desktop_status")
    return fn() if fn else None


def web_status() -> dict[str, Any] | None:
    fn = REGISTRY.web.get("status_overlay")
    return fn() if fn else None


def media_kind_specs(outputs_dir: str, photos_dir: str) -> dict[str, tuple[str, tuple[str, ...]]]:
    specs: dict[str, tuple[str, tuple[str, ...]]] = {
        "photo": (photos_dir, (".jpg", ".jpeg", ".png", ".webp")),
        "asset": (os.path.join(outputs_dir, "assets"), (".png",)),  # Asset Studio; size exports sit in <name>_sizes/
    }
    extra = REGISTRY.web.get("media_kinds")
    if extra:
        for k, val in extra.items():
            specs[k] = val(outputs_dir, photos_dir) if callable(val) else val
    return specs


def llm_ui_strings() -> dict[str, str]:
    defaults = {
        "picker_label": "Prompt LLM",
        "picker_help": "Which local instruct model reconciles and fills the dropdowns. Red = slow on an 8 GB card.",
        "desktop_picker_tooltip": "Which local instruct model reconciles and fills the dropdowns. Red = slow on an 8 GB card.",
        "vision_help": "Describe what the picture should be. The LLM checks your dropdown choices against this and fixes anything that conflicts.",
        "fill_tooltip": "The LLM picks dropdown values from your vision. Only empty dropdowns are filled unless 'Replace my picks too' is ticked. Review them before reconciling.",
        "preview_label": "Preview (before LLM):",
        "preview_help": "What your dropdowns and vision make right now (before the LLM).",
        "reconcile_btn": "✨ Reconcile Prompt",
        "reconcile_web_btn": "Reconcile prompt",
        "final_help": "Reconciled prompt. Edit it freely; this exact text is what gets sent.",
        "status_icon": "✨",
        "actor_name": "Prompt LLM",
        "api_list_key": "llms",
        "result_model_key": "llm",
        "result_used_key": "used_llm",
        "storage_key": "gs-llm",
    }
    extra = REGISTRY.llm.get("ui_strings")
    if extra:
        defaults.update(extra)
    return defaults
