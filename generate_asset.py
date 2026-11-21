#!/usr/bin/env python3
"""Headless asset renderer (icons, backgrounds, textures, sprites) for 8 GB cards.

Engines (see ASSET_MODELS):
  flux_dev / flux_schnell  Flux.1 GGUF Q4 + T5 Q4 GGUF + CLIP-L + ae VAE (ComfyUI-GGUF node).
                           Best prompt adherence, clean vector/3D icon looks, can spell short words.
  flux2_klein / qwen_image FLUX.2 klein 4B and Qwen-Image 20B (natural-language prompt encoders).

Post-processing (all optional): --remove-bg (rembg cut-out to a transparent PNG), --pixelate N,
--final-size WxH (Lanczos resize/crop), --export-sizes 16,32,... (square PNG copies next to master).

Prints "[Asset <model>] Saved <path>" for the master image and one JSON line "ASSET_RESULT=..." at the end.
"""

from __future__ import annotations

import argparse
import gc
import importlib.util
import json
import os
import sys
import time

import addons

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("HF_HOME", os.path.join(ROOT_DIR, ".cache", "huggingface"))
os.environ.setdefault("TORCH_HOME", os.path.join(ROOT_DIR, ".cache", "torch"))
os.environ.setdefault("TMPDIR", os.path.join(ROOT_DIR, ".cache", "tmp"))
os.environ.setdefault("U2NET_HOME", os.path.join(ROOT_DIR, ".cache", "rembg"))
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

COMFY_DIR = os.path.join(ROOT_DIR, "ComfyUI")

# engine: flux | klein | qwen. Files are relative to ComfyUI/models/<folder>.
_BASE_ASSET_MODELS = {
    "flux_dev": {"engine": "flux", "unet": "flux1-dev-Q4_K_S.gguf", "label": "Flux.1 dev (best adherence, ~2-4 min)"},
    "flux_schnell": {"engine": "flux", "unet": "flux1-schnell-Q4_K_S.gguf", "label": "Flux.1 schnell (fast draft, 4 steps)"},
    # Apache 2.0. FLUX.2 [klein] 4B: Qwen3-4B text encoder, 4-step distilled, fits fully in 8 GB.
    "flux2_klein": {"engine": "klein", "unet": "flux-2-klein-4b-Q8_0.gguf", "te": "qwen_3_4b.safetensors",
                    "vae": "flux2-vae.safetensors", "label": "FLUX.2 klein 4B (strong prompt following, fast)"},
    # Apache 2.0. Qwen-Image 20B: Qwen2.5-VL text encoder, best prompt following + text. ~12 GB at Q4, so it spills
    # onto the CPU / system RAM on an 8 GB card (slow). Lightning LoRA = 8 steps instead of ~28.
    "qwen_image": {"engine": "qwen", "unet": "qwen-image-Q4_K_S.gguf", "te": "qwen_2.5_vl_7b_fp8_scaled.safetensors",
                   "vae": "qwen_image_vae.safetensors", "lightning": "Qwen-Image-Lightning-8steps-V2.0-bf16.safetensors",
                   "spills": True, "label": "Qwen-Image 20B (best prompt following & text; spills to CPU, slow)"},
}


def _build_asset_models() -> dict[str, dict]:
    merged = dict(_BASE_ASSET_MODELS)
    if addons.REGISTRY.asset_models:
        merged.update(addons.REGISTRY.asset_models)
    return merged


ASSET_MODELS = _build_asset_models()
FLUX_FILES = {"clip_l": "clip_l.safetensors", "t5": "t5-v1_1-xxl-encoder-Q4_K_M.gguf", "vae": "ae.safetensors"}


def model_files(key: str) -> list[str]:
    """Paths (under ComfyUI/models) a model needs; used by the UI to show what's installed."""
    spec = ASSET_MODELS[key]
    if spec["engine"] == "flux":
        return [f"unet/{spec['unet']}", f"clip/{FLUX_FILES['clip_l']}", f"clip/{FLUX_FILES['t5']}", f"vae/{FLUX_FILES['vae']}"]
    if spec["engine"] in ("klein", "qwen"):
        return [f"unet/{spec['unet']}", f"text_encoders/{spec['te']}", f"vae/{spec['vae']}"] + \
            ([f"loras/{spec['lightning']}"] if spec.get("lightning") else [])
    out = [f"checkpoints/{spec['ckpt']}"]
    if spec.get("lora"):
        out.append(f"loras/{spec['lora']}")
    return out


def model_installed(key: str) -> bool:
    return all(os.path.isfile(os.path.join(COMFY_DIR, "models", f)) for f in model_files(key))


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Render an icon / background / texture / sprite asset.")
    p.add_argument("--model", choices=sorted(ASSET_MODELS), default="flux_dev")
    p.add_argument("--prompt", required=True)
    p.add_argument("--negative", default="")
    p.add_argument("--output", required=True, help="Master image path (.png recommended)")
    p.add_argument("--width", type=int, default=1024)
    p.add_argument("--height", type=int, default=1024)
    p.add_argument("--steps", type=int, default=24)
    p.add_argument("--cfg", type=float, default=1.0, help="Classifier-free guidance scale (Flux samples at 1.0)")
    p.add_argument("--guidance", type=float, default=3.5, help="Flux distilled guidance (dev only)")
    p.add_argument("--seed", type=int, default=42026)
    p.add_argument("--sampler", default="euler")
    p.add_argument("--scheduler", default="simple")
    p.add_argument("--lora-strength", type=float, default=None)
    p.add_argument("--lightning", action="store_true", help="Qwen-Image: use the 8-step Lightning LoRA (cfg 1)")
    p.add_argument("--raw-prompt", action="store_true", help="Skip the per-model quality prefix/negatives")
    p.add_argument("--tile", choices=["none", "both", "x"], default="none", help="Seamless tiling (optional checkpoint add-on)")
    p.add_argument("--remove-bg", choices=["none", "general", "anime"], default="none")
    p.add_argument("--pixelate", type=int, default=0, help="Snap to a pixel grid of this cell size (0 = off)")
    p.add_argument("--final-size", default="", help="WxH to resize/cover-crop the master to (e.g. 1920x1080)")
    p.add_argument("--export-sizes", default="", help="Comma-separated square sizes, e.g. 16,32,48,256")
    p.add_argument("--hollow", action="store_true", help="UI frames: make the flat interior transparent and measure 9-slice margins")
    return p.parse_args(argv)


def free_vram():
    import comfy.model_management
    import torch

    gc.collect()
    comfy.model_management.unload_all_models()
    comfy.model_management.soft_empty_cache()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def _gguf_nodes():
    pkg_dir = os.path.join(COMFY_DIR, "custom_nodes", "ComfyUI-GGUF")
    if not os.path.isfile(os.path.join(pkg_dir, "__init__.py")):
        raise SystemExit("Error: Flux needs ComfyUI/custom_nodes/ComfyUI-GGUF (start_graphical_studio.sh --model-sync --assets).")
    mod = sys.modules.get("comfyui_gguf")
    if mod is None:
        spec = importlib.util.spec_from_file_location("comfyui_gguf", os.path.join(pkg_dir, "__init__.py"),
                                                      submodule_search_locations=[pkg_dir])
        mod = importlib.util.module_from_spec(spec)
        sys.modules["comfyui_gguf"] = mod
        spec.loader.exec_module(mod)
    return mod.NODE_CLASS_MAPPINGS


def _with_prefix(text: str, prefix: str) -> str:
    text = text.strip()
    if not prefix:
        return text
    lead = prefix.split(",")[0].strip().lower()
    return text if lead in text.lower() else prefix + text


def render(args) -> "object":
    """Sample and decode; returns a PIL image (RGB)."""
    import numpy as np
    import torch
    from PIL import Image
    import nodes
    import node_helpers

    spec = ASSET_MODELS[args.model]
    tag = f"[Asset {args.model}]"
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    latent = nodes.EmptyLatentImage().generate(width=args.width, height=args.height, batch_size=1)[0]
    sigmas = None  # set for engines that need their own schedule (FLUX.2)

    if spec["engine"] in ("klein", "qwen"):
        if args.tile != "none":
            print(f"{tag} Note: seamless tiling is not supported on {args.model}; rendering without it.", flush=True)
        g = _gguf_nodes()
        print(f"{tag} Encoding prompt ({spec['te']})...", flush=True)
        clip = nodes.CLIPLoader().load_clip(spec["te"], type="flux2" if spec["engine"] == "klein" else "qwen_image")[0]
        enc = nodes.CLIPTextEncode()
        positive = enc.encode(clip, args.prompt.strip())[0]
        negative = enc.encode(clip, args.negative.strip() if spec["engine"] == "qwen" else "")[0]
        del clip, enc
        free_vram()
        print(f"{tag} Loading {spec['unet']}" + (" (larger than VRAM: part of it runs from system RAM)" if spec.get("spills") else "")
              + "...", flush=True)
        model = g["UnetLoaderGGUF"]().load_unet(spec["unet"])[0]
        vae = nodes.VAELoader().load_vae(spec["vae"])[0]
        cfg = args.cfg
        if spec["engine"] == "klein":
            import torch as _t
            from comfy_extras.nodes_flux import get_schedule

            latent = {"samples": _t.zeros([1, 128, args.height // 16, args.width // 16])}
            sigmas = get_schedule(args.steps, round(args.width * args.height / 256))
        else:
            from comfy_extras.nodes_model_advanced import ModelSamplingAuraFlow

            if args.lightning and spec.get("lightning"):
                model = nodes.LoraLoaderModelOnly().load_lora_model_only(model, spec["lightning"], 1.0)[0]
                print(f"{tag} Lightning LoRA: 8-step mode", flush=True)
            model = ModelSamplingAuraFlow().patch_aura(model, 3.1)[0]
    elif spec["engine"] == "flux":
        if args.tile != "none":
            print(f"{tag} Note: seamless tiling is not supported on {args.model}; rendering without it.", flush=True)
        g = _gguf_nodes()
        print(f"{tag} Encoding prompt (CLIP-L + T5 Q4)...", flush=True)
        clip = g["DualCLIPLoaderGGUF"]().load_clip(FLUX_FILES["clip_l"], FLUX_FILES["t5"], "flux")[0]
        enc = nodes.CLIPTextEncode()
        positive = enc.encode(clip, args.prompt.strip())[0]
        negative = enc.encode(clip, "")[0]
        if args.model == "flux_dev":
            positive = node_helpers.conditioning_set_values(positive, {"guidance": args.guidance})
        del clip, enc
        free_vram()
        print(f"{tag} Loading {spec['unet']}...", flush=True)
        model = g["UnetLoaderGGUF"]().load_unet(spec["unet"])[0]
        vae = nodes.VAELoader().load_vae(FLUX_FILES["vae"])[0]
        cfg = 1.0
    elif addons.REGISTRY.asset_checkpoint_renderer:
        model, positive, negative, vae, cfg = addons.REGISTRY.asset_checkpoint_renderer(args, spec, tag)
    else:
        raise SystemExit(f"Unsupported engine for public edition: {spec['engine']}")

    print(f"{tag} Sampling {args.steps} steps @ {args.width}x{args.height} (cfg={cfg}, {args.sampler}/{args.scheduler})...", flush=True)
    t0 = time.time()
    with torch.inference_mode():
        if sigmas is not None:
            import comfy.sample
            import comfy.samplers

            lat = comfy.sample.fix_empty_latent_channels(model, latent["samples"])
            noise = comfy.sample.prepare_noise(lat, args.seed)
            out = comfy.sample.sample_custom(model, noise, cfg, comfy.samplers.sampler_object(args.sampler), sigmas,
                                             positive, negative, lat, seed=args.seed)
            samples = {"samples": out}
        else:
            samples = nodes.KSampler().sample(model=model, seed=args.seed, steps=args.steps, cfg=cfg,
                                              sampler_name=args.sampler, scheduler=args.scheduler,
                                              positive=positive, negative=negative, latent_image=latent, denoise=1.0)[0]
    t_sample = time.time() - t0
    del model, positive, negative, latent
    free_vram()
    with torch.inference_mode():
        decoded = nodes.VAEDecode().decode(vae=vae, samples=samples)[0]
    while decoded.dim() > 4:  # some VAEs return a batch-of-frames dimension
        decoded = decoded[0]
    arr = (np.clip(decoded[0].detach().float().cpu().numpy(), 0.0, 1.0) * 255.0).round().astype(np.uint8)
    peak = (torch.cuda.max_memory_allocated() / 1e9) if torch.cuda.is_available() else 0.0
    del decoded, samples, vae
    free_vram()
    print(f"{tag} Sampled in {t_sample:.1f}s (peak VRAM {peak:.2f} GB)", flush=True)
    return Image.fromarray(arr)


def pixelate(img, cell: int):
    from PIL import Image

    small = img.resize((max(1, img.width // cell), max(1, img.height // cell)), Image.Resampling.BOX)
    small = small.quantize(colors=48, method=Image.Quantize.MEDIANCUT).convert(img.mode if img.mode == "RGBA" else "RGB")
    return small.resize((small.width * cell, small.height * cell), Image.Resampling.NEAREST)


def cover_resize(img, w: int, h: int):
    from PIL import Image

    scale = max(w / img.width, h / img.height)
    resized = img.resize((max(w, round(img.width * scale)), max(h, round(img.height * scale))), Image.Resampling.LANCZOS)
    left, top = (resized.width - w) // 2, (resized.height - h) // 2
    return resized.crop((left, top, left + w, top + h))


def remove_background(img, model: str):
    from rembg import new_session, remove

    names = {"general": "birefnet-general", "anime": "isnet-anime"}
    out = remove(img.convert("RGBA"), session=new_session(names[model]))
    return _fill_enclosed(out)


def _fill_enclosed(img):
    """Keep regions the subject encloses opaque (a white plate inside an icon outline is part of the icon,
    not background): anything transparent that the outside can't reach gets its original pixels back."""
    from PIL import Image, ImageChops, ImageDraw

    alpha = img.getchannel("A")
    solid = alpha.point(lambda a: 255 if a > 96 else 0)
    pad = Image.new("L", (solid.width + 2, solid.height + 2), 0)
    pad.paste(solid, (1, 1))
    ImageDraw.floodfill(pad, (0, 0), 128)  # paint everything reachable from outside
    outside = pad.crop((1, 1, solid.width + 1, solid.height + 1)).point(lambda v: 255 if v == 128 else 0)
    inside = ImageChops.invert(outside)  # the subject plus every hole it encloses
    holes = ImageChops.subtract(inside, solid)
    if not holes.getbbox():
        return img
    out = img.copy()
    out.putalpha(ImageChops.lighter(alpha, holes))
    return out


def square_on_canvas(img):
    """Pad an RGBA cut-out to a centered square with a little margin (icon sets must be square)."""
    from PIL import Image

    bbox = img.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox() if img.mode == "RGBA" else None
    if bbox:
        img = img.crop(bbox)
    side = round(max(img.width, img.height) * 1.08)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2), img if img.mode == "RGBA" else None)
    return canvas


def hollow_center(img, tol: int = 44):
    """UI frames: flood-fill the flat interior from the middle and make it transparent (soft 1-2 px edge).
    Returns (image, (left, top, right, bottom) 9-slice margins) or (image, None) if the fill leaked out."""
    from PIL import Image, ImageChops, ImageDraw, ImageFilter

    rgba = img.convert("RGBA")
    w, h = rgba.size
    flat = Image.new("RGB", (w, h), (0, 0, 0))
    flat.paste(rgba, (0, 0), rgba)  # outside already cut out -> black, so the fill can't escape through it
    marked = flat.copy()
    ImageDraw.floodfill(marked, (w // 2, h // 2), (255, 0, 255), thresh=tol)
    region = ImageChops.difference(marked, flat).convert("L").point(lambda v: 255 if v else 0)
    bbox = region.getbbox()
    if not bbox:
        return rgba, None
    l, t, r, b = bbox
    if l == 0 or t == 0 or r == w or b == h:  # touched the edge: the border has a gap, don't punch through
        return rgba, None
    soft = region.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(1.0))
    rgba.putalpha(ImageChops.subtract(rgba.getchannel("A"), soft))
    return rgba, (l, t, w - r, h - b)


def postprocess(img, args) -> tuple[object, list[str]]:
    from PIL import Image

    notes = []
    if args.pixelate and args.pixelate > 1:
        img = pixelate(img, args.pixelate)
        notes.append(f"pixel grid {args.pixelate}px")
    if args.remove_bg != "none":
        print(f"[Asset {args.model}] Removing background ({args.remove_bg}, CPU)...", flush=True)
        img = remove_background(img, args.remove_bg)
        notes.append("transparent background")
    if args.final_size:
        w, h = (int(x) for x in args.final_size.lower().split("x"))
        if img.mode == "RGBA" and w == h:
            img = square_on_canvas(img).resize((w, h), Image.Resampling.LANCZOS)
        elif (w, h) != img.size:
            img = cover_resize(img, w, h) if not args.pixelate else img.resize((w, h), Image.Resampling.NEAREST)
        notes.append(f"final {w}x{h}")
    args.slice_margins = None
    if getattr(args, "hollow", False):
        img, margins = hollow_center(img)
        if margins:
            args.slice_margins = margins
            notes.append("hollow center, 9-slice margins L{} T{} R{} B{}".format(*margins))
        else:
            notes.append("hollow center skipped (the interior isn't closed off or isn't flat; edit the prompt or cut it by hand)")
    return img, notes


def export_sizes(img, master_path: str, sizes: list[int], pixel: bool) -> list[str]:
    from PIL import Image

    base = square_on_canvas(img) if img.mode == "RGBA" else img
    if base.width != base.height:
        side = min(base.width, base.height)
        base = cover_resize(base, side, side)
    stem, _ = os.path.splitext(master_path)
    out_dir = f"{stem}_sizes"
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for n in sizes:
        p = os.path.join(out_dir, f"{os.path.basename(stem)}_{n}x{n}.png")
        base.resize((n, n), Image.Resampling.NEAREST if pixel else Image.Resampling.LANCZOS).save(p, "PNG", optimize=True)
        paths.append(p)
    ico = [n for n in sizes if n <= 256]
    if ico:  # Windows / favicon bundle of the small sizes
        ico_p = os.path.join(out_dir, f"{os.path.basename(stem)}.ico")
        base.convert("RGBA").save(ico_p, sizes=[(n, n) for n in ico])
        paths.append(ico_p)
    return paths


def main(argv=None) -> int:
    args = parse_args(argv)
    mult = 16 if ASSET_MODELS[args.model]["engine"] in ("klein", "qwen") else 8
    if args.width % mult or args.height % mult:
        raise SystemExit(f"width and height must be multiples of {mult} for {args.model}")
    sys.argv = [sys.argv[0], "--reserve-vram", "0.6"]
    if COMFY_DIR not in sys.path:
        sys.path.insert(0, COMFY_DIR)
    out_path = os.path.abspath(args.output)
    os.chdir(COMFY_DIR)
    import comfy.options
    comfy.options.enable_args_parsing()

    if not model_installed(args.model):
        missing = [f for f in model_files(args.model) if not os.path.isfile(os.path.join(COMFY_DIR, "models", f))]
        raise SystemExit(f"Error: {args.model} is missing {', '.join(missing)} (start_graphical_studio.sh --model-sync --assets)")

    t0 = time.time()
    img = render(args)
    img, notes = postprocess(img, args)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    if out_path.lower().endswith((".jpg", ".jpeg")):
        img.convert("RGB").save(out_path, "JPEG", quality=94, optimize=True)
    else:
        img.save(out_path, "PNG", optimize=True)
    print(f"[Asset {args.model}] Saved {out_path} ({img.width}x{img.height}{', ' + ', '.join(notes) if notes else ''})", flush=True)

    extra = []
    sizes = sorted({int(s) for s in args.export_sizes.replace(" ", "").split(",") if s.isdigit() and 8 <= int(s) <= 2048})
    if sizes:
        extra = export_sizes(img, out_path, sizes, pixel=bool(args.pixelate))
        print(f"[Asset {args.model}] Exported {len(extra)} size(s) to {os.path.dirname(extra[0])}", flush=True)
    print("ASSET_RESULT=" + json.dumps({"output": out_path, "exports": extra, "width": img.width, "height": img.height,
                                       "seconds": round(time.time() - t0, 1), "notes": notes,
                                       "slice_margins": getattr(args, "slice_margins", None)}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
