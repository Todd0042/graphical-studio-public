"""Tkinter Asset Studio tab: icons, backgrounds, seamless textures and sprites from a one-line brief.

1 Describe it  -> "Expand Brief": an LLM (or the offline matcher) turns the brief into a concept and fills
                  every field; "Read the repo first" skims a project folder for name, colours and purpose.
2 Fine-tune    -> every field is free text with suggestions; change anything.
3 Analyze      -> picks the image model, settings, post-processing and writes the final prompt (with reasons).
4 Generate     -> generate_asset.py in a GPU turn; the master image, size exports and a recipe .json land in
                  outputs/assets/<kind>/. "Load Recipe" puts a past asset's brief, fields and settings back.
"""

from __future__ import annotations

import json
import os
import queue
import random
import re
import shlex
import threading

import wan_assets as A
import wan_library
from wan_dpi import get_font, register_scale_listener, s
import addons
from wan_studio_helpers import open_path_default, reveal_in_file_manager, start_streaming_process
from wan_tooltips import attach_tooltip

KIND_CHOICES = [("auto", "Auto-detect from brief")] + list(A.KIND_LABELS.items())
LLM_AUTO = "Auto (best installed)"
LLM_OFF = "Off (offline matcher only)"


def scan_assets() -> list[dict]:
    """Master images under outputs/assets (size exports in *_sizes folders are skipped), newest first."""
    from datetime import datetime

    rows = []
    if not os.path.isdir(A.ASSETS_DIR):
        return rows
    for dirpath, dirnames, filenames in os.walk(A.ASSETS_DIR):
        dirnames[:] = [d for d in dirnames if not d.endswith("_sizes")]
        for name in filenames:
            if not name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                continue
            full = os.path.join(dirpath, name)
            st = os.stat(full)
            kb = st.st_size / 1024
            rows.append({"path": full, "name": name, "ts": st.st_mtime,
                         "size": f"{kb / 1024:.2f} MB" if kb >= 1024 else f"{kb:.0f} KB",
                         "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")})
    rows.sort(key=lambda r: r["ts"], reverse=True)
    return rows


def _checker(w: int, h: int, cell: int = 10):
    from PIL import Image, ImageDraw

    bg = Image.new("RGB", (w, h), "#2a2f3d")
    d = ImageDraw.Draw(bg)
    for y in range(0, h, cell):
        for x in range((y // cell % 2) * cell, w, cell * 2):
            d.rectangle((x, y, x + cell - 1, y + cell - 1), fill="#3a4152")
    return bg


def build_assets_tab(parent, root):
    import tkinter as tk
    from tkinter import messagebox, ttk
    from PIL import Image, ImageTk

    from wan_builder_dialog import build_outputs_panel

    os.makedirs(A.ASSETS_DIR, exist_ok=True)
    kind_label_to_key = {lbl: k for k, lbl in KIND_CHOICES}
    v_kind = tk.StringVar(value=KIND_CHOICES[0][1])
    v_llm = tk.StringVar(value=LLM_AUTO)
    v_read_repo = tk.BooleanVar(value=False)
    v_repo = tk.StringVar(value="")
    v_status = tk.StringVar(value="Describe the asset, then ✨ Expand Brief.")
    v_title = tk.StringVar(value="")
    field_vars: dict[str, tk.StringVar] = {}
    state = {"kind": "icon", "repo": None, "brief": "", "llm_expand": "", "llm_prompt": "", "reasons": []}
    proc_holder = {"proc": None, "out": None, "result": None, "pending": None}
    log_q: queue.Queue = queue.Queue()
    preview_ref = {"img": None}
    turn = addons.desktop_session(root, lambda m: v_status.set(m))
    busy = {"llm": False}

    # render settings
    model_keys = list(A.ASSET_MODELS)
    v_model = tk.StringVar(value="")
    v_w, v_h = tk.IntVar(value=1024), tk.IntVar(value=1024)
    v_steps, v_cfg, v_guid = tk.IntVar(value=24), tk.DoubleVar(value=1.0), tk.DoubleVar(value=3.5)
    v_sampler, v_sched = tk.StringVar(value="euler"), tk.StringVar(value="simple")
    v_seed, v_rand = tk.IntVar(value=42026), tk.BooleanVar(value=True)
    v_tile, v_rmbg = tk.StringVar(value="none"), tk.StringVar(value="none")
    v_pix, v_final, v_exports = tk.IntVar(value=0), tk.StringVar(value=""), tk.StringVar(value="")
    v_hollow = tk.BooleanVar(value=False)
    v_lightning = tk.BooleanVar(value=True)
    v_cmd = tk.StringVar(value="")

    def model_label(key: str) -> str:
        return f"{A.ASSET_MODELS[key]['label']}" + ("" if A.model_installed(key) else "  [not installed]")

    def colour_model_list():
        """Models that spill onto the CPU (bigger than 8 GB VRAM) are red in the open list and in the box."""
        from wan_themes import CAUTION_FG

        try:
            lb = f"{root.tk.call('ttk::combobox::PopdownWindow', cb_model)}.f.l"
            normal = root.tk.call(lb, "cget", "-foreground")
            for i, label in enumerate(cb_model["values"]):
                root.tk.call(lb, "itemconfigure", i, "-foreground",
                             CAUTION_FG if A.spills(label_to_model.get(label, "")) else normal)
        except tk.TclError:
            pass

    def mark_model_caution():
        cb_model.configure(style="Caution.TCombobox" if A.spills(current_model()) else "TCombobox")

    def on_model_picked(*_):
        """Picking a model loads its sampling defaults (klein 4 steps, Qwen-Image Lightning 8 steps...)."""
        st = A.MODEL_SETTINGS.get(current_model())
        if st:
            v_steps.set(st["steps"]); v_cfg.set(st["cfg"]); v_sampler.set(st["sampler"]); v_sched.set(st["scheduler"])
            v_lightning.set(bool(st.get("lightning")))
        refresh_cmd()

    label_to_model = {}

    def refresh_model_list():
        label_to_model.clear()
        for k in model_keys:
            label_to_model[model_label(k)] = k
        cb_model["values"] = list(label_to_model)
        if not v_model.get() or v_model.get() not in label_to_model:
            first = next((k for k in model_keys if A.model_installed(k)), model_keys[0])
            v_model.set(model_label(first))

    def current_model() -> str:
        return label_to_model.get(v_model.get(), "flux_dev")

    # ── helpers ──────────────────────────────────────────────────────────────
    def get_text(w) -> str:
        return w.get("1.0", "end").strip()

    def set_text(w, text: str):
        ro = str(w.cget("state")) == "disabled"
        if ro:
            w.configure(state="normal")
        w.delete("1.0", "end"); w.insert("1.0", text or "")
        if ro:
            w.configure(state="disabled")

    def current_kind() -> str:
        k = kind_label_to_key.get(v_kind.get(), "auto")
        return state["kind"] if k == "auto" else k

    def fields_now() -> dict[str, str]:
        return {k: v.get().strip() for k, v in field_vars.items()}

    def llm_request() -> tuple[str, bool]:
        val = v_llm.get()
        if val == LLM_OFF:
            return "", False
        return ("" if val == LLM_AUTO else val), True

    def refresh_llms():
        have = A.installed_llms()
        vals = [LLM_AUTO, LLM_OFF] + sorted(have or [])
        cb_llm["values"] = vals
        if v_llm.get() not in vals:
            v_llm.set(LLM_AUTO)
        if have is None:
            l_llm_note.configure(text="No LLM found (llama.cpp router or Ollama): offline matcher only")
        else:
            best, why = A.pick_llm(read_code=v_read_repo.get())
            l_llm_note.configure(text=f"Auto → {best}" if best else "No LLM installed: offline matcher")

    # ── field editor (rebuilt per kind) ──────────────────────────────────────
    def build_fields(kind: str, values: dict[str, str] | None = None):
        for wdg in fields_box.winfo_children():
            wdg.destroy()
        old = fields_now()
        field_vars.clear()
        defs = A.FIELDS[kind]
        for i, (key, label, opts, tip) in enumerate(defs):
            r, c = divmod(i, 2)
            lab = ttk.Label(fields_box, text=label + ":")
            lab.grid(row=r, column=c * 2, sticky="w", padx=(4, 2), pady=2)
            var = tk.StringVar(value=(values or {}).get(key, "") if values is not None else old.get(key, ""))
            cb = ttk.Combobox(fields_box, textvariable=var, values=[o for o in opts if o] or [""])  # editable: free text
            cb.grid(row=r, column=c * 2 + 1, sticky="ew", padx=(0, 8), pady=2)
            field_vars[key] = var
            if tip:
                attach_tooltip(lab, tip); attach_tooltip(cb, tip)
        for c in (1, 3):
            fields_box.columnconfigure(c, weight=1)
        lf_fields.configure(text=f"2 · Fine-tune: {A.KIND_LABELS[kind]}  (every field is free text; dropdowns are suggestions)")

    def on_kind_selected(*_):
        k = kind_label_to_key.get(v_kind.get(), "auto")
        if k != "auto" and k != state["kind"]:
            state["kind"] = k
            build_fields(k)

    # ── 1. expand ────────────────────────────────────────────────────────────
    def run_llm_job(label: str, work, done, read_code: bool):
        """work(model, use_llm) runs in a thread; done(result) on Tk."""
        if busy["llm"]:
            return

        busy["llm"] = True
        btn_expand.configure(state="disabled"); btn_analyze.configure(state="disabled")
        requested, use_llm = llm_request()
        v_status.set(f"{label}...")

        def worker():
            model, why = A.pick_llm(read_code=read_code, requested=requested) if use_llm else (None, "")
            try:
                if model:
                    with addons.gpu_session(f"assets {label.lower()}", needs=f"ollama:{model}",
                                            on_status=lambda m: root.after(0, v_status.set, f"⏳ {m}")):
                        root.after(0, v_status.set, f"{label} with {model}...")
                        res = work(model, True)
                else:
                    res = work("", False)
            except (addons.gpu_session_error(), OSError) as exc:
                res = work("", False)
                res.setdefault("notes", []).append(f"{addons.REGISTRY.gpu_unavailable_note} ({exc}); used the offline path.")
            except Exception as exc:  # show it instead of dying silently in a thread
                res = {"error": str(exc)}
            root.after(0, finish, res)

        def finish(res):
            busy["llm"] = False
            btn_expand.configure(state="normal"); btn_analyze.configure(state="normal")
            if res.get("error"):
                v_status.set(f"⚠ {res['error']}")
                messagebox.showerror("Asset Studio", res["error"])
                return
            done(res)

        threading.Thread(target=worker, daemon=True).start()

    def expand():
        brief = get_text(txt_brief)
        if not brief:
            return messagebox.showinfo("Asset Studio", "Write a short brief first (what it is and what it's for).")
        repo = v_repo.get().strip() if v_read_repo.get() else ""
        if v_read_repo.get() and not os.path.isdir(os.path.expanduser(repo)):
            return messagebox.showinfo("Asset Studio", "Pick the repo folder to read (or untick 'Read the repo first').")
        kind = kind_label_to_key.get(v_kind.get(), "auto")

        def work(model, use_llm):
            return A.expand_brief(brief, kind=kind, repo_path=repo, llm=model, use_llm=use_llm)

        def done(res):
            state.update(kind=res["kind"], repo=res.get("repo"), brief=brief, llm_expand=res.get("llm", ""))
            if kind == "auto":
                v_kind.set(A.KIND_LABELS[res["kind"]])
            build_fields(res["kind"], res["fields"])
            set_text(txt_concept, res["concept"])
            v_title.set(res.get("title") or "")
            set_notes(res["notes"] + ["Now fine-tune any field, then 🔍 Analyze."])
            v_status.set(f"Expanded into a {A.KIND_LABELS[res['kind']].lower()} concept" +
                         (f" by {res['llm']}" if res.get("llm") else " (offline matcher)") + ".")

        run_llm_job("Expanding the brief", work, done, read_code=bool(repo))

    # ── 2. analyze ───────────────────────────────────────────────────────────
    def analyze():
        kind = current_kind()
        fields, concept = fields_now(), get_text(txt_concept)
        if not any(fields.values()) and not concept:
            return messagebox.showinfo("Asset Studio", "Expand a brief (or fill some fields) first.")

        def work(model, use_llm):
            return A.analyze(kind, fields, concept, llm=model, use_llm=use_llm, read_code=bool(state.get("repo")))

        def done(plan):
            apply_plan(plan)
            state["llm_prompt"] = plan.get("llm", "")
            set_notes([f"• {r}" for r in plan["reasons"]] + plan["notes"] + ["Change anything below, then ▶ Generate."])
            v_status.set(f"Analyzed: {plan['model_label']}. Review the settings and prompt, then Generate.")

        run_llm_job("Analyzing", work, done, read_code=False)

    def apply_plan(plan: dict):
        refresh_model_list()
        v_model.set(model_label(plan["model"]))
        v_w.set(plan["width"]); v_h.set(plan["height"]); v_steps.set(plan["steps"]); v_cfg.set(plan["cfg"])
        v_guid.set(plan.get("guidance", 3.5)); v_sampler.set(plan["sampler"]); v_sched.set(plan["scheduler"])
        v_seed.set(plan.get("seed", 42026)); v_tile.set(plan["tile"]); v_rmbg.set(plan["remove_bg"])
        v_pix.set(plan.get("pixelate", 0)); v_final.set(plan.get("final_size", "")); v_exports.set(plan.get("export_sizes", ""))
        v_hollow.set(bool(plan.get("hollow")))
        v_lightning.set(bool(plan.get("lightning")))
        set_text(txt_prompt, plan["prompt"]); set_text(txt_neg, plan["negative"])
        state["reasons"] = plan.get("reasons", [])
        refresh_cmd()

    def set_notes(lines: list[str]):
        set_text(txt_notes, "\n".join(lines))

    # ── 3. generate ──────────────────────────────────────────────────────────
    def plan_now() -> dict:
        def iv(var, d):
            try:
                return var.get()
            except (tk.TclError, ValueError):
                return d

        return {"model": current_model(), "width": iv(v_w, 1024), "height": iv(v_h, 1024), "steps": iv(v_steps, 24),
                "cfg": iv(v_cfg, 1.0), "guidance": iv(v_guid, 3.5), "sampler": v_sampler.get(), "scheduler": v_sched.get(),
                "seed": iv(v_seed, 42026), "tile": v_tile.get(), "remove_bg": v_rmbg.get(), "pixelate": iv(v_pix, 0),
                "final_size": v_final.get().strip(), "export_sizes": v_exports.get().strip(), "hollow": v_hollow.get(), "lightning": v_lightning.get(),
                "prompt": get_text(txt_prompt), "negative": get_text(txt_neg)}

    def refresh_cmd(*_):
        try:
            cmd = A.build_command(plan_now(), "<output>.png")
            v_cmd.set(shlex.join(cmd[1:]))
        except Exception:
            pass
        engine = A.ASSET_MODELS.get(current_model(), {}).get("engine")
        e_guid.configure(state="normal" if current_model() == "flux_dev" else "disabled")
        e_cfg.configure(state="disabled" if engine in ("flux", "klein") else "normal")
        chk_light.configure(state="normal" if current_model() == "qwen_image" else "disabled")
        mark_model_caution()

    def generate():
        if proc_holder["proc"] is not None or turn.waiting:
            return
        plan = plan_now()
        if not plan["prompt"]:
            return messagebox.showinfo("Asset Studio", "There's no prompt yet: Expand and Analyze first (or type one).")
        if not A.model_installed(plan["model"]):
            missing = ", ".join(f for f in __import__("generate_asset").model_files(plan["model"])
                                if not os.path.isfile(os.path.join(A.ROOT_DIR, "ComfyUI", "models", f)))
            return messagebox.showwarning("Model not installed", f"{A.ASSET_MODELS[plan['model']]['label']} is missing:\n{missing}\n\n"
                                          "Run: ./start_graphical_studio.sh --model-sync --assets")
        if v_rand.get():
            plan["seed"] = random.randint(1000, 999_999); v_seed.set(plan["seed"])
        kind = current_kind()
        out = A.output_path(kind, v_title.get() or get_text(txt_brief)[:60], plan["prompt"])
        cmd = A.build_command(plan, out)
        recipe = {"kind": kind, "brief": get_text(txt_brief), "title": v_title.get(), "concept": get_text(txt_concept),
                  "fields": fields_now(), "repo": state.get("repo"), "plan": plan, "reasons": state.get("reasons", []),
                  "llm_expand": state.get("llm_expand", ""), "llm_prompt": state.get("llm_prompt", "")}
        proc_holder.update(out=out, result=None, pending=recipe)
        set_text(txt_log, f"$ {shlex.join(cmd)}\n\n")
        btn_gen.configure(state="disabled"); btn_cancel.configure(state="normal"); prog["value"] = 0

        def start():
            v_status.set(f"Rendering with {A.ASSET_MODELS[plan['model']]['label']}...")
            proc_holder["proc"] = start_streaming_process(cmd, log_q)

        def not_started():
            btn_gen.configure(state="normal"); btn_cancel.configure(state="disabled")
            v_status.set("Cancelled before it started.")

        turn.run(f"asset {os.path.basename(out)}", "exclusive", start, not_started)

    def cancel():
        if turn.cancel():
            return
        proc = proc_holder.get("proc")
        if proc is not None and proc.poll() is None:
            proc.terminate(); append_log("\n[CANCELLED BY USER]\n"); v_status.set("Cancelled.")

    def append_log(line: str):
        txt_log.configure(state="normal"); txt_log.insert("end", line); txt_log.see("end"); txt_log.configure(state="disabled")

    def finish_render(rc: int):
        proc_holder["proc"] = None
        turn.release()
        btn_gen.configure(state="normal"); btn_cancel.configure(state="disabled")
        out = proc_holder.get("out")
        if rc != 0 or not out or not os.path.isfile(out):
            v_status.set(f"Render failed (exit {rc}); see the log.")
            return
        prog["value"] = 100
        recipe = dict(proc_holder.get("pending") or {})
        recipe["result"] = proc_holder.get("result")
        try:
            with open(os.path.splitext(out)[0] + ".json", "w", encoding="utf-8") as f:
                json.dump(recipe, f, indent=1)
        except OSError as exc:
            append_log(f"[Recipe] could not save: {exc}\n")
        try:
            plan = recipe.get("plan", {})
            wan_library.record(out, source="desktop-assets", prompt=recipe.get("brief", ""), effective_prompt=plan.get("prompt", ""),
                               settings={**plan, "kind": recipe.get("kind")})
        except Exception as exc:  # never break the render over the library
            append_log(f"[Library] could not record: {exc}\n")
        res = proc_holder.get("result") or {}
        n = len(res.get("exports") or [])
        sm = res.get("slice_margins")
        v_status.set(f"Done: {os.path.basename(out)}" + (f" + {n} export(s)" if n else "")
                     + (" · 9-slice L{} T{} R{} B{}".format(*sm) if sm else ""))
        refresh_outputs(out)

    def poll():
        try:
            while True:
                kind, payload = log_q.get_nowait()
                if kind == "line":
                    m = re.search(r"(\d+)/(\d+)\s*\[", payload)
                    if payload.startswith("ASSET_RESULT="):
                        try:
                            proc_holder["result"] = json.loads(payload.split("=", 1)[1])
                        except ValueError:
                            pass
                    elif m:
                        cur, tot = int(m.group(1)), max(1, int(m.group(2)))
                        prog["value"] = min(99, int(cur / tot * 100)); v_status.set(f"Sampling step {cur}/{tot}...")
                    elif not payload.endswith("%|"):
                        append_log(payload)
                elif kind == "done":
                    finish_render(payload)
        except queue.Empty:
            pass
        root.after(80, poll)

    # ── outputs ──────────────────────────────────────────────────────────────
    def selected_path():
        sel = tree.selection()
        return tree.item(sel[0], "values")[3] if sel else None

    def on_select(*_):
        p = selected_path()
        if not p or not os.path.isfile(p):
            lbl_preview.configure(image="", text="(Select an asset)")
            return
        img = Image.open(p)
        img.thumbnail((s(384), s(216)), Image.Resampling.LANCZOS)
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            bg = _checker(img.width, img.height)
            bg.paste(img, (0, 0), img)
            img = bg
        preview_ref["img"] = ImageTk.PhotoImage(img.convert("RGB"))
        lbl_preview.configure(image=preview_ref["img"], text="")

    def refresh_outputs(select: str | None = None):
        tree.delete(*tree.get_children())
        target = None
        for i, r in enumerate(scan_assets()):
            iid = tree.insert("", "end", values=(r["name"], r["size"], r["mtime"], r["path"]))
            if (select and os.path.abspath(select) == os.path.abspath(r["path"])) or (not select and i == 0):
                target = iid
        if target:
            tree.selection_set(target); tree.focus(target); tree.see(target); on_select()

    def open_selected():
        p = selected_path()
        if p:
            open_path_default(p)

    def open_exports():
        p = selected_path()
        if p:
            d = os.path.splitext(p)[0] + "_sizes"
            open_path_default(d if os.path.isdir(d) else os.path.dirname(p))

    def load_recipe():
        p = selected_path()
        rp = os.path.splitext(p)[0] + ".json" if p else ""
        if not rp or not os.path.isfile(rp):
            return messagebox.showinfo("Asset Studio", "This asset has no saved recipe (only assets made in this tab do).")
        with open(rp, encoding="utf-8") as f:
            rec = json.load(f)
        state.update(kind=rec.get("kind", "icon"), repo=rec.get("repo"), llm_expand=rec.get("llm_expand", ""),
                     llm_prompt=rec.get("llm_prompt", ""))
        v_kind.set(A.KIND_LABELS.get(state["kind"], KIND_CHOICES[0][1]))
        set_text(txt_brief, rec.get("brief", "")); set_text(txt_concept, rec.get("concept", ""))
        v_title.set(rec.get("title", ""))
        build_fields(state["kind"], rec.get("fields", {}))
        if rec.get("plan"):
            plan = {**rec["plan"], "model_label": "", "reasons": rec.get("reasons", [])}
            apply_plan(plan)
            v_rand.set(False)
        set_notes([f"Loaded the recipe of {os.path.basename(p)} (same seed: untick nothing and Generate to reproduce)."]
                  + [f"• {r}" for r in rec.get("reasons", [])])
        v_status.set(f"Recipe loaded from {os.path.basename(p)}.")

    _sc = addons.REGISTRY.private_desktop_shortcuts
    _export_bg_dir = _sc.get("backgrounds_dir", "")

    def copy_to_export_bg():
        import shutil

        if not _export_bg_dir:
            return
        p = selected_path()
        if not p:
            return
        if not os.path.isdir(_export_bg_dir):
            return messagebox.showwarning("Asset Studio", f"Export backgrounds folder not found:\n{_export_bg_dir}")
        shutil.copy2(p, os.path.join(_export_bg_dir, os.path.basename(p)))
        v_status.set(f"Copied {os.path.basename(p)} to {_sc.get('assets_dest_desc', _export_bg_dir)}.")

    def browse_repo():
        from tkinter import filedialog
        import shutil
        import subprocess

        start = v_repo.get() or os.path.expanduser("~")
        path = ""
        if shutil.which("kdialog"):
            res = subprocess.run(["kdialog", "--title", "Pick the repo to read", "--getexistingdirectory", start],
                                 capture_output=True, text=True)
            if res.returncode == 0:
                path = res.stdout.strip()
            elif res.returncode == 1:
                return
        if not path:
            path = filedialog.askdirectory(initialdir=start, title="Pick the repo to read") or ""
        if path:
            v_repo.set(path); v_read_repo.set(True); refresh_llms()

    # ── layout ───────────────────────────────────────────────────────────────
    pane = ttk.Frame(parent, padding=8)
    pane.pack(fill="both", expand=True)
    pane.columnconfigure(0, weight=3); pane.columnconfigure(1, weight=2); pane.rowconfigure(0, weight=1)

    # scrollable left column (the field grid + settings are tall)
    left_outer = ttk.Frame(pane); left_outer.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
    left_outer.rowconfigure(0, weight=1); left_outer.columnconfigure(0, weight=1)
    canvas = tk.Canvas(left_outer, highlightthickness=0, bg="#0d1324")
    vsb = ttk.Scrollbar(left_outer, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vsb.set)
    canvas.grid(row=0, column=0, sticky="nsew"); vsb.grid(row=0, column=1, sticky="ns")
    left = ttk.Frame(canvas)
    win = canvas.create_window((0, 0), window=left, anchor="nw")
    left.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))

    def _wheel(event):
        w = event.widget
        if isinstance(w, (tk.Text, ttk.Combobox)) or str(w).startswith(str(tree)):
            return
        canvas.yview_scroll(-1 if (event.num == 4 or getattr(event, "delta", 0) > 0) else 1, "units")

    def _bind_wheel(_e=None):
        canvas.bind_all("<Button-4>", _wheel); canvas.bind_all("<Button-5>", _wheel); canvas.bind_all("<MouseWheel>", _wheel)

    def _unbind_wheel(_e=None):
        for seq in ("<Button-4>", "<Button-5>", "<MouseWheel>"):
            canvas.unbind_all(seq)

    left_outer.bind("<Enter>", _bind_wheel); left_outer.bind("<Leave>", _unbind_wheel)
    left.columnconfigure(0, weight=1)
    text_kw = dict(wrap="word", bg="#0a0f1f", fg="#eef2fc", insertbackground="#44e0ff", relief="flat", padx=6, pady=5, font=get_font("ui"))

    # 1 · describe
    lf_desc = ttk.LabelFrame(left, text="1 · Describe it (one line is enough)", padding=8)
    lf_desc.grid(row=0, column=0, sticky="ew", pady=(0, 8)); lf_desc.columnconfigure(1, weight=1); lf_desc.columnconfigure(3, weight=1)
    ttk.Label(lf_desc, text="Asset Type:").grid(row=0, column=0, sticky="w", padx=4)
    cb_kind = ttk.Combobox(lf_desc, textvariable=v_kind, values=[lbl for _, lbl in KIND_CHOICES], state="readonly")
    cb_kind.grid(row=0, column=1, sticky="ew", padx=4, pady=2); cb_kind.bind("<<ComboboxSelected>>", on_kind_selected)
    attach_tooltip(cb_kind, "Auto-detect reads the brief (icon / logo / wallpaper / texture / sprite...).")
    ttk.Label(lf_desc, text="LLM:").grid(row=0, column=2, sticky="w", padx=4)
    llm_row = ttk.Frame(lf_desc); llm_row.grid(row=0, column=3, sticky="ew", padx=4)
    cb_llm = ttk.Combobox(llm_row, textvariable=v_llm, values=[LLM_AUTO, LLM_OFF], state="readonly")
    cb_llm.pack(side="left", fill="x", expand=True)
    b_llm = ttk.Button(llm_row, text="⟳", width=3, command=lambda: refresh_llms()); b_llm.pack(side="left", padx=(4, 0))
    attach_tooltip(cb_llm, "Auto picks the best installed Ollama model for the job (Qwen3 8B first; a coder model when reading a repo). "
                           "Off = the offline keyword matcher.")
    l_llm_note = ttk.Label(lf_desc, text="", font=get_font("small_bold"))
    l_llm_note.grid(row=1, column=2, columnspan=2, sticky="w", padx=4)

    txt_brief = tk.Text(lf_desc, height=3, **text_kw)
    txt_brief.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(4, 4))
    attach_tooltip(txt_brief, "What it is and what it's for. Mention anything that must be in it; everything else gets invented.")

    repo_row = ttk.Frame(lf_desc); repo_row.grid(row=3, column=0, columnspan=4, sticky="ew")
    chk_repo = ttk.Checkbutton(repo_row, text="Read the repo first:", variable=v_read_repo, command=lambda: refresh_llms())
    chk_repo.pack(side="left")
    e_repo = ttk.Entry(repo_row, textvariable=v_repo); e_repo.pack(side="left", fill="x", expand=True, padx=4)
    ttk.Button(repo_row, text="Browse...", command=browse_repo).pack(side="left")
    attach_tooltip(chk_repo, "Skims the project (README, package/pyproject, languages, CSS/theme colours, existing icons) "
                             "so the concept, motif and palette fit it. Nothing is changed in the repo.")

    act1 = ttk.Frame(lf_desc); act1.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(6, 0))
    btn_expand = ttk.Button(act1, text="✨ Expand Brief", style="Accent.TButton", command=expand); btn_expand.pack(side="left")
    attach_tooltip(btn_expand, "Fluff the brief into a full concept and pre-fill every field.")

    # 2 · fine-tune
    lf_fields = ttk.LabelFrame(left, text="2 · Fine-tune", padding=8)
    lf_fields.grid(row=1, column=0, sticky="ew", pady=(0, 8)); lf_fields.columnconfigure(0, weight=1)
    t_row = ttk.Frame(lf_fields); t_row.grid(row=0, column=0, sticky="ew")
    ttk.Label(t_row, text="Title:").pack(side="left", padx=4)
    ttk.Entry(t_row, textvariable=v_title).pack(side="left", fill="x", expand=True, padx=4)
    ttk.Label(lf_fields, text="Concept (the fluffed-up description; edit freely):").grid(row=1, column=0, sticky="w", padx=4, pady=(4, 0))
    txt_concept = tk.Text(lf_fields, height=3, **text_kw); txt_concept.grid(row=2, column=0, sticky="ew", pady=(2, 6))
    fields_box = ttk.Frame(lf_fields); fields_box.grid(row=3, column=0, sticky="ew")
    act2 = ttk.Frame(lf_fields); act2.grid(row=4, column=0, sticky="ew", pady=(6, 0))
    btn_analyze = ttk.Button(act2, text="🔍 Analyze", style="Accent.TButton", command=analyze); btn_analyze.pack(side="left")
    attach_tooltip(btn_analyze, "Pick the best image model, settings and post-processing, and write the final prompt for that model.")

    # notes / reasons
    txt_notes = tk.Text(lf_fields, height=5, wrap="word", bg="#0a0f1f", fg="#a9c4f5", relief="flat", padx=6, pady=4,
                        font=get_font("ui"), state="disabled")
    txt_notes.grid(row=5, column=0, sticky="ew", pady=(6, 0))

    # 3 · model & settings
    lf_set = ttk.LabelFrame(left, text="3 · Model, Settings & Prompt (from Analyze; change anything)", padding=8)
    lf_set.grid(row=2, column=0, sticky="ew", pady=(0, 8))
    for c in range(6):
        lf_set.columnconfigure(c, weight=1 if c % 2 else 0)
    ttk.Label(lf_set, text="Image Model:").grid(row=0, column=0, sticky="w", padx=4)
    cb_model = ttk.Combobox(lf_set, textvariable=v_model, state="readonly", postcommand=colour_model_list)
    cb_model.grid(row=0, column=1, columnspan=5, sticky="ew", padx=4, pady=2); cb_model.bind("<<ComboboxSelected>>", on_model_picked)
    attach_tooltip(cb_model, "Red = bigger than 8 GB VRAM: runs partly from system RAM, so it's much slower.")

    def entry(row, col, label, var, tip="", width=8):
        lab = ttk.Label(lf_set, text=label); lab.grid(row=row, column=col, sticky="w", padx=4, pady=2)
        e = ttk.Entry(lf_set, textvariable=var, width=width); e.grid(row=row, column=col + 1, sticky="ew", padx=4, pady=2)
        e.bind("<KeyRelease>", refresh_cmd)
        if tip:
            attach_tooltip(lab, tip); attach_tooltip(e, tip)
        return e

    def combo(row, col, label, var, values, tip=""):
        lab = ttk.Label(lf_set, text=label); lab.grid(row=row, column=col, sticky="w", padx=4, pady=2)
        cb = ttk.Combobox(lf_set, textvariable=var, values=values, state="readonly", width=10)
        cb.grid(row=row, column=col + 1, sticky="ew", padx=4, pady=2); cb.bind("<<ComboboxSelected>>", refresh_cmd)
        if tip:
            attach_tooltip(lab, tip); attach_tooltip(cb, tip)
        return cb

    entry(1, 0, "Width:", v_w, "Render width (multiple of 8 or 16; ~1 MP is the sweet spot).")
    entry(1, 2, "Height:", v_h, "Render height.")
    entry(1, 4, "Steps:", v_steps)
    e_cfg = entry(2, 0, "CFG:", v_cfg, "Guidance scale (FLUX samples at CFG 1.0).")
    e_guid = entry(2, 2, "Flux Guidance:", v_guid, "Flux dev only: 2.5-3 looks natural, 3.5-4.5 follows the prompt harder.")
    entry(2, 4, "Seed:", v_seed)
    combo(3, 0, "Sampler:", v_sampler, list(A.SAMPLERS))
    combo(3, 2, "Scheduler:", v_sched, list(A.SCHEDULERS))
    chk_box = ttk.Frame(lf_set); chk_box.grid(row=3, column=4, columnspan=2, sticky="w", padx=4)
    ttk.Checkbutton(chk_box, text="Random seed", variable=v_rand).pack(side="left")
    chk_hollow = ttk.Checkbutton(chk_box, text="Hollow center", variable=v_hollow, command=refresh_cmd)
    chk_hollow.pack(side="left", padx=(8, 0))
    def on_lightning():
        if current_model() == "qwen_image":
            v_steps.set(8 if v_lightning.get() else 28); v_cfg.set(1.0 if v_lightning.get() else 2.5)
        refresh_cmd()

    chk_light = ttk.Checkbutton(chk_box, text="Lightning", variable=v_lightning, command=on_lightning)
    chk_light.pack(side="left", padx=(8, 0))
    attach_tooltip(chk_light, "Qwen-Image only: 8-step Lightning LoRA at CFG 1. Untick for ~28 steps at CFG 2.5 (better, much slower).")
    attach_tooltip(chk_hollow, "UI frames: make the flat interior transparent and measure the 9-slice margins.")
    combo(4, 0, "Seamless Tile:", v_tile, ["none", "both", "x"], "Seamless tiling (optional checkpoint add-on only).")
    combo(4, 2, "Cut Out BG:", v_rmbg, ["none", "general", "anime"], "Remove the background to a transparent PNG (rembg, CPU).")
    entry(4, 4, "Pixel Grid:", v_pix, "Snap to N-px pixel-art cells (0 = off).")
    entry(5, 0, "Final Size:", v_final, "WxH to resize/crop the master to (empty = as rendered).", width=12)
    lab_ex = ttk.Label(lf_set, text="Export Sizes:"); lab_ex.grid(row=5, column=2, sticky="w", padx=4)
    e_ex = ttk.Entry(lf_set, textvariable=v_exports); e_ex.grid(row=5, column=3, columnspan=3, sticky="ew", padx=4, pady=2)
    e_ex.bind("<KeyRelease>", refresh_cmd)
    attach_tooltip(e_ex, "Comma-separated square sizes; PNGs + a .ico go into <name>_sizes/.")

    ttk.Label(lf_set, text="Prompt:").grid(row=6, column=0, sticky="nw", padx=4, pady=(6, 0))
    txt_prompt = tk.Text(lf_set, height=5, **text_kw); txt_prompt.grid(row=6, column=1, columnspan=5, sticky="ew", pady=(6, 2))
    txt_prompt.bind("<KeyRelease>", refresh_cmd)
    ttk.Label(lf_set, text="Negative:").grid(row=7, column=0, sticky="nw", padx=4)
    txt_neg = tk.Text(lf_set, height=2, **{**text_kw, "fg": "#cdd6ef"}); txt_neg.grid(row=7, column=1, columnspan=5, sticky="ew", pady=2)
    txt_neg.bind("<KeyRelease>", refresh_cmd)
    attach_tooltip(txt_neg, "Used by Qwen-Image and optional checkpoints. Flux ignores negatives (put 'without X' in the prompt instead).")
    ttk.Label(lf_set, text="CLI:").grid(row=8, column=0, sticky="w", padx=4)
    ttk.Entry(lf_set, textvariable=v_cmd, state="readonly").grid(row=8, column=1, columnspan=5, sticky="ew", padx=4, pady=2)

    act3 = ttk.Frame(lf_set); act3.grid(row=9, column=0, columnspan=6, sticky="ew", pady=(6, 0))
    btn_gen = ttk.Button(act3, text="▶ Generate Asset", style="Accent.TButton", command=generate); btn_gen.pack(side="left", padx=(0, 6))
    btn_cancel = ttk.Button(act3, text="⏹ Cancel", state="disabled", command=cancel); btn_cancel.pack(side="left", padx=(0, 10))
    prog = ttk.Progressbar(act3, mode="determinate", maximum=100, length=s(160)); prog.pack(side="left", padx=(0, 8))
    ttk.Label(act3, textvariable=v_status, wraplength=s(420)).pack(side="left", fill="x", expand=True)

    lf_log = ttk.LabelFrame(left, text="Render Log", padding=6)
    lf_log.grid(row=3, column=0, sticky="ew"); lf_log.columnconfigure(0, weight=1)
    txt_log = tk.Text(lf_log, height=6, wrap="word", bg="#070a14", fg="#a7e9c4", state="disabled", relief="flat", font=get_font("mono"))
    txt_log._is_log = True
    txt_log.grid(row=0, column=0, sticky="ew")

    _, tree, lbl_preview = build_outputs_panel(
        pane, root, "Generated Assets (outputs/assets)", "Select an asset to preview", on_select, open_selected,
        [("Open Image", open_selected), ("Load Recipe (brief, fields, settings)", load_recipe), ("Open Size Exports", open_exports),
         (_sc.get("select_menu", "Reveal in File Manager"), lambda: reveal_in_file_manager(selected_path(), A.ASSETS_DIR)),
         ("Open Assets Folder", lambda: open_path_default(A.ASSETS_DIR))],
        [("🖼 Open Image", open_selected, 0, 0, 1, "TButton", "open_output"),
         ("📥 Load Recipe", load_recipe, 0, 1, 1, "Accent.TButton", "Put back the brief, concept, fields, model, settings and seed."),
         ("🗂 Open Size Exports", open_exports, 1, 0, 1, "TButton", "The icon size set (PNGs + .ico) for this asset."),
         (_sc.get("select_btn", "📂 Reveal File"), lambda: reveal_in_file_manager(selected_path(), A.ASSETS_DIR), 1, 1, 1, "TButton", _sc.get("tt_select", "select_file")),
         ("📁 Open Assets Folder", lambda: open_path_default(A.ASSETS_DIR), 2, 0, 1, "TButton", "Open outputs/assets."),
         ("🔄 Refresh List", lambda: refresh_outputs(), 2, 1, 1, "TButton", "refresh_list")],
    )

    def _rescale(_s):
        if prog.winfo_exists():
            prog.configure(length=s(160))
        on_select()

    register_scale_listener(_rescale)
    refresh_model_list()
    build_fields("icon")
    refresh_cmd()
    refresh_outputs()
    root.after(200, refresh_llms)
    root.after(80, poll)
    return {"refresh": refresh_outputs, "open_selected": open_selected,
            "select_file": lambda: reveal_in_file_manager(selected_path(), A.ASSETS_DIR),
            "open_folder": lambda: open_path_default(A.ASSETS_DIR),
            **({"copy_export": copy_to_export_bg} if _export_bg_dir else {})}
