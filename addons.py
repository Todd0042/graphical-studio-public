"""Optional extension registry for Graphical Studio.

Core ships neutral SFW-only defaults and runs renders directly. When the optional private ``extras``
package is present alongside the repo, ``addons`` loads it once at import time and exposes its
registered extensions. When ``extras`` is absent, every helper returns the safe core default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class AddonRegistry:
    enabled: bool = False
    manifest_overlay: Callable[[dict], dict] | None = None

    # Image / asset models
    photo_model_options: list[tuple[str, str]] | None = None
    default_photo_model: str | None = None
    photo_model_registry: dict[str, dict] | None = None
    photo_model_settings: dict[str, dict] | None = None
    photo_benchmark_targets: list[str] | None = None
    photo_cli_builder: Callable[[dict], list[str]] | None = None
    photo_supports_ipadapter: bool = False
    lora_exclude_prefix: str | None = None
    builtin_ckpts: set[str] | None = None
    fallback_model_key: str | None = None

    asset_models: dict[str, dict] | None = None
    asset_model_settings: dict[str, dict] | None = None
    asset_fallback_order: list[str] | None = None
    asset_llm_ranking: list[tuple[str, str]] | None = None
    asset_choose_model: Callable[[str, dict[str, str], str], tuple[str, str] | None] | None = None
    asset_checkpoint_renderer: Callable[..., Any] | None = None
    asset_prompt_system: str | None = None
    anime_asset_models: set[str] = field(default_factory=set)
    anime_photo_model: str | None = None
    legacy_pair_meta_key: str | None = None

    # Video extensions (absent in image-only public edition)
    video_enabled: bool = False
    video_model_options: list[tuple[str, str]] | None = None
    video_caution_models: frozenset[str] = field(default_factory=frozenset)
    video_i2v_versions: frozenset[str] = field(default_factory=frozenset)
    video_model_settings: dict[str, dict] | None = None
    video_presets: dict[str, tuple[int, int, float, int]] | None = None
    video_default_negative: str = ""
    video_gen_script: str | None = None
    video_slug_prefix: str | None = None
    video_cli_builder: Callable[[dict], list[str]] | None = None
    video_motion_fields: list[tuple] | None = None
    video_tooltips: dict[str, str] = field(default_factory=dict)
    video_ui_strings: dict[str, str] = field(default_factory=dict)
    default_sync_groups: tuple[str, ...] = ("assets",)
    check_sync_groups: tuple[str, ...] = ("assets",)
    startup_sync_groups: tuple[str, ...] = ("assets",)
    extra_model_cli_args: Callable[[Any], None] | None = None
    extra_model_sync_groups: Callable[[Any], list[str]] | None = None

    # Catalog, presets, tooltips, vibe
    extend_catalog: Callable[[list, list, list, list], None] | None = None
    extend_presets: Callable[[list], list] | None = None
    tooltips_override: dict[str, str] = field(default_factory=dict)
    extend_tooltips: Callable[[dict[str, str]], None] | None = None
    vibe_extra_triggers: list[tuple[str, set[str]]] = field(default_factory=list)
    vibe_extra_aliases: dict[str, set[str]] = field(default_factory=dict)
    vibe_llm_system_prompt: str | None = None
    post_fill_vision: Callable[[dict[str, str], str, dict[str, str], bool, list[str]], None] | None = None
    anti_zoom_neg_extra: str = ""

    # Compatibility, routing, rectifier, reconcile
    classify_intent: Callable[[dict[str, str], str, dict], dict] | None = None
    choose_photo_model: Callable[[dict, str], str] | None = None
    extra_content_negatives: Callable[[dict], list[str]] | None = None
    filter_photo_compat: Callable[[dict, str, str], tuple[str | None, str | None]] | None = None
    video_compat_overrides: Callable[[dict, bool], dict] | None = None
    extend_conflict_groups: Callable[[dict], dict] | None = None
    rectifier_llm_messages: Callable[[str, dict[str, str], str], tuple[str, str]] | None = None
    attach_rectifier_compat: Callable[[Any], None] | None = None
    attach_reconcile_compat: Callable[[Any], None] | None = None
    attach_specs_compat: Callable[[Any], None] | None = None
    attach_models_compat: Callable[[Any], None] | None = None
    resolve_llm_override: Callable[[str | None], tuple[str | None, str]] | None = None
    reconcile_system_prompt: str | None = None
    reconcile_post_check: Callable[..., str] | None = None
    run_llm_override: Callable[..., tuple[str | None, str, str]] | None = None

    # LLM selection / execution
    llm_manifest_key: str = "instruct"
    llm_ui_strings: dict[str, str] = field(default_factory=dict)
    legacy_llm_runners: tuple[Callable[..., tuple[str | None, str]], ...] = ()
    extra_llm_hints: tuple[str, ...] = ()
    allow_refusal_fallback: bool = False
    llm_missing_note: str | None = None
    llm_offline_note: str | None = None

    # Features & environment integrations
    pair_provider: Any = None
    self_test_hook: Callable[[], None] | None = None
    video_compat_banner: Callable[[dict], str | None] | None = None
    photo_tab_title: str | None = None
    photo_ready_status: str | None = None
    private_web_defaults: dict[str, Any] = field(default_factory=dict)
    private_desktop_shortcuts: dict[str, Any] = field(default_factory=dict)
    gpu_app_labels: dict[str, str] = field(default_factory=dict)
    gpu_competing_apps: str | None = None
    gpu_session_factory: Callable[..., Any] | None = None
    gpu_session_error_type: type[Exception] = RuntimeError
    gpu_status_provider: Callable[[], dict[str, Any]] | None = None
    desktop_session_factory: Callable[[Any, Callable[[str], None]], Any] | None = None
    desktop_gpu_status: Callable[[], str | None] | None = None
    gpu_offline_label: str = ""
    gpu_active_key: str = ""
    gpu_unavailable_note: str = "GPU unavailable"


class DirectSession:
    """Direct local execution context when no multi-app GPU extension is loaded."""

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


def gpu_session(job_id: str = "", *, needs: str = "exclusive", app_id: str = "graphical_studio", **kwargs):
    if REGISTRY.gpu_session_factory:
        return REGISTRY.gpu_session_factory(job_id, needs=needs, app_id=app_id, **kwargs)
    return DirectSession()


def gpu_session_error() -> type[Exception]:
    return REGISTRY.gpu_session_error_type


def desktop_session(root, on_status: Callable[[str], None]):
    if REGISTRY.desktop_session_factory:
        return REGISTRY.desktop_session_factory(root, on_status)
    return _DirectDesktopSession()


def desktop_status_label() -> str | None:
    if REGISTRY.desktop_gpu_status:
        return REGISTRY.desktop_gpu_status()
    return None


def gpu_web_status() -> dict[str, Any] | None:
    if REGISTRY.gpu_status_provider:
        return REGISTRY.gpu_status_provider()
    return None


def is_addon_enabled() -> bool:
    return REGISTRY.enabled


def merge_manifest(base: dict) -> dict:
    if REGISTRY.manifest_overlay:
        return REGISTRY.manifest_overlay(base)
    return base


def pair_provider():
    return REGISTRY.pair_provider


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
    if REGISTRY.llm_ui_strings:
        defaults.update(REGISTRY.llm_ui_strings)
    return defaults
