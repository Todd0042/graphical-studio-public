#!/usr/bin/env python3
"""Cut the subject out of an image: transparent background, cropped to the subject.

    .venv/bin/python cutout.py --input photo.png --output subject.png [--model general|anime|portrait]

general  = BiRefNet (best all-round edges: hair, hands, soft outlines)
anime    = ISNet anime (made for anime / illustrated characters)
portrait = BiRefNet portrait (people photos)

Runs on the CPU (onnxruntime), so it never needs a GPU turn. Prints one JSON line: {"width", "height"}.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("U2NET_HOME", os.path.join(ROOT_DIR, ".cache", "rembg"))
MODELS = {"general": "birefnet-general", "anime": "isnet-anime", "portrait": "birefnet-portrait"}


def cut_out(src: str, dst: str, model: str = "general", pad: int = 4) -> tuple[int, int]:
    from PIL import Image
    from rembg import new_session, remove

    Image.MAX_IMAGE_PIXELS = 40_000_000
    with Image.open(src) as im:
        im = im.convert("RGBA")
    out = remove(im, session=new_session(MODELS[model]))
    bbox = out.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    if bbox:  # crop to the subject so dragging and scaling work on the subject, not empty space
        l, t, r, b = bbox
        out = out.crop((max(0, l - pad), max(0, t - pad), min(out.width, r + pad), min(out.height, b + pad)))
    out.save(dst, "PNG")
    return out.width, out.height


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--model", choices=sorted(MODELS), default="general")
    args = ap.parse_args()
    w, h = cut_out(args.input, args.output, args.model)
    print(json.dumps({"width": w, "height": h}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
