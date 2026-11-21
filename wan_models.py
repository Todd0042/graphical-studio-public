"""models.json: the list of every model Graphical Studio uses, kept in sync across computers.

Other computers pull it with git and then:
    start_graphical_studio.sh --llm-sync [--all] [--update]   # Ollama LLMs: pull missing (--all: extras too)
    start_graphical_studio.sh --model-sync                    # ComfyUI model files
    start_graphical_studio.sh --models-check                  # report only
    start_graphical_studio.sh --llm-pin                       # record installed digests in the list
Nothing is ever removed; a different build is only replaced with --update.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from functools import lru_cache

import addons

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(ROOT_DIR, "models.json")
MODELS_DIR = os.path.join(ROOT_DIR, "ComfyUI", "models")
OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
if not OLLAMA_URL.startswith("http"):
    OLLAMA_URL = "http://" + OLLAMA_URL


@lru_cache(maxsize=1)
def manifest() -> dict:
    with open(MANIFEST, encoding="utf-8") as f:
        return addons.merge_manifest(json.load(f))


# ---- LLMs (Ollama) ---------------------------------------------------------------------------

def prompt_llms() -> list[dict]:
    llms = manifest()["llms"]
    return list(llms.get(addons.REGISTRY.llm_manifest_key) or llms.get("instruct") or [])


def default_prompt_llm() -> str:
    items = prompt_llms()
    return next((d["name"] for d in items if d.get("default")), items[0]["name"])


def ollama_installed(timeout: float = 2.0) -> dict[str, str] | None:
    """{model name (lowercase): digest} from the local Ollama, or None if Ollama isn't running."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=timeout) as resp:
            tags = json.loads(resp.read()).get("models", [])
    except Exception:
        return None
    out = {}
    for m in tags:
        name = str(m.get("name", "")).lower()
        out[name] = str(m.get("digest", ""))
        if name.endswith(":latest"):
            out[name[: -len(":latest")]] = out[name]
    return out


def prompt_llm_options() -> list[dict]:
    """The prompt LLM picker: every listed model with whether it's installed here."""
    have = ollama_installed() or {}
    default = default_prompt_llm()
    return [{"name": d["name"], "label": d["label"], "installed": d["name"].lower() in have,
             "default": d["name"] == default, "caution": bool(d.get("caution")), "note": d.get("note", "")}
            for d in prompt_llms()]


def resolve_prompt_llm(requested: str | None) -> tuple[str | None, str]:
    """The Ollama model to run: strictly allow-listed from models.json (or registered add-on)."""
    if addons.REGISTRY.resolve_llm_override:
        return addons.REGISTRY.resolve_llm_override(requested)
    items = prompt_llms()
    want = (requested or "").strip() or default_prompt_llm()
    if want not in {d["name"] for d in items}:
        want = default_prompt_llm()
    have = ollama_installed()
    if have is None:
        return None, "Ollama isn't running."
    if want.lower() in have:
        return want, ""
    for d in items:
        if d["name"].lower() in have:
            return d["name"], f"{want} isn't installed on this computer, so {d['name']} was used. Run --llm-sync."
    return None, "No listed instruct LLM is installed on this computer. Run start_graphical_studio.sh --llm-sync."


def _pull(name: str) -> bool:
    print(f"[PULL] {name}", flush=True)
    req = urllib.request.Request(f"{OLLAMA_URL}/api/pull", data=json.dumps({"model": name, "stream": True}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    last = ""
    try:
        with urllib.request.urlopen(req, timeout=None) as resp:
            for line in resp:
                ev = json.loads(line or b"{}")
                if ev.get("error"):
                    print(f"[FAIL] {name}: {ev['error']}", flush=True)
                    return False
                status = ev.get("status", "")
                if ev.get("total"):
                    status = f"{status} {100 * ev.get('completed', 0) // ev['total']}%"
                if status != last and not status.endswith(("1%", "3%", "5%", "7%", "9%")):
                    print(f"       {status}", flush=True)
                    last = status
    except Exception as exc:
        print(f"[FAIL] {name}: {exc}", flush=True)
        return False
    return True


def llm_report(include_extras: bool = False) -> list[str]:
    have = ollama_installed()
    if have is None:
        return ["Ollama isn't running, so the LLMs can't be checked."]
    pins = manifest()["llms"].get("digests", {})
    entries = prompt_llms() + (manifest()["llms"]["extras"] if include_extras else [])
    lines = []
    for e in entries:
        name = e["name"]
        if name.lower() not in have:
            lines.append(f"missing: {name}")
        elif pins.get(name) and not have[name.lower()].startswith(pins[name]):
            lines.append(f"different build: {name} (this computer {have[name.lower()][:12]}, list {pins[name]})")
    listed = {e["name"].lower() for e in prompt_llms() + manifest()["llms"]["extras"]}
    hints = addons.REGISTRY.extra_llm_hints
    for name in sorted(have):
        if hints and name not in listed and not name.endswith(":latest") and any(h in name for h in hints):
            lines.append(f"installed but not in the list (not used): {name}")
    return lines


def llm_sync(include_extras: bool = False, update: bool = False) -> int:
    have = ollama_installed()
    if have is None:
        print("Ollama isn't running: start it, then run --llm-sync again.")
        return 1
    pins = manifest()["llms"].get("digests", {})
    entries = prompt_llms() + (manifest()["llms"]["extras"] if include_extras else [])
    failed = 0
    for e in entries:
        name = e["name"]
        installed = name.lower() in have
        stale = installed and pins.get(name) and not have[name.lower()].startswith(pins[name])
        if installed and not stale:
            print(f"[OK  ] {name}")
            continue
        if stale and not update:
            print(f"[DIFF] {name}: a different build is installed (add --update to re-pull it)")
            continue
        failed += not _pull(name)
    for line in llm_report(include_extras):
        if line.startswith("installed but not"):
            print(f"[NOTE] {line}")
    return 1 if failed else 0


def llm_pin() -> int:
    """Record the installed digest of every listed LLM, so other computers match it."""
    have = ollama_installed()
    if have is None:
        print("Ollama isn't running.")
        return 1
    data = json.loads(open(MANIFEST, encoding="utf-8").read())
    key = addons.REGISTRY.llm_manifest_key
    pins = {}
    for e in prompt_llms() + manifest()["llms"]["extras"]:
        digest = have.get(e["name"].lower(), "")
        if digest:
            pins[e["name"]] = digest[:12]
    data["llms"]["digests"] = pins
    if key in data["llms"]:
        with open(MANIFEST + ".tmp", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(MANIFEST + ".tmp", MANIFEST)
    print(f"Pinned {len(pins)} LLM digests in models.json. Commit it so other computers match.")
    return 0


# ---- ComfyUI model files ---------------------------------------------------------------------

def file_groups() -> dict[str, list[dict]]:
    return {k: v for k, v in manifest()["files"].items() if not k.startswith("_")}


def _present(dest: str) -> bool:
    path = os.path.join(MODELS_DIR, dest)
    return os.path.isfile(path) and os.path.getsize(path) > 50_000_000


def files_report(groups: list[str]) -> list[str]:
    lines = []
    for g in groups:
        for e in file_groups().get(g, []):
            if not _present(e["dest"]):
                how = " (copy it over by hand)" if e.get("source") == "manual" else ""
                lines.append(f"missing ({g}): {e['dest']}{how}")
    return lines


def model_sync(groups: list[str]) -> int:
    os.environ.setdefault("HF_HOME", os.path.join(ROOT_DIR, ".cache", "huggingface"))
    os.environ.setdefault("TMPDIR", os.path.join(ROOT_DIR, ".cache", "tmp"))
    os.environ.setdefault("HF_XET_HIGH_PERFORMANCE", "1")
    from huggingface_hub import hf_hub_download

    stage = os.path.join(ROOT_DIR, ".cache", "hf_stage")
    os.makedirs(stage, exist_ok=True)
    missing_manual = 0
    for g in groups:
        for e in file_groups().get(g, []):
            dest = os.path.join(MODELS_DIR, e["dest"])
            if _present(e["dest"]):
                print(f"[OK  ] {e['dest']}")
                continue
            if e.get("source") == "manual":
                print(f"[HAND] {e['dest']}: not downloadable, copy it over from the other computer")
                missing_manual += 1
                continue
            print(f"[GET ] {e['repo']} :: {e['file']} -> {e['dest']}", flush=True)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            fetched = hf_hub_download(repo_id=e["repo"], filename=e["file"], local_dir=stage)
            shutil.move(os.path.realpath(fetched), dest)
            print(f"[DONE] {e['dest']} ({os.path.getsize(dest) / 1e9:.2f} GB)", flush=True)
        _setup_group(g)
    shutil.rmtree(stage, ignore_errors=True)
    return 0 if not missing_manual else 2


def _setup_group(group: str) -> None:
    """Custom nodes and Python packages a model group needs."""
    spec = manifest().get("setup", {}).get(group)
    if not spec:
        return
    for node in spec.get("custom_nodes", []):
        path = os.path.join(ROOT_DIR, "ComfyUI", "custom_nodes", node["name"])
        if not os.path.isdir(path):
            print(f"[NODE] cloning {node['name']}", flush=True)
            subprocess.run(["git", "clone", "--depth", "1", node["git"], path], check=True)
    if spec.get("pip"):
        py = os.path.join(ROOT_DIR, ".venv", "bin", "python")
        uv = shutil.which("uv")
        cmd = ([uv, "pip", "install", "--python", py] if uv else [py, "-m", "pip", "install"]) + spec["pip"]
        print(f"[PIP ] {' '.join(spec['pip'])}", flush=True)
        subprocess.run(cmd, check=True, env={**os.environ, "UV_CACHE_DIR": os.path.join(ROOT_DIR, ".cache", "uv")})


def startup_notice() -> str:
    """One line for the app's status bar; empty when everything listed is here."""
    issues = [ln for ln in llm_report() if not ln.startswith("installed but not")]
    issues += files_report(list(addons.REGISTRY.startup_sync_groups))
    if not issues:
        return ""
    return f"Models out of sync ({len(issues)}): {issues[0]}" + (" ..." if len(issues) > 1 else "") + \
        " -- run start_graphical_studio.sh --llm-sync / --model-sync"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Keep Graphical Studio's models in sync with models.json")
    ap.add_argument("--llm-sync", action="store_true", help="pull missing Ollama LLMs from the list")
    ap.add_argument("--all", action="store_true", help="with --llm-sync: include the optional extras")
    ap.add_argument("--update", action="store_true", help="with --llm-sync: re-pull LLMs whose build differs")
    ap.add_argument("--model-sync", action="store_true", help="download missing ComfyUI model files")
    if addons.REGISTRY.extra_model_cli_args:
        addons.REGISTRY.extra_model_cli_args(ap)
    ap.add_argument("--assets", action="store_true", help="with --model-sync: include Asset Studio models (FLUX, Qwen-Image)")
    ap.add_argument("--models-check", action="store_true", help="report what's missing or different")
    ap.add_argument("--llm-pin", action="store_true", help="record installed LLM digests in models.json")
    args = ap.parse_args(argv)
    rc = 0
    if args.llm_pin:
        rc |= llm_pin()
    if args.llm_sync:
        rc |= llm_sync(include_extras=args.all, update=args.update)
    if args.model_sync:
        groups = list(addons.REGISTRY.default_sync_groups)
        if addons.REGISTRY.extra_model_sync_groups:
            for g in addons.REGISTRY.extra_model_sync_groups(args):
                if g not in groups:
                    groups.append(g)
        if args.assets and "assets" not in groups:
            groups.append("assets")
        rc |= model_sync(groups)
    if args.models_check or not (args.llm_sync or args.model_sync or args.llm_pin):
        lines = llm_report(include_extras=args.all) + files_report(list(addons.REGISTRY.check_sync_groups))
        print("\n".join(lines) or "Everything in models.json is here.")
    return rc


if addons.REGISTRY.attach_models_compat:
    addons.REGISTRY.attach_models_compat(sys.modules[__name__])


if __name__ == "__main__":
    sys.exit(main())
