<p align="center">
  <a href="https://ko-fi.com/todd0042">
    <img src="https://raw.githubusercontent.com/Todd0042/creator-assets/main/banners/todd_creator_banner_v1.0.png" alt="Support Todd on Ko-fi" width="100%" />
  </a>
</p>

---

# 🎨 Graphical Studio

[![License: PolyForm Noncommercial](https://img.shields.io/badge/License-PolyForm%20Noncommercial%201.0.0-00f0ff.svg)](LICENSE)
[![Content: SFW-Leaning Models](https://img.shields.io/badge/Content-Image%20Only%20%26%20SFW--Leaning-2ea44f.svg)](#models--safety-scope)
[![Platform: Linux](https://img.shields.io/badge/Platform-Linux-orange.svg)](#quick-start)
[![Desktop: Python Tkinter](https://img.shields.io/badge/Desktop-Tkinter%20%2B%20ComfyUI-8a6cff.svg)](#1-desktop-app-studio_guipy)
[![Web: FastAPI](https://img.shields.io/badge/Web-FastAPI%20%2B%20Compose-teal.svg)](#2-web-generator-web)
[![Support on Ko-fi](https://img.shields.io/badge/Ko--fi-Support%20Creator-F16061?style=flat&logo=ko-fi&logoColor=white)](https://ko-fi.com/todd0042)

> **A local AI image and game-asset studio powered by ComfyUI (`FLUX` and `Qwen-Image`) and local Ollama instruct LLMs — with both a Tkinter desktop app and a login-gated FastAPI web wrapper, structured Prompt Builder with conflict rectification, Asset Studio (icons, backgrounds, textures, sprites), and browser-based layer Compose.**

> **Image generation with safety-minded models:** Graphical Studio generates **images only** and ships **SFW-leaning models** (`FLUX.2 klein 4B`, `FLUX.1 dev`, `FLUX.1 schnell`, `Qwen-Image 20B`) alongside **safety-aligned local instruct LLMs** (`Llama 3.1`, `Gemma 3`, `Qwen 3`, `Qwen 2.5 Coder`), with SFW prompt catalogs and presets. **No generative model is guaranteed safe** — you remain responsible for reviewing generated outputs and complying with applicable laws and platform rules.

---

## 📖 Table of Contents

* **Part 1 — Overview & Quick Start**
  * [🧠 What Is Graphical Studio?](#-what-is-graphical-studio)
  * [✨ Highlights at a Glance](#-highlights-at-a-glance)
  * [🛡️ Models & Safety Scope](#models--safety-scope)
  * [🚀 Quick Start](#-quick-start)
* **Part 2 — Technical Documentation & Architecture Reference**
  * [1. Desktop App (`studio_gui.py`, `studio_photo_tab.py`, `studio_assets_tab.py`)](#1-desktop-app-studio_guipy)
  * [2. Web Generator & Compose (`web/`)](#2-web-generator-web)
  * [3. Prompt Builder, Conflict Rectifier & Vibe Fill](#3-prompt-builder-conflict-rectifier--vibe-fill)
  * [4. Asset Studio Engine (`studio_assets.py`, `generate_asset.py`)](#4-asset-studio-engine)
  * [5. Model Sync (`models.json`, `studio_models.py`)](#5-model-sync-modelsjson-studio_modelspy)
  * [6. Testing, Security & Licensing (`tests/`, `SECURITY.md`, `LICENSE`)](#6-testing-security--licensing)

---

# Part 1 — Overview & Quick Start

## 🧠 What Is Graphical Studio?

**Graphical Studio** gives you one unified workspace for local image and game-asset workflows on 8 GB+ NVIDIA GPUs (powered by ComfyUI under the hood) paired with local Ollama instruct LLMs for prompt assistance:

1. **🖼️ Photos & Images (`FLUX` / `Qwen-Image`)**: Generate portraits, illustrations, and scenes with `FLUX.2 klein 4B` (fast 4-step default), `FLUX.1 dev`, `FLUX.1 schnell`, or `Qwen-Image 20B` (for typography and complex layouts), plus Character Profiles (`studio_profiles.py`) and library recipes.
2. **✨ Asset Studio**: One-line brief expansion into structured fields for app icons (with multi-size PNG + `.ico` export and 9-slice frame hollowing), wallpapers/backgrounds, material textures, pixel-grid sprites, and transparent cutout assets.
3. **🧩 Prompt Builder & Web Compose**: Structured orthogonal dropdowns with deterministic conflict rectification, optional local LLM reconciliation, and a browser layer composer with CPU background removal (`rembg`).

---

## ✨ Highlights at a Glance

* **⚖️ Orthogonal Prompt Builder + Deterministic Rectifier**: Pick traits across Theme, Person, and Scene & Attire dropdowns without categories bleeding into each other; `studio_rectifier.py` resolves contradictions deterministically (with custom text always taking precedence).
* **🤖 Local Instruct LLM Assistance**: Optional Ollama integration (`llama3.1:8b`, `gemma3:4b`, `qwen3:8b`, `qwen2.5-coder:7b`) expands briefs, fills dropdowns from a short vision, or reconciles dropdowns against custom text—while respecting safety-aligned model refusals.
* **🎨 Browser Compose Canvas**: Drag gallery images onto a canvas, remove backgrounds locally on the CPU (BiRefNet / ISNet via `rembg`), snap to thirds/center, adjust edge fades and gradients, and save flattened PNGs straight back to the gallery.
* **📚 Shared Library (`outputs/library.db`)**: Every desktop and web generation stores its recipe (prompt, builder state, settings, seed) so **Import into Prompt Builder** restores it in one click.
* **🔄 Multi-Machine Model Sync (`models.json`)**: Sync ComfyUI GGUF/VAE weights, `ComfyUI-GGUF`, and Ollama instruct LLMs across desktop and laptop with `--model-sync` and `--llm-sync`.

---

## Models & Safety Scope

Graphical Studio is built for image generation with safety-minded defaults:

* **Image & Asset Models**: Ships strictly SFW-leaning open models (`FLUX.2-klein-4B`, `FLUX.1-dev`, `FLUX.1-schnell`, and `Qwen-Image 20B` with GGUF Q4/Q8 weights via `ComfyUI-GGUF`).
* **Local LLMs (Ollama)**: Allow-listed safety-aligned instruct models (`llama3.1:8b` default, `gemma3:4b`, `qwen3:8b`, and `qwen2.5-coder:7b`). If an instruct model refuses a prompt, the refusal is surfaced directly rather than bypassed.
* **Important Safety Disclaimer**: **No model is guaranteed safe.** Even SFW-leaning diffusion models and safety-aligned LLMs can occasionally produce unexpected, inaccurate, or unsuitable outputs depending on prompts and seeds. Always review outputs before sharing or publishing.
* **Clean Catalogs & UI**: All built-in builder options, presets, and UI controls are SFW and image-focused.

---

## 🚀 Quick Start

### Desktop App (Linux + NVIDIA GPU)

```bash
git clone https://github.com/Todd0042/graphical-studio-public.git
cd graphical-studio-public

chmod +x setup_laptop.sh start_graphical_studio.sh
./setup_laptop.sh
```

`setup_laptop.sh` clones ComfyUI, creates `.venv`, installs `ComfyUI-GGUF` + `rembg`, downloads the core `FLUX` and `Qwen-Image` assets from `models.json`, and pulls the Ollama instruct LLMs (start Ollama first, or run `./start_graphical_studio.sh --llm-sync` afterwards).

Launch the desktop GUI:

```bash
./start_graphical_studio.sh
# Or lower CPU/I/O priority while working on other tasks:
./start_graphical_studio.sh --low-impact
```

Sync image models, launch ComfyUI manually, or check installation status:

```bash
./start_graphical_studio.sh --models-check
./start_graphical_studio.sh --model-sync --assets
./start_comfyui.sh
```

### Web Wrapper (Optional)

```bash
python3 -m venv .venv-web
.venv-web/bin/pip install fastapi uvicorn httpx pillow python-multipart

cp web/.env.example web/.env
# Edit web/.env with your allowed host, SSO settings, and GS_WEB_SESSION_SECRET

.venv-web/bin/uvicorn web.server:create_app --factory --host 127.0.0.1 --port 8040
```

See [deploy/graphical-studio-web.service.example](deploy/graphical-studio-web.service.example) for a sample user systemd service unit.

---

# Part 2 — Technical Documentation & Architecture Reference

## 1. Desktop App (`studio_gui.py`)

* [studio_gui.py](studio_gui.py): Main Tkinter notebook (**Photos & Images**, **Asset Studio**, **Themes & Menu**), DPI scaling (`studio_dpi.py`), and theme palette (`studio_themes.py`).
* [studio_photo_tab.py](studio_photo_tab.py): Image generation controls (`FLUX.2 klein`, `FLUX.1 dev`, `FLUX.1 schnell`, `Qwen-Image`), Character Profiles (`studio_profiles.py`), and output gallery.
* [studio_assets_tab.py](studio_assets_tab.py): Asset Studio front end with repo-scanning support, live field editor, analysis reasons, pixel-grid snapping, and multi-size icon export helpers.
* [studio_builder_dialog.py](studio_builder_dialog.py): Full Scene & Person Prompt Builder window + quick-pick bar, template manager (`studio_templates.py`), live rectifier preview, and LLM reconcile/fill.

## 2. Web Generator (`web/`)

* [web/server.py](web/server.py): Login-gated FastAPI application serving `web/static/index.html`, `app.js`, `compose.js`, REST image job APIs, gallery recipes, and upload handling.
* [web/config.py](web/config.py) & [web/.env.example](web/.env.example): Configuration loader (`GS_WEB_*` environment variables override `web/.env`).
* [web/sso.py](web/sso.py) & [web/auth.py](web/auth.py): Single-owner HMAC-SHA256 one-time ticket verification and signed session cookies (`gs_session`).
* [web/specs.py](web/specs.py) & [web/jobs.py](web/jobs.py): Allow-list request validation, `argv`-only subprocess construction, and serial background job runner.
* [web/compose.py](web/compose.py) & [cutout.py](cutout.py): CPU `rembg` background-removal endpoints for the Compose canvas.

## 3. Prompt Builder, Conflict Rectifier & Vibe Fill

* [studio_prompt_catalog.py](studio_prompt_catalog.py): Orthogonal field definitions (`THEME_FIELDS`, `PERSON_FIELDS`, `SCENE_ATTIRE_FIELDS`), prompt assembler, and reverse prompt-to-dropdown matcher (`ascertain_fields_from_prompt`).
* [studio_rectifier.py](studio_rectifier.py): Domain-weighted deterministic conflict resolution (`CONFLICT_GROUPS`) plus optional safety-aligned Ollama instruct LLM refinement (`run_prompt_llm_checked`).
* [studio_reconcile.py](studio_reconcile.py) & [studio_vibe.py](studio_vibe.py): Reconciles dropdown selections against custom vision text and fills empty dropdowns from a short text description (with offline keyword vibe profiles as fallback when Ollama is offline).
* [studio_compat.py](studio_compat.py) & [studio_presets.py](studio_presets.py): Intent analysis, preset sizing/steps recommendations, style negatives, and partial look presets.

## 4. Asset Studio Engine

* [studio_assets.py](studio_assets.py) & [generate_asset.py](generate_asset.py): Automatically selects between `FLUX.2 klein 4B`, `FLUX.1 dev/schnell`, and `Qwen-Image 20B` (for lettering and complex prompts), with optional pixel-grid snapping (`--pixelate`), `rembg` transparent cutouts, and multi-size `.png`/`.ico` exports.

## 5. Model Sync (`models.json`, `studio_models.py`)

* [models.json](models.json) & [studio_models.py](studio_models.py): Declarative manifest for Ollama instruct LLMs and Hugging Face ComfyUI model weights (`FLUX.1`, `FLUX.2 klein`, `Qwen-Image`) and `ComfyUI-GGUF`. Supports `--models-check`, `--model-sync`, `--llm-sync`, and `--llm-pin`.

## 6. Testing, Security & Licensing

* [tests/test_core.py](tests/test_core.py): Verifies SFW-leaning image-only defaults, catalog/preset cleanliness, LLM refusal handling, and FastAPI web authentication, CSRF protection, options, builder preview, and job validation. Run locally with:

```bash
.venv-web/bin/python tests/test_core.py
```

* [SECURITY.md](SECURITY.md): Security architecture and private vulnerability reporting instructions.
* [LICENSE](LICENSE): **PolyForm Noncommercial 1.0.0**.
