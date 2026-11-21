"""Tkinter Photos & Images tab."""

import os
import queue
import random
import re
import shlex
import shutil

import addons
import studio_library
from studio_builder_dialog import build_outputs_panel, build_quick_bar
from studio_compat import PHOTO_MODEL_SETTINGS, evaluate_photo_compat
from studio_dpi import fit_window_geometry, get_font, register_scale_listener, s
from studio_rectifier import rectify_freeform_prompt
from studio_profiles import (
    PROFILE_MODE_NONE,
    PROFILE_MODE_VARY,
    delete_character_profile,
    extract_person_traits_from_prompt,
    generate_random_person_variation,
    get_photo_meta,
    get_profile_dropdown_values,
    load_profiles,
    parse_profile_selection,
    record_photo_meta,
    resolve_profile_ref_image,
    save_character_profile,
)
from studio_helpers import (
    AMERICAN_REALISTIC_STYLE,
    ANIME_BG_STYLE,
    ANIME_GREENSCREEN_CHAR_STYLE,
    PHOTO_DEFAULT_NEGATIVE,
    PHOTO_PRESETS,
    PHOTOS_DIR,
    REF_STYLE_OPTIONS,
    REF_TARGET_OPTIONS,
    build_photo_cli_command,
    get_photo_model_options,
    open_path_default,
    reveal_in_file_manager,
    scan_photo_outputs,
    slugify_photo_prompt,
    start_streaming_process,
)
from studio_tooltips import attach_tooltip, build_wh_row, pick_file_native


def build_photos_tab(parent, root, on_open_builder=None, on_import_builder=None, extra_ctrls=None):
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from PIL import Image, ImageTk

    os.makedirs(PHOTOS_DIR, exist_ok=True)
    photo_models = get_photo_model_options()
    model_map = {label: key for key, label in photo_models}
    default_m = addons.REGISTRY.models.get("default_photo_model") or "flux2_klein"
    default_st = PHOTO_MODEL_SETTINGS.get(default_m, {"steps": 4, "cfg": 1.0, "sampler": "euler", "scheduler": "simple"})
    supports_ref = bool(addons.REGISTRY.models.get("supports_ref"))
    ref_mode_map = {label: key for key, label in REF_TARGET_OPTIONS}
    ref_style_map = {label: text for label, text in REF_STYLE_OPTIONS}
    v_model = tk.StringVar(value=photo_models[0][1])
    v_preset = tk.StringVar(value=list(PHOTO_PRESETS.keys())[0])
    v_width, v_height = tk.IntVar(value=1280), tk.IntVar(value=720)
    v_steps = tk.IntVar(value=default_st["steps"])
    v_cfg = tk.DoubleVar(value=default_st["cfg"])
    v_seed = tk.IntVar(value=42026)
    v_rand_seed = tk.BooleanVar(value=True)
    v_sampler = tk.StringVar(value=default_st["sampler"])
    v_scheduler = tk.StringVar(value=default_st["scheduler"])
    v_ref_img, v_ref_mode = tk.StringVar(value=""), tk.StringVar(value=REF_TARGET_OPTIONS[0][1])
    v_ref_style, v_ref_weight = tk.StringVar(value=REF_STYLE_OPTIONS[0][0]), tk.DoubleVar(value=0.75)
    v_profile = tk.StringVar(value=PROFILE_MODE_VARY)
    v_outname, v_cmd = tk.StringVar(value=""), tk.StringVar(value="")
    v_compat = tk.StringVar(value="")
    v_status = tk.StringVar(value=addons.REGISTRY.desktop.get("photo_ready_status") or "Ready (FLUX / Qwen-Image)")
    compat_state = {"reduced": {}, "restricted": [], "builder_vals": None}
    proc_holder = {"proc": None, "last_out": None, "pending_meta": None}
    profile_state = {"auto_ref": ""}
    log_q: queue.Queue = queue.Queue()
    preview_ref = {"photo": None}
    photo_turn = addons.desktop_session(root, lambda m: v_status.set(m))

    def get_cfg(include_profile_traits: bool = False, variation_override: str = ""):
        base_prompt = txt_prompt.get("1.0", "end").strip()
        eff_prompt = base_prompt
        pmode, pname = parse_profile_selection(v_profile.get())
        if include_profile_traits:
            if pmode == "profile" and pname:
                prof = load_profiles().get(pname, {})
                traits = (prof.get("traits") or "").strip()
                if traits and traits.lower() not in eff_prompt.lower():
                    eff_prompt = f"{eff_prompt}, {traits}" if eff_prompt else traits
            elif pmode == "vary" and variation_override:
                eff_prompt = f"{eff_prompt}, {variation_override}" if eff_prompt else variation_override
        return {
            "model": model_map.get(v_model.get(), default_m),
            "prompt": eff_prompt,
            "negative": txt_neg.get("1.0", "end").strip(),
            "output_name": v_outname.get().strip(),
            "ref_image": v_ref_img.get().strip(),
            "ref_mode": ref_mode_map.get(v_ref_mode.get(), "none"),
            "ref_weight": v_ref_weight.get(),
            "width": v_width.get(), "height": v_height.get(),
            "steps": v_steps.get(), "cfg": v_cfg.get(), "seed": v_seed.get(),
            "sampler": v_sampler.get(), "scheduler": v_scheduler.get(),
        }

    def refresh_cmd(*_):
        try:
            v_cmd.set(shlex.join(build_photo_cli_command(get_cfg())))
        except Exception:
            pass

    def set_prompt(text: str, replace: bool = True, builder_vals: dict | None = None, vision: str = "",
                   settings: dict | None = None, builder: dict | None = None):
        """Fill the prompt; from the Prompt Builder also the auto-picked model and settings.
        The builder state is saved to the library with each photo (Import into Prompt Builder)."""
        if builder is not None or builder_vals:
            compat_state["builder"] = builder or studio_library.builder_state(builder_vals, vision, "photo", text)
        elif replace:
            compat_state["builder"] = None
        if replace:
            txt_prompt.delete("1.0", "end")
            txt_prompt.insert("1.0", text)
        else:
            cur = txt_prompt.get("1.0", "end").strip()
            txt_prompt.delete("1.0", "end")
            txt_prompt.insert("1.0", f"{cur}, {text}" if cur else text)
        if builder_vals:
            apply_compat(builder_vals)
        if settings:
            apply_builder_settings(settings)
        refresh_cmd()
        v_status.set("Photo prompt & settings updated from Builder.")

    def apply_builder_settings(st: dict):
        """Everything the builder picked for this prompt (studio_compat.recommended_photo_settings)."""
        label = next((lbl for key, lbl in photo_models if key == st.get("model")), None)
        if label:
            v_model.set(label)
        if st.get("preset") in PHOTO_PRESETS:
            v_preset.set(st["preset"])
            on_preset()
        elif st.get("width") and st.get("height"):
            v_width.set(int(st["width"])); v_height.set(int(st["height"]))
        for var, key in ((v_steps, "steps"), (v_cfg, "cfg"), (v_sampler, "sampler"), (v_scheduler, "scheduler")):
            if st.get(key) not in (None, ""):
                var.set(st[key])
        if "vary_person" in st:
            refresh_profile_dropdown(PROFILE_MODE_VARY if st["vary_person"] else PROFILE_MODE_NONE)
        adds = st.get("neg_additions") or []
        cur_neg = txt_neg.get("1.0", "end").strip()
        missing = [t for t in adds if t not in cur_neg.lower()]
        if missing:
            txt_neg.delete("1.0", "end")
            txt_neg.insert("1.0", f"{cur_neg}, {', '.join(missing)}" if cur_neg else ", ".join(missing))
        v_compat.set(f"✅ Builder picked {st.get('model', '').upper()}, {st.get('steps')} steps, CFG {st.get('cfg')}")

    def on_model_selected(*_):
        mkey = model_map.get(v_model.get(), "")
        if not supports_ref and mkey in PHOTO_MODEL_SETTINGS:
            st = PHOTO_MODEL_SETTINGS[mkey]
            v_steps.set(st["steps"]); v_cfg.set(st["cfg"])
            v_sampler.set(st["sampler"]); v_scheduler.set(st["scheduler"])
        warn = compat_state["reduced"].get(mkey)
        if warn:
            v_compat.set(f"⚠ {warn}")
        elif compat_state["restricted"]:
            names = ", ".join(k.upper() for k, _, _ in compat_state["restricted"])
            v_compat.set(f"✅ Best selected | ⛔ Restricted: {names}")
        refresh_cmd()

    def apply_compat(builder_vals: dict):
        compat_state["builder_vals"] = dict(builder_vals)
        res = evaluate_photo_compat(builder_vals)
        compat_state["reduced"] = res["reduced_warnings"]
        compat_state["restricted"] = res["restricted_models"]
        cb_model["values"] = [lbl for _, lbl in res["allowed_models"]]
        best_lbl = next((lbl for k, lbl in res["allowed_models"] if k == res["best_model"]), res["allowed_models"][0][1])
        v_model.set(best_lbl)
        if res["best_preset"] in PHOTO_PRESETS:
            v_preset.set(res["best_preset"])
            on_preset()
        v_cfg.set(res["best_cfg"])
        if res["neg_additions"]:
            cur_neg = txt_neg.get("1.0", "end").strip()
            missing = [t for t in res["neg_additions"] if t not in cur_neg.lower()]
            if missing:
                txt_neg.delete("1.0", "end")
                txt_neg.insert("1.0", f"{cur_neg}, {', '.join(missing)}" if cur_neg else ", ".join(missing))
        if res["restricted_models"]:
            r_names = ", ".join(k.upper() for k, _, _ in res["restricted_models"])
            v_compat.set(f"✅ Auto-picked {res['best_model'].upper()} + {res['best_preset'].split('(')[1].rstrip(')')} | ⛔ Restricted: {r_names}")
        else:
            v_compat.set(f"✅ Auto-picked {res['best_model'].upper()} ({res['best_preset'].split('(')[1].rstrip(')')}, CFG {res['best_cfg']})")

    def unlock_all_models():
        compat_state["reduced"] = {}
        compat_state["restricted"] = []
        cb_model["values"] = [m[1] for m in photo_models]
        v_compat.set("All models unlocked (manual mode).")
        refresh_cmd()

    def on_preset(*_):
        w, h = PHOTO_PRESETS.get(v_preset.get(), (1280, 720))
        v_width.set(w); v_height.set(h)
        refresh_cmd()

    def selected_path():
        sel = tree.selection()
        return tree.item(sel[0], "values")[3] if sel else None

    def on_select_photo(*_):
        p = selected_path()
        if p and os.path.isfile(p):
            img = Image.open(p).convert("RGB")
            img.thumbnail((s(384), s(216)), Image.Resampling.LANCZOS)
            preview_ref["photo"] = ImageTk.PhotoImage(img)
            lbl_preview.configure(image=preview_ref["photo"], text="")
        else:
            lbl_preview.configure(image="", text="(Select a generated photo)")

    def refresh_photos(select_file: str | None = None):
        tree.delete(*tree.get_children())
        rows = scan_photo_outputs(PHOTOS_DIR)
        target = None
        for idx, r in enumerate(rows):
            iid = tree.insert("", "end", values=(r["name"], r["size"], r["mtime"], r["path"]))
            if (select_file and os.path.abspath(r["path"]) == os.path.abspath(select_file)) or (not select_file and idx == 0):
                target = iid
        if target:
            tree.selection_set(target); tree.focus(target)
            on_select_photo()

    def open_selected_photo():
        p = selected_path()
        if not p or not os.path.isfile(p):
            return messagebox.showinfo("No Selection", "Select a generated image first.")
        open_path_default(p)

    _sc = addons.REGISTRY.desktop.get("shortcuts", {})
    _export_bg_dir = _sc.get("backgrounds_dir", "")

    def select_in_fm():
        reveal_in_file_manager(selected_path(), PHOTOS_DIR)

    def open_folder_fm():
        reveal_in_file_manager(None, PHOTOS_DIR)

    def copy_to_export_bg():
        if not _export_bg_dir:
            return
        p = selected_path()
        if not p or not os.path.isfile(p):
            return messagebox.showinfo("No Selection", "Select a generated image first.")
        os.makedirs(_export_bg_dir, exist_ok=True)
        shutil.copy2(p, os.path.join(_export_bg_dir, os.path.basename(p)))
        v_status.set(f"Copied {os.path.basename(p)} to {_sc.get('photo_dest_desc', _export_bg_dir)}")

    def send_selected_to_reference():
        p = selected_path()
        if not p or not os.path.isfile(p):
            return messagebox.showinfo("No Selection", "Select a generated image first.")
        v_ref_img.set(p)
        if ref_mode_map.get(v_ref_mode.get(), "none") == "none":
            v_ref_mode.set(REF_TARGET_OPTIONS[1][1])
        refresh_cmd()
        v_status.set(f"Reference image set: {os.path.basename(p)} (edit prompt to fix/refine)")

    def apply_recipe(asset: dict, prompt: str | None = None, builder: dict | None = None):
        """Put a library photo's exact recipe in the form: prompt, model, size, steps, CFG, sampler,
        scheduler, negatives and the same seed (random seed off), plus its reference if still there."""
        st = asset.get("settings") or {}
        if prompt is None:
            prompt = asset["prompt"] + (f", {asset['variation']}" if asset.get("variation") else "") \
                if asset.get("prompt") else asset.get("effective_prompt", "")
        set_prompt(prompt, replace=True, builder=builder)
        apply_builder_settings({k: st.get(k) for k in ("model", "width", "height", "steps", "cfg", "sampler", "scheduler")}
                               | {"vary_person": False})
        if "negative" in st:
            txt_neg.delete("1.0", "end"); txt_neg.insert("1.0", st["negative"])
        if st.get("seed") is not None:
            v_seed.set(int(st["seed"])); v_rand_seed.set(False)
        ref = asset.get("reference") or ""
        if ref and os.path.isfile(ref) and st.get("ref_mode") in ("person", "background"):
            v_ref_img.set(ref)
            v_ref_mode.set(next(lbl for key, lbl in REF_TARGET_OPTIONS if key == st["ref_mode"]))
        refresh_cmd()

    def selected_asset() -> dict | None:
        p = selected_path()
        if not p or not os.path.isfile(p):
            messagebox.showinfo("No Selection", "Select a generated photo first.")
            return None
        asset = studio_library.get(p)
        if not asset or not (asset.get("effective_prompt") or asset.get("builder")):
            messagebox.showinfo("Nothing Saved", "Nothing is saved about how this photo was made, so there's nothing to import.")
            return None
        return asset

    def import_selected():
        """Import into Prompt Builder: the exact recipe in the form, and the builder state in the builder."""
        asset = selected_asset()
        if not asset:
            return
        apply_recipe(asset, builder=asset.get("builder"))
        if asset.get("builder") and on_import_builder:
            on_import_builder(asset)
            v_status.set(f"Imported {os.path.basename(asset['path'])}: builder and form restored (same seed).")
        else:
            v_status.set(f"Imported {os.path.basename(asset['path'])}: exact prompt and settings (same seed). "
                         "It wasn't made with the Prompt Builder, so there are no dropdowns to restore.")

    def refresh_profile_dropdown(select_value: str | None = None):
        vals = get_profile_dropdown_values()
        cb_profile["values"] = vals
        if select_value and select_value in vals:
            v_profile.set(select_value)
        elif v_profile.get() not in vals:
            v_profile.set(PROFILE_MODE_VARY)
        pmode, _ = parse_profile_selection(v_profile.get())
        b_del_prof.configure(state="normal" if pmode == "profile" else "disabled")

    def on_profile_selected(*_):
        pmode, pname = parse_profile_selection(v_profile.get())
        b_del_prof.configure(state="normal" if pmode == "profile" else "disabled")
        if pmode == "profile" and pname:
            prof = load_profiles().get(pname, {})
            ref_p = resolve_profile_ref_image(prof) if supports_ref else ""
            if ref_p:
                v_ref_img.set(ref_p)
                v_ref_mode.set(REF_TARGET_OPTIONS[1][1])
                v_ref_weight.set(float(prof.get("ref_weight", 0.72)))
                profile_state["auto_ref"] = ref_p
            v_status.set(f"Character Profile active: {pname} (saved traits)" if not supports_ref
                         else f"Character Profile active: {pname} (locked face + saved traits)")
        else:
            if profile_state["auto_ref"] and v_ref_img.get().strip() == profile_state["auto_ref"]:
                v_ref_img.set("")
                v_ref_mode.set(REF_TARGET_OPTIONS[0][1])
            profile_state["auto_ref"] = ""
            if pmode == "vary":
                v_status.set("Auto Person Variety active (distinct face each run)")
            else:
                v_status.set("Character Profile: None (using prompt as-is)")
        refresh_cmd()

    def delete_active_profile():
        pmode, pname = parse_profile_selection(v_profile.get())
        if pmode != "profile" or not pname:
            return
        if not messagebox.askyesno("Delete Profile", f"Delete saved Character Profile '{pname}'?"):
            return
        delete_character_profile(pname)
        if profile_state["auto_ref"] and v_ref_img.get().strip() == profile_state["auto_ref"]:
            v_ref_img.set("")
            v_ref_mode.set(REF_TARGET_OPTIONS[0][1])
        profile_state["auto_ref"] = ""
        refresh_profile_dropdown(PROFILE_MODE_VARY)
        refresh_cmd()
        v_status.set(f"Deleted Character Profile: {pname}")

    def open_save_profile_dialog():
        p = selected_path()
        if not p or not os.path.isfile(p):
            return messagebox.showinfo("No Selection", "Select a generated photo first to save that person as a profile.")
        from studio_tooltips import CURRENT_PALETTE

        meta = get_photo_meta(p)
        src_prompt = meta.get("base_prompt") or txt_prompt.get("1.0", "end").strip()
        src_var = meta.get("variation") or ""
        default_traits = extract_person_traits_from_prompt(src_prompt, src_var)

        pal = CURRENT_PALETTE
        dlg = tk.Toplevel(root)
        dlg.title("👤 Save Person as Character Profile")
        fit_window_geometry(dlg, 620, 480, 500, 400)
        dlg.configure(bg=pal["bg"])
        dlg.transient(root)

        wrap = ttk.Frame(dlg, padding=s(12))
        wrap.pack(fill="both", expand=True)
        wrap.columnconfigure(1, weight=1)
        wrap.rowconfigure(3, weight=1)

        top = ttk.Frame(wrap)
        top.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, s(8)))
        img = Image.open(p).convert("RGB")
        img.thumbnail((s(120), s(120)), Image.Resampling.LANCZOS)
        dlg._thumb = ImageTk.PhotoImage(img)
        tk.Label(top, image=dlg._thumb, bg=pal["input_bg"], bd=1, relief="solid").pack(side="left", padx=(0, s(10)))
        info = ttk.Frame(top)
        info.pack(side="left", fill="both", expand=True)
        ttk.Label(info, text="Save this person so you can reuse them across new outfits, poses & scenes.", wraplength=s(420)).pack(anchor="w")
        ttk.Label(info, text=f"Source photo: {os.path.basename(p)}", font=get_font("small")).pack(anchor="w", pady=(s(4), 0))

        ttk.Label(wrap, text="Profile Name:").grid(row=1, column=0, sticky="w", padx=(0, s(8)), pady=s(4))
        v_pname = tk.StringVar(value="")
        e_pname = ttk.Entry(wrap, textvariable=v_pname)
        e_pname.grid(row=1, column=1, sticky="ew", pady=s(4))
        e_pname.focus_set()

        opt_row = ttk.Frame(wrap)
        opt_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=s(4))
        v_use_ref = tk.BooleanVar(value=supports_ref)
        v_pweight = tk.DoubleVar(value=0.72)
        if supports_ref:
            ttk.Checkbutton(opt_row, text="Lock face with reference portrait", variable=v_use_ref).pack(side="left")
            ttk.Label(opt_row, text="Weight:").pack(side="left", padx=(s(12), s(4)))
            ttk.Entry(opt_row, textvariable=v_pweight, width=6).pack(side="left")

        ttk.Label(wrap, text="Saved Person Traits (editable):").grid(row=3, column=0, columnspan=2, sticky="nw", pady=(s(4), 0))
        txt_traits = tk.Text(
            wrap, height=6, wrap="word", bg=pal["input_bg"], fg=pal["fg"],
            insertbackground=pal["accent"], relief="flat", padx=6, pady=6, font=get_font("ui"),
        )
        txt_traits.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=(s(4), s(10)))
        wrap.rowconfigure(3, weight=0)
        wrap.rowconfigure(4, weight=1)
        txt_traits.insert("1.0", default_traits)

        def do_save():
            nm = v_pname.get().strip()
            if not nm:
                return messagebox.showwarning("Missing Name", "Enter a name for this Character Profile (e.g. Maya, Chloe).", parent=dlg)
            try:
                wt = float(v_pweight.get())
            except Exception:
                wt = 0.72
            save_character_profile(
                name=nm,
                traits=txt_traits.get("1.0", "end").strip(),
                source_image=p if v_use_ref.get() else "",
                ref_weight=wt,
                model_key=meta.get("model", model_map.get(v_model.get(), "")),
                seed=meta.get("seed", 0),
            )
            refresh_profile_dropdown(f"👤 {nm}")
            on_profile_selected()
            v_status.set(f"Saved Character Profile '{nm}' — select it anytime from Character Profile.")
            dlg.destroy()

        bbar = ttk.Frame(wrap)
        bbar.grid(row=5, column=0, columnspan=2, sticky="ew")
        ttk.Button(bbar, text="💾 Save Profile", style="Accent.TButton", command=do_save).pack(side="left", padx=(0, s(8)))
        ttk.Button(bbar, text="Cancel", command=dlg.destroy).pack(side="right")

    def append_log(line: str):
        txt_log.configure(state="normal"); txt_log.insert("end", line); txt_log.see("end"); txt_log.configure(state="disabled")

    def start_generate():
        if proc_holder["proc"] is not None or photo_turn.waiting:
            return
        if v_rand_seed.get():
            v_seed.set(random.randint(1000, 999999))
        pmode, pname = parse_profile_selection(v_profile.get())
        base_prompt = txt_prompt.get("1.0", "end").strip()
        variation = ""
        if pmode == "vary" and "no humans" not in base_prompt.lower():
            variation = generate_random_person_variation(base_prompt)
        cfg = get_cfg(include_profile_traits=True, variation_override=variation)
        cfg["prompt"], rect_notes = rectify_freeform_prompt(
            cfg["prompt"],
            priority_hints=compat_state.get("builder_vals"),
            use_extra_llm=False,
        )
        out_path = slugify_photo_prompt(base_prompt or cfg["prompt"], cfg["output_name"], cfg["model"])
        cfg["output"] = out_path
        cmd = build_photo_cli_command(cfg)
        v_cmd.set(shlex.join(cmd))
        proc_holder["last_out"] = None
        builder = compat_state.get("builder") if base_prompt else None
        parent_ref = compat_state.pop("derived_parent", "")
        src_name = "desktop-builder" if builder else "desktop"
        if parent_ref:
            src_name = compat_state.pop("derived_source", "desktop-derived")
        proc_holder["pending_library"] = {
            "source": src_name, "parent": parent_ref,
            "prompt": base_prompt, "variation": variation,
            "effective_prompt": cfg["prompt"], "settings": dict(cfg), "builder": builder,
            "reference": cfg.get("ref_image") if cfg.get("ref_mode") in ("person", "background") else "",
        }
        proc_holder["pending_meta"] = {
            "base_prompt": base_prompt,
            "effective_prompt": cfg["prompt"],
            "variation": variation,
            "profile": pname if pmode == "profile" else "",
            "model": cfg["model"],
            "seed": cfg["seed"],
        }
        txt_log.configure(state="normal"); txt_log.delete("1.0", "end"); txt_log.configure(state="disabled")
        if variation:
            append_log(f"[Auto Person Variety] + {variation}\n")
        elif pmode == "profile" and pname:
            append_log(f"[Character Profile] {pname}\n")
        for rn in rect_notes:
            append_log(f"[Conflict Rectifier] {rn}\n")
        append_log(f"$ {shlex.join(cmd)}\n\n")
        btn_gen.configure(state="disabled"); btn_cancel.configure(state="normal")
        prog["value"] = 0

        def start_render():
            v_status.set(f"Generating Photo ({cfg['model']})...")
            proc_holder["proc"] = start_streaming_process(cmd, log_q)

        def not_started():
            btn_gen.configure(state="normal"); btn_cancel.configure(state="disabled")
            v_status.set("Cancelled before it started.")

        photo_turn.run(f"photo {os.path.basename(out_path)}", "exclusive", start_render, not_started)

    def cancel_generate():
        if photo_turn.cancel():
            return
        proc = proc_holder.get("proc")
        if proc is not None and proc.poll() is None:
            proc.terminate(); append_log("\n[CANCELLED BY USER]\n"); v_status.set("Photo generation cancelled.")

    def poll_queue():
        try:
            while True:
                kind, payload = log_q.get_nowait()
                if kind == "line":
                    m = re.search(r"(\d+)/(\d+)\s*\[", payload)
                    m_saved = re.search(r"\[(?:Photo|Asset)\s+[^\]]+\]\s+Saved\s+(\S+)", payload)
                    if m_saved:
                        saved_p = m_saved.group(1)
                        proc_holder["last_out"] = saved_p
                        if proc_holder.get("pending_meta"):
                            record_photo_meta(saved_p, proc_holder["pending_meta"])
                        if proc_holder.get("pending_library"):
                            try:
                                studio_library.record(saved_p, **proc_holder["pending_library"])
                            except Exception as exc:
                                append_log(f"[Library] could not record {os.path.basename(saved_p)}: {exc}\n")
                    if m:
                        cur, tot = int(m.group(1)), max(1, int(m.group(2)))
                        prog["value"] = min(100, int((cur / tot) * 100))
                        v_status.set(f"Sampling step {cur}/{tot}...")
                    elif not payload.endswith("%|"):
                        append_log(payload)
                elif kind == "done":
                    proc_holder["proc"] = None
                    photo_turn.release()
                    btn_gen.configure(state="normal"); btn_cancel.configure(state="disabled")
                    if payload == 0:
                        prog["value"] = 100; v_status.set("Photo generation complete!")
                        refresh_photos(proc_holder.get("last_out"))
                    else:
                        v_status.set(f"Exited with code {payload}")
        except queue.Empty:
            pass
        root.after(80, poll_queue)

    pane = ttk.Frame(parent, padding=8)
    pane.pack(fill="both", expand=True)
    pane.columnconfigure(0, weight=3); pane.columnconfigure(1, weight=2); pane.rowconfigure(0, weight=1)

    left = ttk.Frame(pane); left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
    left.rowconfigure(2, weight=1); left.columnconfigure(0, weight=1)

    lf_flags = ttk.LabelFrame(left, text="Photo Model & CLI Flags", padding=8)
    lf_flags.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    for c in range(4):
        lf_flags.columnconfigure(c, weight=1)

    def browse_ref_image():
        path = pick_file_native("Select Reference Image", PHOTOS_DIR, "Images (*.jpg *.jpeg *.png *.webp);;All files (*)", [("Images", "*.jpg *.jpeg *.png *.webp"), ("All files", "*.*")])
        if path:
            v_ref_img.set(path)
            if ref_mode_map.get(v_ref_mode.get(), "none") == "none":
                v_ref_mode.set(REF_TARGET_OPTIONS[1][1])
            refresh_cmd()

    def clear_ref_image():
        v_ref_img.set(""); v_ref_mode.set(REF_TARGET_OPTIONS[0][1]); refresh_cmd()

    def apply_ref_style(*_):
        prefix = ref_style_map.get(v_ref_style.get(), "")
        if prefix:
            cur = txt_prompt.get("1.0", "end").strip()
            if prefix not in cur:
                txt_prompt.delete("1.0", "end")
                txt_prompt.insert("1.0", f"{prefix}, {cur}" if cur else prefix)
            if "JRPG" in v_ref_style.get():
                pref = addons.REGISTRY.models.get("anime_photo_model") or default_m
                v_model.set(next((m[1] for m in photo_models if m[0] == pref), photo_models[0][1]))
        refresh_cmd()

    l_mod = ttk.Label(lf_flags, text="Model (--model):"); l_mod.grid(row=0, column=0, sticky="w", padx=4)
    cb_model = ttk.Combobox(lf_flags, textvariable=v_model, values=[m[1] for m in photo_models], state="readonly")
    cb_model.grid(row=0, column=1, columnspan=3, sticky="ew", padx=4, pady=2); cb_model.bind("<<ComboboxSelected>>", on_model_selected)
    attach_tooltip(l_mod, "model_photo"); attach_tooltip(cb_model, "model_photo")

    l_pre = ttk.Label(lf_flags, text="Preset:"); l_pre.grid(row=1, column=0, sticky="w", padx=4)
    cb_preset = ttk.Combobox(lf_flags, textvariable=v_preset, values=list(PHOTO_PRESETS.keys()), state="readonly")
    cb_preset.grid(row=1, column=1, columnspan=3, sticky="ew", padx=4, pady=2); cb_preset.bind("<<ComboboxSelected>>", on_preset)
    attach_tooltip(l_pre, "preset"); attach_tooltip(cb_preset, "preset")

    build_wh_row(lf_flags, v_width, v_height, refresh_cmd, row=2)
    for lbl, var, r, c, tkey in [("Steps:", v_steps, 3, 0, "steps"), ("CFG:", v_cfg, 3, 2, "cfg"), ("Seed:", v_seed, 4, 0, "seed")]:
        lw = ttk.Label(lf_flags, text=lbl); lw.grid(row=r, column=c, sticky="w", padx=4, pady=2)
        ent = ttk.Entry(lf_flags, textvariable=var, width=10)
        ent.grid(row=r, column=c + 1, sticky="ew", padx=4, pady=2); ent.bind("<KeyRelease>", refresh_cmd)
        attach_tooltip(lw, tkey); attach_tooltip(ent, tkey)

    chk_r = ttk.Checkbutton(lf_flags, text="Random Seed Each Run", variable=v_rand_seed); chk_r.grid(row=4, column=2, columnspan=2, sticky="w", padx=4)
    attach_tooltip(chk_r, "rand_seed")
    l_s = ttk.Label(lf_flags, text="Sampler:"); l_s.grid(row=5, column=0, sticky="w", padx=4, pady=2)
    sampler_vals = ["dpmpp_2m", "euler", "uni_pc"] if supports_ref else ["euler", "dpmpp_2m", "uni_pc"]
    cb_samp = ttk.Combobox(lf_flags, textvariable=v_sampler, values=sampler_vals, state="readonly")
    cb_samp.grid(row=5, column=1, sticky="ew", padx=4, pady=2); cb_samp.bind("<<ComboboxSelected>>", refresh_cmd)
    attach_tooltip(l_s, "sampler"); attach_tooltip(cb_samp, "sampler")
    l_sc = ttk.Label(lf_flags, text="Scheduler:"); l_sc.grid(row=5, column=2, sticky="w", padx=4, pady=2)
    sched_vals = ["karras", "simple", "normal"] if supports_ref else ["simple", "karras", "normal"]
    cb_sched = ttk.Combobox(lf_flags, textvariable=v_scheduler, values=sched_vals, state="readonly")
    cb_sched.grid(row=5, column=3, sticky="ew", padx=4, pady=2); cb_sched.bind("<<ComboboxSelected>>", refresh_cmd)
    attach_tooltip(l_sc, "scheduler"); attach_tooltip(cb_sched, "scheduler")
    l_on = ttk.Label(lf_flags, text="Output Name:"); l_on.grid(row=6, column=0, sticky="w", padx=4, pady=2)
    e_out = ttk.Entry(lf_flags, textvariable=v_outname); e_out.grid(row=6, column=1, columnspan=3, sticky="ew", padx=4, pady=2); e_out.bind("<KeyRelease>", refresh_cmd)
    attach_tooltip(l_on, "output_name"); attach_tooltip(e_out, "output_name")

    if supports_ref:
        l_ref = ttk.Label(lf_flags, text="Reference Image:"); l_ref.grid(row=7, column=0, sticky="w", padx=4, pady=2)
        ref_row = ttk.Frame(lf_flags); ref_row.grid(row=7, column=1, columnspan=3, sticky="ew", padx=4, pady=2)
        e_ref = ttk.Entry(ref_row, textvariable=v_ref_img); e_ref.pack(side="left", fill="x", expand=True); e_ref.bind("<KeyRelease>", refresh_cmd)
        b_rbr = ttk.Button(ref_row, text="Browse...", command=browse_ref_image); b_rbr.pack(side="left", padx=(4, 2))
        b_rcl = ttk.Button(ref_row, text="Clear", command=clear_ref_image); b_rcl.pack(side="left")
        attach_tooltip(l_ref, "ref_image"); attach_tooltip(e_ref, "ref_image"); attach_tooltip(b_rbr, "browse_ref"); attach_tooltip(b_rcl, "clear_ref")

        l_rm = ttk.Label(lf_flags, text="Extract / Style:"); l_rm.grid(row=8, column=0, sticky="w", padx=4, pady=2)
        rm_row = ttk.Frame(lf_flags); rm_row.grid(row=8, column=1, columnspan=3, sticky="ew", padx=4, pady=2)
        cb_rm = ttk.Combobox(rm_row, textvariable=v_ref_mode, values=[x[1] for x in REF_TARGET_OPTIONS], state="readonly", width=24)
        cb_rm.pack(side="left", fill="x", expand=True); cb_rm.bind("<<ComboboxSelected>>", refresh_cmd)
        cb_rs = ttk.Combobox(rm_row, textvariable=v_ref_style, values=[x[0] for x in REF_STYLE_OPTIONS], state="readonly", width=28)
        cb_rs.pack(side="left", fill="x", expand=True, padx=4); cb_rs.bind("<<ComboboxSelected>>", apply_ref_style)
        e_rw = ttk.Entry(rm_row, textvariable=v_ref_weight, width=5); e_rw.pack(side="left"); e_rw.bind("<KeyRelease>", refresh_cmd)
        attach_tooltip(l_rm, "ref_mode"); attach_tooltip(cb_rm, "ref_mode"); attach_tooltip(cb_rs, "ref_style"); attach_tooltip(e_rw, "ref_weight")

    l_prof = ttk.Label(lf_flags, text="Character Profile:"); l_prof.grid(row=9, column=0, sticky="w", padx=4, pady=2)
    prof_row = ttk.Frame(lf_flags); prof_row.grid(row=9, column=1, columnspan=3, sticky="ew", padx=4, pady=2)
    cb_profile = ttk.Combobox(prof_row, textvariable=v_profile, values=get_profile_dropdown_values(), state="readonly")
    cb_profile.pack(side="left", fill="x", expand=True); cb_profile.bind("<<ComboboxSelected>>", on_profile_selected)
    b_save_prof = ttk.Button(prof_row, text="👤 Save Selected...", command=open_save_profile_dialog); b_save_prof.pack(side="left", padx=(4, 2))
    b_del_prof = ttk.Button(prof_row, text="🗑", width=3, state="disabled", command=delete_active_profile); b_del_prof.pack(side="left")
    attach_tooltip(l_prof, "char_profile"); attach_tooltip(cb_profile, "char_profile")
    attach_tooltip(b_save_prof, "save_profile"); attach_tooltip(b_del_prof, "delete_profile")

    l_cmd = ttk.Label(lf_flags, text="CLI Command:"); l_cmd.grid(row=10, column=0, sticky="w", padx=4, pady=2)
    e_cmd = ttk.Entry(lf_flags, textvariable=v_cmd, state="readonly"); e_cmd.grid(row=10, column=1, columnspan=3, sticky="ew", padx=4, pady=2)
    attach_tooltip(l_cmd, "cli_cmd"); attach_tooltip(e_cmd, "cli_cmd")
    c_row = ttk.Frame(lf_flags); c_row.grid(row=11, column=0, columnspan=4, sticky="ew", padx=4, pady=(2, 0))
    ttk.Label(c_row, textvariable=v_compat, font=get_font("small_bold")).pack(side="left", fill="x", expand=True)
    b_un = ttk.Button(c_row, text="🔓 Unlock All", command=unlock_all_models); b_un.pack(side="right")
    attach_tooltip(b_un, "Clear compatibility restrictions and allow selecting every model manually.")

    lf_prompt = ttk.LabelFrame(left, text="Image Descriptions", padding=8)
    lf_prompt.grid(row=1, column=0, sticky="ew", pady=(0, 8)); lf_prompt.columnconfigure(0, weight=1)
    qbar = build_quick_bar(lf_prompt, lambda t: set_prompt(t, replace=True), lambda: on_open_builder and on_open_builder("photo"), include_motion=False)
    qbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))

    hdr_p = ttk.Frame(lf_prompt); hdr_p.grid(row=1, column=0, sticky="ew")
    l_pos = ttk.Label(hdr_p, text="Positive Description (--prompt):"); l_pos.pack(side="left"); attach_tooltip(l_pos, "prompt")
    for blbl, bpref, btkey in [("+ American Realistic Style", AMERICAN_REALISTIC_STYLE, "style_real_photo"), ("+ Green-Screen Character", ANIME_GREENSCREEN_CHAR_STYLE, "style_gs_photo"), ("+ Anime Background Style", ANIME_BG_STYLE, "style_bg_photo")]:
        b = ttk.Button(hdr_p, text=blbl, command=lambda p=bpref: (txt_prompt.insert("1.0", p), refresh_cmd()))
        b.pack(side="right", padx=(4, 0)); attach_tooltip(b, btkey)

    txt_prompt = tk.Text(lf_prompt, height=3, wrap="word", bg="#0a0f1f", fg="#eef2fc", insertbackground="#44e0ff", relief="flat", padx=6, pady=6, font=get_font("ui"))
    txt_prompt.grid(row=2, column=0, sticky="ew", pady=(4, 6))
    txt_prompt.insert("1.0", "60th-floor Fortune 500 corporate executive boardroom at dusk, long dark walnut table, leather chairs, floor-to-ceiling windows overlooking neon city skyline at twilight, crisp cel shading")
    txt_prompt.bind("<KeyRelease>", refresh_cmd); attach_tooltip(txt_prompt, "prompt")

    hdr_n = ttk.Frame(lf_prompt); hdr_n.grid(row=3, column=0, sticky="ew")
    l_neg = ttk.Label(hdr_n, text="Negative Prompt (--negative):"); l_neg.pack(side="left"); attach_tooltip(l_neg, "negative")

    txt_neg = tk.Text(lf_prompt, height=2, wrap="word", bg="#0a0f1f", fg="#cdd6ef", insertbackground="#44e0ff", relief="flat", padx=6, pady=4, font=get_font("ui"))
    txt_neg.grid(row=4, column=0, sticky="ew", pady=(2, 6)); txt_neg.insert("1.0", PHOTO_DEFAULT_NEGATIVE); txt_neg.bind("<KeyRelease>", refresh_cmd)
    attach_tooltip(txt_neg, "negative")
    neg_helper = addons.REGISTRY.desktop.get("photo_neg_helper")  # after txt_neg exists: the helper edits it
    if neg_helper:
        btn_cfg = neg_helper(txt_neg, refresh_cmd)
        b_helper = ttk.Button(hdr_n, text=btn_cfg["label"], command=btn_cfg["command"])
        b_helper.pack(side="right"); attach_tooltip(b_helper, btn_cfg["tooltip"])

    act = ttk.Frame(lf_prompt); act.grid(row=5, column=0, sticky="ew")
    btn_gen = ttk.Button(act, text="▶ Generate Photo(s)", style="Accent.TButton", command=start_generate); btn_gen.pack(side="left", padx=(0, 6))
    btn_cancel = ttk.Button(act, text="⏹ Cancel", state="disabled", command=cancel_generate); btn_cancel.pack(side="left", padx=(0, 10))
    attach_tooltip(btn_gen, "generate"); attach_tooltip(btn_cancel, "cancel")
    prog = ttk.Progressbar(act, mode="determinate", maximum=100, length=s(180)); prog.pack(side="left", padx=(0, 8))
    ttk.Label(act, textvariable=v_status).pack(side="left", fill="x", expand=True)

    lf_log = ttk.LabelFrame(left, text="Photo Generation Log", padding=6)
    lf_log.grid(row=2, column=0, sticky="nsew"); lf_log.rowconfigure(0, weight=1); lf_log.columnconfigure(0, weight=1)
    txt_log = tk.Text(lf_log, height=5, wrap="word", bg="#070a14", fg="#a7e9c4", state="disabled", relief="flat", font=get_font("mono"))
    txt_log._is_log = True
    txt_log.grid(row=0, column=0, sticky="nsew")

    ext_ctx = {
        "selected_path": selected_path, "selected_asset": selected_asset, "apply_recipe": apply_recipe,
        "txt_neg": txt_neg, "v_outname": v_outname, "compat_state": compat_state, "refresh_cmd": refresh_cmd,
        "v_status": v_status, "root": root, "extra_ctrls": extra_ctrls or [],
    }
    extra_action_builder = addons.REGISTRY.desktop.get("photo_output_actions")
    ext_actions = extra_action_builder(ext_ctx) if extra_action_builder else {"menu": [], "buttons": [], "send_target": None}
    send_target_spec = ext_actions.get("send_target")

    _photo_menu_items = [
        ("Open Image", open_selected_photo),
        ("Save Person as Character Profile...", open_save_profile_dialog),
        *([("Use Selected as Reference Photo", send_selected_to_reference)] if supports_ref else []),
        ("Import into Prompt Builder", import_selected),
        *ext_actions.get("menu", []),
        (_sc.get("select_menu", "Reveal in File Manager"), select_in_fm),
        (_sc.get("open_photos_menu", "Open Photos Folder"), open_folder_fm),
        *([(_sc.get("photo_menu_label", "Copy to Export Folder"), copy_to_export_bg)] if _export_bg_dir else []),
    ]
    next_row = 2
    _photo_buttons = [
        ("🖼 Open Image", open_selected_photo, 0, 0, 1, "TButton", "open_output"),
        (_sc.get("select_btn", "📂 Reveal File"), select_in_fm, 0, 1, 1, "TButton", _sc.get("tt_select", "select_file")),
        (_sc.get("open_photos_btn", "📁 Open Photos Folder"), open_folder_fm, 1, 0, 1 if _export_bg_dir else 2, "TButton", _sc.get("tt_folder", "open_folder")),
        *([(_sc.get("photo_copy_label", "🎬 Copy to Export"), copy_to_export_bg, 1, 1, 1, "TButton", _sc.get("tt_copy", "copy_export"))] if _export_bg_dir else []),
    ]
    if supports_ref or send_target_spec:
        if supports_ref:
            _photo_buttons.append(("🔁 Use as Reference Photo", send_selected_to_reference, next_row, 0, 1 if send_target_spec else 2, "Accent.TButton", "send_to_ref"))
        if send_target_spec:
            _photo_buttons.append((send_target_spec["label"], send_target_spec["command"], next_row, 1 if supports_ref else 0, 1 if supports_ref else 2, "Accent.TButton", send_target_spec["tooltip"]))
        next_row += 1

    extra_btns = ext_actions.get("buttons", [])
    _photo_buttons.append(("📥 Import into Prompt Builder", import_selected, next_row, 0, 1 if extra_btns else 2, "Accent.TButton",
                           "Put back everything this photo was made with: dropdowns, vision, Final prompt, model, size and seed."))
    for b_spec in extra_btns:
        _photo_buttons.append((b_spec["label"], b_spec["command"], next_row, 1, 1, "TButton", b_spec["tooltip"]))
    next_row += 1
    _photo_buttons.extend([
        ("👤 Save Person as Profile...", open_save_profile_dialog, next_row, 0, 1, "Accent.TButton", "save_profile"),
        ("🔄 Refresh List", refresh_photos, next_row, 1, 1, "TButton", "refresh_list"),
    ])

    _, tree, lbl_preview = build_outputs_panel(
        pane, root, "Generated Photos & Backgrounds", "Select a photo to preview",
        on_select_photo, open_selected_photo,
        _photo_menu_items,
        _photo_buttons,
    )

    def _on_photo_rescale(_scale):
        if prog.winfo_exists():
            prog.configure(length=s(180))
        on_select_photo()

    register_scale_listener(_on_photo_rescale)
    refresh_cmd(); refresh_photos()
    root.after(80, poll_queue)
    return {"refresh": refresh_photos, "open_selected": open_selected_photo, "select_file": select_in_fm, "open_folder": open_folder_fm,
            **({"copy_export": copy_to_export_bg} if _export_bg_dir else {}), "set_prompt": set_prompt,
            "get_prompt": lambda: txt_prompt.get("1.0", "end").strip(), "apply_recipe": apply_recipe}
