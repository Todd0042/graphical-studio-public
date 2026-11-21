#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$ROOT_DIR/.cache/tmp"
export UV_CACHE_DIR="$ROOT_DIR/.cache/uv"
export HF_HOME="$ROOT_DIR/.cache/huggingface"
export TORCH_HOME="$ROOT_DIR/.cache/torch"
export TMPDIR="$ROOT_DIR/.cache/tmp"
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

cd "$ROOT_DIR/ComfyUI"
exec "$ROOT_DIR/.venv/bin/python" main.py \
  --listen 127.0.0.1 \
  --port 8188 \
  --fp8_e4m3fn-unet \
  --fp8_e4m3fn-text-enc \
  --reserve-vram 0.6 \
  "$@"
