#!/usr/bin/env python3
"""Core (image-only, no extras/) functional and web E2E test suite.

When executed from the private repo (where extras/ is present), this script stages a clean copy
without extras/ or private scripts into a temporary directory and re-runs itself cleanly.
In the exported repo (or CI), it runs directly.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parent.parent


def _private_only() -> list[str]:
    """Files the export leaves out, read from bin/export-public when it exists (it only exists where optional
    extensions are installed); the test then runs against the same file set that gets published."""
    script = ROOT_DIR / "bin" / "export-public"
    if not script.is_file():
        return ["extras"]
    import re as _re
    block = _re.search(r"PRIVATE_ONLY=\((.*?)\)", script.read_text(encoding="utf-8"), _re.S)
    names = block.group(1).split() if block else []
    return sorted({Path(n).name for n in names if not n.startswith("#")} | {"extras"})


def _run_staged_without_addons() -> int:
    with tempfile.TemporaryDirectory(prefix="gs_public_test_") as tmp:
        stage = Path(tmp) / "repo"
        ignore = shutil.ignore_patterns(
            ".git", ".venv", ".venv-web", ".cache", "outputs", "ComfyUI", "__pycache__", "*.pyc", *_private_only(),
        )
        shutil.copytree(ROOT_DIR, stage, ignore=ignore)
        env = {**os.environ, "GS_PUBLIC_TEST_STAGED": "1", "PYTHONPATH": str(stage)}
        res = subprocess.run([sys.executable, str(stage / "tests" / "test_core.py")], cwd=stage, env=env)
        return res.returncode


def _mint_ticket(secret_bytes: bytes, site: str, user: str) -> str:
    payload = {"u": user, "aud": site, "exp": int(time.time()) + 60, "n": secrets.token_hex(8)}
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(secret_bytes, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def run_tests() -> None:
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))

    import addons
    import generate_asset
    import studio_assets
    import studio_compat
    import studio_helpers
    import studio_models
    import studio_presets
    import studio_prompt_catalog
    import studio_reconcile
    import studio_rectifier
    import studio_tooltips
    import studio_vibe

    assert not addons.is_addon_enabled(), "Core must run without optional private extensions"
    assert not (ROOT_DIR / ("gpu_" + "policy.py")).exists()
    assert not (ROOT_DIR / ("gpu_" + "turn.py")).exists()
    assert not (ROOT_DIR / ("start_comfyui_" + "5060" + "ti.sh")).exists()
    assert not list(ROOT_DIR.glob("wa" + "n_*.py"))
    assert addons.web_status() is None
    assert addons.desktop_status_label() is None
    with addons.execution_session("test") as direct:
        assert direct.held is True

    # 1. Models & checkpoints: FLUX + Qwen-Image only (no excluded video/legacy checkpoints), aligned LLMs only
    assert [d["name"] for d in studio_models.prompt_llms()] == ["llama3.1:8b", "gemma3:4b", "qwen3:8b"]
    assert studio_models.default_prompt_llm() == "llama3.1:8b"
    groups = studio_models.file_groups()
    assert list(groups.keys()) == ["assets"], f"Unexpected manifest file groups: {list(groups.keys())}"
    asset_dests = [item["dest"] for item in groups["assets"]]
    assert len(asset_dests) == 12
    assert any("flux-2-klein" in d for d in asset_dests)
    assert any("qwen-image" in d for d in asset_dests)
    setup = studio_models.manifest()["setup"]
    assert list(setup.keys()) == ["assets"]
    assert [n["name"] for n in setup["assets"]["custom_nodes"]] == ["ComfyUI-GGUF"]
    assert setup["assets"]["pip"] == ["gguf>=0.13.0", "rembg"]

    # Video CLI flag must not exist in core
    try:
        studio_models.main(["--wa" + "n14b"])
        raise AssertionError("Expected unrecognized argument exit")
    except SystemExit as exc:
        assert exc.code != 0

    assert [k for k, _ in studio_helpers.get_photo_model_options()] == [
        "flux2_klein", "flux_dev", "flux_schnell", "qwen_image"
    ]
    assert set(generate_asset.ASSET_MODELS) == {"flux_dev", "flux_schnell", "flux2_klein", "qwen_image"}
    cmd = studio_helpers.build_photo_cli_command({"model": "flux2_klein", "prompt": "sunny forest"})
    assert cmd[1].endswith("generate_asset.py") and "--model" in cmd and "flux2_klein" in cmd

    # 2. Catalog, presets, tooltips: SFW-only, no rating/video motion fields
    assert "rating" not in studio_prompt_catalog.FIELD_BY_KEY
    attire_opts = studio_prompt_catalog.FIELD_BY_KEY["attire"][3]
    assert len(attire_opts) == 15
    assert studio_prompt_catalog.MOTION_FIELDS == []
    assert len(studio_prompt_catalog.ALL_GROUPS) == 3
    assert len(studio_presets.PRESETS) == 11
    assert "select_file" in studio_tooltips.TOOLTIPS
    assert "model_video" not in studio_tooltips.TOOLTIPS
    assert "rating" not in studio_tooltips.TOOLTIPS
    assert ("anti_" + "zoom_neg") not in studio_tooltips.TOOLTIPS

    # 3. Compat & asset selection (FLUX / Qwen-Image only)
    intent = studio_compat.analyze_builder_intent({"style": "Anime Visual Novel: anime", "framing": "Upper Body (Waist-Up)"})
    assert studio_compat.best_photo_model(intent) == "flux2_klein"
    assert studio_assets._choose_model_base("texture", {"style": "Photoreal PBR albedo"}, "brick")[0] == "flux_dev"
    assert studio_assets._choose_model_base("icon", {"style": "Pixel art"}, "sword")[0] == "flux_dev"

    # 4. Asset Studio LLM allow-list enforcement & safety refusal surfacing
    with patch("studio_models.ollama_installed", return_value={"unlisted_custom:8b": "aaa", "qwen3:8b": "bbb"}):
        assert studio_assets.installed_llms() == ["qwen3:8b"]
        picked, _ = studio_assets.pick_llm()
        assert picked == "qwen3:8b"
    with patch("studio_models.ollama_installed", return_value={"unlisted_custom:8b": "aaa"}):
        assert studio_assets.installed_llms() == []
        picked_none, _ = studio_assets.pick_llm()
        assert picked_none is None

    with patch("studio_models.ollama_installed", return_value={"qwen3:8b": "bbb"}), \
         patch("studio_assets._ollama_chat", return_value="I cannot fulfill this request due to safety policies."):
        exp_ref = studio_assets.expand_brief("weather app icon", kind="icon", use_llm=True)
        assert exp_ref.get("refused") is True and exp_ref["fields"] == {}
        ana_ref = studio_assets.analyze("icon", {"subject": "cloud"}, concept="cloud icon", use_llm=True)
        assert ana_ref.get("refused") is True and ana_ref["prompt"] == ""

    # 5. Builder / Vibe safety-aligned LLM refusal handling
    with patch("studio_models.ollama_installed", return_value={"llama3.1:8b": "abc"}), \
         patch("studio_rectifier._try_ollama_instruct", return_value=(None, "llama3.1:8b refused the request.", True)):
        rec = studio_reconcile.reconcile_builder(
            {"style": "American Realistic Photo: RAW candid photo", "scene": "Artisan Coffee Shop: cafe"},
            "test request",
            include_motion=False,
            use_llm=True,
            model="llama3.1:8b",
        )
        assert rec.get("refused") is True and rec["prompt"] == ""
        filled, notes = studio_vibe.fill_from_vision({}, "test vision", use_llm=True, model="llama3.1:8b")
        assert filled == {} and any("refused" in n.lower() for n in notes)

    # 6. Web FastAPI E2E (auth gate, CSRF, image-only options, video disabled, live uvicorn)
    from fastapi.testclient import TestClient
    from web.config import load_settings
    from web.server import create_app

    with tempfile.TemporaryDirectory(prefix="gs_web_e2e_") as wtmp:
        wdir = Path(wtmp)
        sso_secret = secrets.token_bytes(32)
        session_secret = secrets.token_hex(32)
        secret_file = wdir / "sso_secret"
        secret_file.write_bytes(sso_secret)
        env_file = wdir / "web.env"
        port = _free_port()
        env_file.write_text(
            f"GS_WEB_ALLOWED_HOSTS=testserver,127.0.0.1:{port},localhost:{port}\n"
            "GS_WEB_ALLOWED_GITHUB_USER=tester\n"
            "GS_WEB_SSO_URL=https://auth.example.com/sso\n"
            "GS_WEB_SSO_SITE=graphical-studio\n"
            f"DEV_SSO_SECRET={secret_file}\n"
            f"GS_WEB_SESSION_SECRET={session_secret}\n"
            f"GS_WEB_JOBS_PATH={wdir / 'jobs.json'}\n"
            f"GS_WEB_UPLOADS_DIR={wdir / 'uploads'}\n",
            encoding="utf-8",
        )
        with patch.dict(os.environ, {"GS_WEB_ENV_FILE": str(env_file), "GS_LIBRARY_DB": str(wdir / "library.db")}):
            app = create_app(load_settings())
            with TestClient(app) as client:
                r_root = client.get("/", follow_redirects=False)
                assert r_root.status_code == 303 and r_root.headers["location"].startswith("/login")
                assert client.get("/api/options").status_code == 401

                ticket = _mint_ticket(sso_secret, "graphical-studio", "tester")
                r_sso = client.get(f"/auth/sso?ticket={ticket}&next=/", follow_redirects=False)
                assert r_sso.status_code == 303 and "gs_session" in client.cookies

                html = client.get("/").text
                assert 'id="llm-select"' in html and "Reconcile prompt" in html
                assert "Reconcile with" not in html
                for forbidden_id in ("video-form", "video-ref", "gpu-pill", "/static/ext/", "builder-target"):
                    assert forbidden_id not in html, f"Unexpected private UI element in core HTML: {forbidden_id}"

                app_js = client.get("/static/app.js").text
                assert ("tw" + "in") not in app_js

                opts = client.get("/api/options").json()
                assert set(opts.keys()) == {"photo", "assets", "builder", "llms", "ui", "app_labels", "presets"}
                assert "video" not in opts and "features" not in opts
                assert [m["key"] for m in opts["photo"]["models"]] == [
                    "flux2_klein", "flux_dev", "flux_schnell", "qwen_image"
                ]
                assert len(opts["builder"]) == 3 and all("motion" not in g["group"].lower() for g in opts["builder"])
                assert [d["name"] for d in opts["llms"]] == ["llama3.1:8b", "gemma3:4b", "qwen3:8b"]
                assert opts["app_labels"] == {"graphical_studio": "Graphical Studio"}
                st = client.get("/api/status").json()
                assert set(st.keys()) == {"queue"}

                assert client.post("/api/builder/preview", json={"target": "photo", "values": {}}).status_code == 403
                prev = client.post(
                    "/api/builder/preview",
                    headers={"X-GS-CSRF": "1"},
                    json={
                        "target": "photo",
                        "vision": "sunny cafe",
                        "values": {
                            "style": studio_prompt_catalog.FIELD_BY_KEY["style"][3][1],
                            "gender": studio_prompt_catalog.FIELD_BY_KEY["gender"][3][1],
                        },
                    },
                )
                assert prev.status_code == 200 and "sunny cafe" in prev.json()["prompt"]

                # Video / pair endpoints and targets disabled in core
                assert client.post("/api/builder/preview", headers={"X-GS-CSRF": "1"}, json={"target": "video", "values": {}}).status_code == 400
                assert client.post("/api/jobs/video", headers={"X-GS-CSRF": "1"}, json={"prompt": "test"}).status_code == 404
                assert client.get("/api/media?kind=video").status_code == 400

                r_twin = client.post("/api/media/" + "pa" + "ir", headers={"X-GS-CSRF": "1"}, json={"rel": "x.jpg"})
                assert r_twin.status_code in (404, 405)
                assert not any(getattr(rt, "path", "").endswith("/" + "pa" + "ir") for rt in app.routes)

                # Disallowed photo model rejected; core flux2_klein accepted
                bad_job = client.post(
                    "/api/jobs/photo",
                    headers={"X-GS-CSRF": "1"},
                    json={"model": "unsupported_model", "prompt": "sunny forest"},
                )
                assert bad_job.status_code == 400

                hold = threading.Event()
                with patch("web.jobs.JobQueue._execute", side_effect=lambda _job: hold.wait(5.0)):
                    ok_job = client.post(
                        "/api/jobs/photo",
                        headers={"X-GS-CSRF": "1"},
                        json={
                            "model": "flux2_klein",
                            "prompt": "sunny forest path in morning light",
                            "steps": 4,
                            "cfg": 1.0,
                            "sampler": "euler",
                            "scheduler": "simple",
                        },
                    )
                    assert ok_job.status_code == 201
                    jid = ok_job.json()["id"]
                    assert client.post(f"/api/jobs/{jid}/cancel", headers={"X-GS-CSRF": "1"}).json()["cancelled"] is True
                    hold.set()

            # Asset Studio on the web: brief -> plan (offline, no LLM installed) -> edit -> generate (a stand-in
            # renderer writes the image and its icon size exports) -> gallery "Assets" -> sizes zip.
            import io
            import zipfile

            import studio_assets
            import studio_library
            import web.server as web_server

            png = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                                "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")
            fake_render = (
                "import os, sys\n"
                "out = sys.argv[1]; os.makedirs(os.path.dirname(out), exist_ok=True)\n"
                f"data = bytes.fromhex({png.hex()!r})\n"
                "open(out, 'wb').write(data)\n"
                "sizes = os.path.splitext(out)[0] + '_sizes'; os.makedirs(sizes, exist_ok=True)\n"
                "stem = os.path.basename(os.path.splitext(out)[0])\n"
                "for n in (16, 32): open(os.path.join(sizes, f'{stem}_{n}x{n}.png'), 'wb').write(data)\n"
                "open(os.path.join(sizes, stem + '.ico'), 'wb').write(b'ico')\n"
                "print('ASSET_RESULT={}')\n"
            )
            asset_root = wdir / "outputs"
            with TestClient(create_app(load_settings())) as client, \
                 patch.dict(os.environ, {"GS_WEB_ENV_FILE": str(env_file), "GS_LIBRARY_DB": str(wdir / "asset_library.db")}), \
                 patch("studio_models.ollama_installed", return_value={}), \
                 patch.object(studio_assets, "ASSETS_DIR", str(asset_root / "assets")), \
                 patch.object(studio_library, "OUTPUTS_DIR", str(asset_root)), \
                 patch.object(web_server, "OUTPUTS_DIR", str(asset_root)), \
                 patch.object(studio_assets, "build_command", lambda plan, out: [sys.executable, "-c", fake_render, out]):
                client.get(f"/auth/sso?ticket={_mint_ticket(sso_secret, 'graphical-studio', 'tester')}&next=/",
                           follow_redirects=False)
                csrf = {"X-GS-CSRF": "1"}

                def wait(jid):
                    for _ in range(200):
                        j = client.get(f"/api/jobs/{jid}").json()
                        if j["status"] not in ("queued", "waiting_gpu", "running"):
                            return j
                        time.sleep(0.05)
                    raise AssertionError(f"job {jid} never finished")

                opts = client.get("/api/options").json()["assets"]
                assert {k["key"] for k in opts["kinds"]} >= {"icon", "background"} and opts["models"]
                html = client.get("/").text
                assert 'id="asset-form"' in html and 'data-kind="asset"' in html

                # Refused before anything runs: no brief; no plan; unknown kind/model; not signed in.
                assert client.post("/api/jobs/asset_plan", headers=csrf, json={"brief": " "}).status_code == 400
                assert client.post("/api/jobs/asset", headers=csrf, json={}).status_code == 400
                bad = {"kind": "spaceship", "model": "flux_dev", "prompt": "x"}
                assert client.post("/api/jobs/asset", headers=csrf, json={"plan": bad}).status_code == 400
                bad = {"kind": "icon", "model": "not-a-model", "prompt": "x"}
                assert client.post("/api/jobs/asset", headers=csrf, json={"plan": bad}).status_code == 400

                job = client.post("/api/jobs/asset_plan", headers=csrf,
                                  json={"brief": "app icon for a budgeting app, friendly piggy bank, flat, teal",
                                        "asset_kind": "auto"}).json()
                planned = wait(job["id"])
                assert planned["status"] == "done", planned
                r = planned["result"]
                assert r["kind"] == "icon" and r["fields"] and r["plan"]["prompt"], r
                assert r["plan"]["model"] in studio_assets.ASSET_MODELS

                plan = dict(r["plan"], kind=r["kind"], title=r["title"], export_sizes="16,32", steps=4)
                gen = client.post("/api/jobs/asset", headers=csrf, json={"plan": plan})
                assert gen.status_code == 201, gen.text
                done = wait(gen.json()["id"])
                assert done["status"] == "done" and done["outputs"], done

                items = client.get("/api/media?kind=asset").json()["items"]
                assert len(items) == 1 and items[0]["kind"] == "asset", items  # the size exports aren't listed
                assert not any(i["rel"].startswith("assets/") for i in client.get("/api/media?kind=photo").json()["items"])
                z = client.get("/api/media/exports", params={"rel": items[0]["rel"]})
                assert z.status_code == 200 and z.headers["content-type"] == "application/zip"
                names = sorted(zipfile.ZipFile(io.BytesIO(z.content)).namelist())
                assert len(names) == 3 and names[0].endswith(".ico") and any(n.endswith("_16x16.png") for n in names)
                assert client.get("/api/media/exports", params={"rel": "../../etc/passwd"}).status_code == 404

            # Live isolated uvicorn HTTP check on ephemeral port (never touches 8040)
            import urllib.request

            proc = subprocess.Popen(
                [
                    sys.executable, "-m", "uvicorn", "web.server:create_app", "--factory",
                    "--host", "127.0.0.1", "--port", str(port), "--no-access-log",
                ],
                cwd=ROOT_DIR,
                env={**os.environ, "GS_WEB_ENV_FILE": str(env_file), "GS_LIBRARY_DB": str(wdir / "live_library.db")},
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            try:
                deadline = time.time() + 10.0
                health = None
                while time.time() < deadline:
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.0) as resp:
                            health = json.loads(resp.read())
                            break
                    except Exception:
                        time.sleep(0.15)
                assert health == {"ok": True, "service": "graphical-studio-web"}, f"Live health failed: {health}"
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/signed-out", timeout=2.0) as resp:
                    signed_out_html = resp.read().decode("utf-8")
                assert "Sign in with GitHub" in signed_out_html
            finally:
                proc.terminate()
                proc.wait(timeout=5)

    print("CORE TESTS PASSED!")


if __name__ == "__main__":
    if (ROOT_DIR / "extras").is_dir() and not os.environ.get("GS_PUBLIC_TEST_STAGED"):
        sys.exit(_run_staged_without_addons())
    run_tests()
