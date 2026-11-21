#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$ROOT_DIR/.cache/tmp"
export UV_CACHE_DIR="$ROOT_DIR/.cache/uv"
export HF_HOME="$ROOT_DIR/.cache/huggingface"
export TORCH_HOME="$ROOT_DIR/.cache/torch"
export TMPDIR="$ROOT_DIR/.cache/tmp"
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# Prefer system python3 for the Tkinter GUI when it has Xft TrueType fonts + Pillow
# (standalone uv Python builds bundle bitmap-only Tk without Xft scaling).
# AI generation subprocesses still run inside $ROOT_DIR/.venv/bin/python (CUDA venv).
GUI_PYTHON="$ROOT_DIR/.venv/bin/python"
if command -v python3 >/dev/null 2>&1 && python3 -c "import tkinter, PIL, tkinter.font as f; r=tkinter.Tk(); r.withdraw(); ok=len(set(f.families()))>5; r.destroy(); raise SystemExit(0 if ok else 1)" 2>/dev/null; then
  GUI_PYTHON="$(command -v python3)"
fi

# Model sync (models.json): --llm-sync [--all] [--update], --model-sync [--assets], --models-check, --llm-pin.
# These run and exit without opening the app.
if [[ " $* " =~ \ --(llm-sync|model-sync|models-check|llm-pin)\  ]]; then
  exec "$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/studio_models.py" "$@"
fi

if [[ " $* " == *" --low-impact "* ]]; then
  export OMP_NUM_THREADS=4
  export MKL_NUM_THREADS=4
  args=()
  for a in "$@"; do
    [[ "$a" == "--low-impact" ]] || args+=("$a")
  done
  exec nice -n 19 ionice -c 3 "$GUI_PYTHON" "$ROOT_DIR/studio_gui.py" "${args[@]}"
fi

exec "$GUI_PYTHON" "$ROOT_DIR/studio_gui.py" "$@"
