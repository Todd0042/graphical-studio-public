#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

echo "=== 1. Cloning ComfyUI (if missing) ==="
if [[ ! -d "$ROOT_DIR/ComfyUI" ]]; then
  git clone https://github.com/comfyanonymous/ComfyUI.git "$ROOT_DIR/ComfyUI"
fi

echo "=== 2. Setting up Python .venv ==="
if [[ ! -d "$ROOT_DIR/.venv" ]]; then
  python3 -m venv "$ROOT_DIR/.venv"
fi
"$ROOT_DIR/.venv/bin/pip" install --upgrade pip
"$ROOT_DIR/.venv/bin/pip" install -r "$ROOT_DIR/ComfyUI/requirements.txt"
"$ROOT_DIR/.venv/bin/pip" install huggingface_hub hf_transfer pillow numpy rembg onnxruntime

echo "=== 3. Downloading the image models in models.json ==="
"$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/studio_models.py" --model-sync || true

echo "=== 4. Pulling the LLMs in models.json ==="
"$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/studio_models.py" --llm-sync --all || \
  echo "Start Ollama, then run: $ROOT_DIR/start_graphical_studio.sh --llm-sync --all"

echo ""
echo "Setup complete! Run $ROOT_DIR/start_graphical_studio.sh --models-check to see if any manual checkpoints are needed."
echo "Launch UI: $ROOT_DIR/start_graphical_studio.sh"
