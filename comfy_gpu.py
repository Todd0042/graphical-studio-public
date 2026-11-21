"""VRAM helpers for scripts that run ComfyUI nodes in-process."""

import gc


def free_vram() -> None:
    """Move loaded models off the GPU (kept in RAM; ComfyUI reloads them on next use)."""
    import comfy.model_management
    import torch

    gc.collect()
    comfy.model_management.unload_all_models()
    comfy.model_management.soft_empty_cache()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
