#!/usr/bin/env python3
"""Dark-themed Tkinter GUI wrapper for Graphical Studio."""

import argparse
import json
import os
import queue
import random
import re
import shlex
import shutil

import addons
import wan_library
from wan_builder_dialog import build_outputs_panel, build_quick_bar, open_builder_window
from wan_compat import evaluate_photo_compat, evaluate_video_compat
import wan_dpi
from wan_dpi import SCALE_OPTIONS, apply_ui_scale, fit_window_geometry, get_font, load_saved_scale, register_scale_listener, s
from wan_rectifier import rectify_freeform_prompt
from wan_prompt_catalog import ALL_FIELDS, ascertain_fields_from_prompt, assemble_builder_prompt, assemble_motion_only
from wan_studio_helpers import (
    ANIME_PREFIX, CAUTION_MODELS, DEFAULT_NEGATIVE, I2V_VERSIONS, MODEL_OPTIONS, OUTPUTS_DIR,
    VIDEO_MODEL_SETTINGS,
    PHOTOS_DIR, PRESETS, build_cli_command, build_photo_cli_command, duration_to_frames,
    extract_thumbnail, open_path_default, reveal_in_file_manager, scan_outputs,
    scan_photo_outputs, slugify_prompt, start_streaming_process,
)
from wan_photo_tab import build_photos_tab
from wan_themes import CAUTION_FG, THEME_CATEGORIES, THEMES_BY_ID, apply_theme, build_themes_tab, load_saved_theme_id
from wan_tooltips import TOOLTIPS, attach_tooltip, build_wh_row, pick_file_native


def _build_video_tab(tab_video, root, notebook, photo_api_getter, launch_builder, import_into_builder, v_status):
    import tkinter as tk
    from tkinter import messagebox, ttk
    from PIL import Image, ImageTk

    vui = addons.REGISTRY.video_ui_strings
    mprefix = vui.get("video_model_prefix", "Video")
    model_map = {label: ver for ver, label in MODEL_OPTIONS}
    v_model = tk.StringVar(value=MODEL_OPTIONS[0][1])
    v_preset = tk.StringVar(value=list(PRESETS.keys())[0])
    v_width, v_height = tk.IntVar(value=768), tk.IntVar(value=432)
    v_duration, v_fps = tk.DoubleVar(value=4.0), tk.IntVar(value=16)
    v_frames_info = tk.StringVar(value="-> 65f (4.06s)")
    v_steps, v_cfg, v_seed = tk.IntVar(value=20), tk.DoubleVar(value=5.0), tk.IntVar(value=42026)
    v_rand_seed = tk.BooleanVar(value=True)
    v_sampler, v_scheduler = tk.StringVar(value="uni_pc"), tk.StringVar(value="simple")
    v_outname, v_image, v_cmd = tk.StringVar(value=""), tk.StringVar(value=""), tk.StringVar(value="")
    v_compat = tk.StringVar(value="")
    compat_ctx = {"vals": None}
    proc_holder = {"proc": None, "out_path": None}
    log_q: queue.Queue = queue.Queue()
    video_turn = addons.desktop_session(root, lambda m: v_status.set(m))
    thumb_ref = {"photo": None}

    def get_cfg():
        return {
            "version": model_map.get(v_model.get(), "2.2"),
            "prompt": txt_prompt.get("1.0", "end").strip(),
            "negative": txt_neg.get("1.0", "end").strip(),
            "output_name": v_outname.get().strip(),
            "image": v_image.get().strip(),
            "width": v_width.get(), "height": v_height.get(),
            "duration_sec": v_duration.get(), "fps": v_fps.get(),
            "steps": v_steps.get(), "cfg": v_cfg.get(), "seed": v_seed.get(),
            "sampler": v_sampler.get(), "scheduler": v_scheduler.get(),
        }

    def refresh_cmd(*_):
        try:
            f_cnt, act_s = duration_to_frames(v_duration.get(), v_fps.get())
            v_frames_info.set(f"-> {f_cnt}f ({act_s}s)")
            v_cmd.set(shlex.join(build_cli_command(get_cfg())))
        except Exception:
            pass

    caution_labels = {label for ver, label in MODEL_OPTIONS if ver in CAUTION_MODELS}

    def mark_model_caution():
        cb_model.configure(style="Caution.TCombobox" if v_model.get() in caution_labels else "TCombobox")

    def colour_model_list():
        """Paint caution models red inside the open dropdown list too."""
        try:
            lb = f"{root.tk.call('ttk::combobox::PopdownWindow', cb_model)}.f.l"
            normal = root.tk.call(lb, "cget", "-foreground")
            for i, label in enumerate(cb_model["values"]):
                root.tk.call(lb, "itemconfigure", i, "-foreground", CAUTION_FG if label in caution_labels else normal)
        except tk.TclError:
            pass

    def on_model(*_):
        st = VIDEO_MODEL_SETTINGS.get(model_map.get(v_model.get(), "2.2"))
        if st:
            v_steps.set(st["steps"]); v_cfg.set(st["cfg"]); v_sampler.set(st["sampler"]); v_scheduler.set(st["scheduler"])
        mark_model_caution()
        refresh_cmd()

    def keep_i2v_model():
        if model_map.get(v_model.get()) not in I2V_VERSIONS:
            v_model.set(MODEL_OPTIONS[0][1])
        mark_model_caution()

    def on_preset(*_):
        w, h, sec, fps = PRESETS.get(v_preset.get(), (768, 432, 4.0, 16))
        v_width.set(w); v_height.set(h); v_duration.set(sec); v_fps.set(fps)
        refresh_cmd()

    def browse_start_image():
        path = pick_file_native(f"Select Start Image for {mprefix} 2.2 I2V", PHOTOS_DIR, "Images (*.jpg *.jpeg *.png *.webp);;All files (*)", [("Images", "*.jpg *.jpeg *.png *.webp"), ("All files", "*.*")])
        if path:
            v_image.set(path); keep_i2v_model()
            if compat_ctx["vals"]:
                apply_video_compat(compat_ctx["vals"])
            refresh_cmd()

    def clear_start_image():
        v_image.set("")
        if compat_ctx["vals"]:
            apply_video_compat(compat_ctx["vals"])
        refresh_cmd()

    def send_photo_to_i2v(img_path: str):
        v_image.set(img_path); keep_i2v_model()
        if compat_ctx["vals"]:
            apply_video_compat(compat_ctx["vals"])
        refresh_cmd(); notebook.select(tab_video)
        v_status.set(f"I2V start image set: {os.path.basename(img_path)}")

    def apply_video_compat(builder_vals: dict):
        compat_ctx["vals"] = dict(builder_vals)
        res = evaluate_video_compat(builder_vals, has_start_image=bool(v_image.get().strip()))
        cb_model["values"] = [lbl for _, lbl in res["allowed_models"]]
        v_model.set(res["allowed_models"][0][1]); mark_model_caution()
        cb_model.configure(state="disabled" if len(res["allowed_models"]) == 1 else "readonly")
        if res["best_preset"] in PRESETS:
            v_preset.set(res["best_preset"]); on_preset()
        v_cfg.set(res["best_cfg"]); v_steps.set(res["best_steps"])
        if res["neg_additions"]:
            cur_neg = txt_neg.get("1.0", "end").strip()
            missing = [t for t in res["neg_additions"] if t not in cur_neg.lower()]
            if missing:
                txt_neg.delete("1.0", "end"); txt_neg.insert("1.0", f"{cur_neg}, {', '.join(missing)}" if cur_neg else ", ".join(missing))
        if res["needs_start_image"]:
            btn_gen.configure(state="disabled")
            banner = addons.REGISTRY.video_compat_banner(res) if addons.REGISTRY.video_compat_banner else None
            v_compat.set(banner or "⛔ Needs Start Image (I2V) from Photos Tab (or click Unlock)")
        else:
            btn_gen.configure(state="normal")
            v_compat.set(f"✅ {mprefix} 2.2 selected" + (f" | ⛔ Restricted: {mprefix} 2.1" if res["restricted_models"] else ""))

    def unlock_video_all():
        compat_ctx["vals"] = None
        cb_model["values"] = [m[1] for m in MODEL_OPTIONS]
        cb_model.configure(state="readonly")
        btn_gen.configure(state="normal")
        v_compat.set("All video options unlocked (manual mode).")
        refresh_cmd()

    def apply_video_builder_settings(st: dict):
        label = next((lbl for ver, lbl in MODEL_OPTIONS if ver == st.get("version")), None)
        if label:
            v_model.set(label); mark_model_caution()
        if st.get("width") and st.get("height") and not v_image.get().strip():
            v_width.set(int(st["width"])); v_height.set(int(st["height"]))
        for var, key in ((v_duration, "duration"), (v_fps, "fps"), (v_steps, "steps"), (v_cfg, "cfg"),
                         (v_sampler, "sampler"), (v_scheduler, "scheduler")):
            if st.get(key) not in (None, ""):
                var.set(st[key])
        adds = st.get("neg_additions") or []
        cur_neg = txt_neg.get("1.0", "end").strip()
        missing = [t for t in adds if t not in cur_neg.lower()]
        if missing:
            txt_neg.delete("1.0", "end"); txt_neg.insert("1.0", f"{cur_neg}, {', '.join(missing)}" if cur_neg else ", ".join(missing))

    def apply_video_prompt(text: str, replace: bool = True, builder_vals: dict | None = None, vision: str = "",
                           settings: dict | None = None, builder: dict | None = None):
        if builder is not None or builder_vals:
            compat_ctx["builder"] = builder or wan_library.builder_state(builder_vals, vision, "video", text)
        elif replace:
            compat_ctx["builder"] = None
        if replace:
            txt_prompt.delete("1.0", "end"); txt_prompt.insert("1.0", text)
        else:
            cur = txt_prompt.get("1.0", "end").strip()
            txt_prompt.delete("1.0", "end"); txt_prompt.insert("1.0", f"{cur}, {text}" if cur else text)
        if builder_vals:
            apply_video_compat(builder_vals)
        if settings:
            apply_video_builder_settings(settings)
        refresh_cmd(); notebook.select(tab_video)
        v_status.set("Video prompt & settings updated from Builder.")

    def selected_path():
        sel = tree.selection()
        return tree.item(sel[0], "values")[3] if sel else None

    def import_selected_video():
        p = selected_path()
        if not p or not os.path.isfile(p):
            return messagebox.showinfo("No Selection", "Select a generated video first.")
        asset = wan_library.get(p)
        if not asset or not (asset.get("effective_prompt") or asset.get("builder")):
            return messagebox.showinfo("Nothing Saved", "Nothing is saved about how this video was made, so there's nothing to import.")
        st = asset.get("settings") or {}
        apply_video_prompt(asset.get("prompt") or asset["effective_prompt"], replace=True, builder=asset.get("builder"))
        apply_video_builder_settings({"version": st.get("version"), "width": st.get("width"), "height": st.get("height"),
                                      "duration": st.get("duration_sec"), "fps": st.get("fps"), "steps": st.get("steps"),
                                      "cfg": st.get("cfg"), "sampler": st.get("sampler"), "scheduler": st.get("scheduler")})
        if "negative" in st:
            txt_neg.delete("1.0", "end"); txt_neg.insert("1.0", st["negative"])
        if st.get("seed") is not None:
            v_seed.set(int(st["seed"])); v_rand_seed.set(False)
        ref = asset.get("reference") or ""
        v_image.set(ref if ref and os.path.isfile(ref) else "")
        refresh_cmd()
        if asset.get("builder"):
            import_into_builder(asset)
            v_status.set(f"Imported {os.path.basename(p)}: builder and form restored (same seed).")
        else:
            v_status.set(f"Imported {os.path.basename(p)}: exact prompt and settings (same seed); no builder state to restore.")

    def on_select_output(*_):
        p = selected_path()
        tpath = extract_thumbnail(p) if p else None
        if tpath and os.path.isfile(tpath):
            img = Image.open(tpath).convert("RGB")
            img.thumbnail((s(384), s(216)), Image.Resampling.LANCZOS)
            thumb_ref["photo"] = ImageTk.PhotoImage(img)
            lbl_thumb.configure(image=thumb_ref["photo"], text="")
        else:
            lbl_thumb.configure(image="", text="(Select a generated clip)")

    def refresh_outputs(select_file: str | None = None):
        tree.delete(*tree.get_children())
        rows = scan_outputs(OUTPUTS_DIR)
        target = None
        for idx, r in enumerate(rows):
            iid = tree.insert("", "end", values=(r["name"], r["size"], r["mtime"], r["path"]))
            if (select_file and os.path.abspath(r["path"]) == os.path.abspath(select_file)) or (not select_file and idx == 0):
                target = iid
        if target:
            tree.selection_set(target); tree.focus(target); on_select_output()

    def open_selected_video():
        p = selected_path()
        if not p or not os.path.isfile(p):
            return messagebox.showinfo("No Selection", "Select a generated .mp4 clip first.")
        open_path_default(p)

    _sc = addons.REGISTRY.private_desktop_shortcuts
    _export_cutscenes = _sc.get("cutscenes_dir", "")

    def select_in_fm():
        reveal_in_file_manager(selected_path(), OUTPUTS_DIR)

    def open_folder_fm():
        reveal_in_file_manager(None, OUTPUTS_DIR)

    def copy_to_export():
        if not _export_cutscenes:
            return
        p = selected_path()
        if not p or not os.path.isfile(p):
            return messagebox.showinfo("No Selection", "Select a generated .mp4 clip first.")
        os.makedirs(_export_cutscenes, exist_ok=True)
        shutil.copy2(p, os.path.join(_export_cutscenes, os.path.basename(p)))
        v_status.set(f"Copied {os.path.basename(p)} to {_sc.get('video_dest_desc', _export_cutscenes)}")

    def append_log(line: str):
        txt_log.configure(state="normal"); txt_log.insert("end", line); txt_log.see("end"); txt_log.configure(state="disabled")

    def start_generate():
        if proc_holder["proc"] is not None or video_turn.waiting:
            return
        if v_rand_seed.get():
            v_seed.set(random.randint(1000, 999999))
        cfg = get_cfg()
        typed_prompt = cfg["prompt"]
        cfg["prompt"], rect_notes = rectify_freeform_prompt(
            cfg["prompt"], priority_hints=compat_ctx.get("vals"), use_extra_llm=False,
        )
        out_path = slugify_prompt(cfg["prompt"], cfg["output_name"], cfg["version"])
        cfg["output"] = out_path
        cmd = build_cli_command(cfg)
        v_cmd.set(shlex.join(cmd))
        proc_holder["out_path"] = out_path
        builder = compat_ctx.get("builder") if typed_prompt else None
        proc_holder["pending_library"] = {
            "source": "desktop-builder" if builder else "desktop", "prompt": typed_prompt,
            "effective_prompt": cfg["prompt"], "settings": dict(cfg), "builder": builder, "reference": cfg.get("image") or "",
        }
        txt_log.configure(state="normal"); txt_log.delete("1.0", "end"); txt_log.configure(state="disabled")
        for rn in rect_notes:
            append_log(f"[Conflict Rectifier] {rn}\n")
        append_log(f"$ {shlex.join(cmd)}\n\n")
        btn_gen.configure(state="disabled"); btn_cancel.configure(state="normal")
        prog["value"] = 0

        def start_render():
            v_status.set(f"Generating {mprefix} {cfg['version']} cutscene...")
            proc_holder["proc"] = start_streaming_process(cmd, log_q)

        def not_started():
            btn_gen.configure(state="normal"); btn_cancel.configure(state="disabled")
            v_status.set("Cancelled before it started.")

        video_turn.run(f"video {os.path.basename(out_path)}", "exclusive", start_render, not_started)

    def cancel_generate():
        if video_turn.cancel():
            return
        proc = proc_holder.get("proc")
        if proc is not None and proc.poll() is None:
            proc.terminate(); append_log("\n[CANCELLED BY USER]\n"); v_status.set("Generation cancelled.")

    def poll_queue():
        try:
            while True:
                kind, payload = log_q.get_nowait()
                if kind == "line":
                    m = re.search(r"(\d+)/(\d+)\s*\[", payload)
                    if m:
                        cur, tot = int(m.group(1)), max(1, int(m.group(2)))
                        prog["value"] = min(100, int((cur / tot) * 100))
                        v_status.set(f"Sampling step {cur}/{tot}...")
                    elif not payload.endswith("%|"):
                        append_log(payload)
                elif kind == "done":
                    proc_holder["proc"] = None
                    video_turn.release()
                    btn_gen.configure(state="normal"); btn_cancel.configure(state="disabled")
                    if payload == 0:
                        prog["value"] = 100
                        v_status.set(f"Done: {os.path.basename(proc_holder['out_path'] or '')}")
                        if proc_holder.get("out_path") and proc_holder.get("pending_library"):
                            try:
                                wan_library.record(proc_holder["out_path"], **proc_holder["pending_library"])
                            except Exception as exc:
                                append_log(f"[Library] could not record: {exc}\n")
                        refresh_outputs(proc_holder.get("out_path"))
                    else:
                        v_status.set(f"Exited with code {payload}")
        except queue.Empty:
            pass
        root.after(80, poll_queue)

    main_pane = ttk.Frame(tab_video, padding=8)
    main_pane.pack(fill="both", expand=True)
    main_pane.columnconfigure(0, weight=3); main_pane.columnconfigure(1, weight=2); main_pane.rowconfigure(0, weight=1)

    left = ttk.Frame(main_pane)
    left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
    left.rowconfigure(2, weight=1); left.columnconfigure(0, weight=1)

    lf_flags = ttk.LabelFrame(left, text="Model & CLI Flags (8 GB RTX 5060 Ti)", padding=8)
    lf_flags.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    for c in range(4):
        lf_flags.columnconfigure(c, weight=1)

    l_mod = ttk.Label(lf_flags, text="Model (--version):"); l_mod.grid(row=0, column=0, sticky="w", padx=4)
    cb_model = ttk.Combobox(lf_flags, textvariable=v_model, values=[m[1] for m in MODEL_OPTIONS], state="readonly",
                            postcommand=colour_model_list)
    cb_model.grid(row=0, column=1, columnspan=3, sticky="ew", padx=4, pady=2); cb_model.bind("<<ComboboxSelected>>", on_model)
    attach_tooltip(l_mod, "model_video"); attach_tooltip(cb_model, "model_video")

    l_pre = ttk.Label(lf_flags, text="Preset:"); l_pre.grid(row=1, column=0, sticky="w", padx=4)
    cb_preset = ttk.Combobox(lf_flags, textvariable=v_preset, values=list(PRESETS.keys()), state="readonly")
    cb_preset.grid(row=1, column=1, columnspan=3, sticky="ew", padx=4, pady=2); cb_preset.bind("<<ComboboxSelected>>", on_preset)
    attach_tooltip(l_pre, "preset"); attach_tooltip(cb_preset, "preset")

    build_wh_row(lf_flags, v_width, v_height, refresh_cmd, row=2)
    for lbl, var, r, c, tkey in [("FPS:", v_fps, 3, 2, "fps"), ("Steps:", v_steps, 4, 0, "steps"), ("CFG:", v_cfg, 4, 2, "cfg"), ("Seed:", v_seed, 5, 0, "seed")]:
        lw = ttk.Label(lf_flags, text=lbl); lw.grid(row=r, column=c, sticky="w", padx=4, pady=2)
        ent = ttk.Entry(lf_flags, textvariable=var, width=10)
        ent.grid(row=r, column=c + 1, sticky="ew", padx=4, pady=2); ent.bind("<KeyRelease>", refresh_cmd)
        attach_tooltip(lw, tkey); attach_tooltip(ent, tkey)
    l_dur = ttk.Label(lf_flags, text="Duration (sec):"); l_dur.grid(row=3, column=0, sticky="w", padx=4, pady=2)
    dur_box = ttk.Frame(lf_flags); dur_box.grid(row=3, column=1, sticky="ew", padx=4, pady=2)
    e_dur = ttk.Entry(dur_box, textvariable=v_duration, width=6); e_dur.pack(side="left", fill="x", expand=True); e_dur.bind("<KeyRelease>", refresh_cmd)
    lbl_finfo = ttk.Label(dur_box, textvariable=v_frames_info, font=get_font("small")); lbl_finfo.pack(side="left", padx=(4, 0))
    attach_tooltip(l_dur, "duration_sec"); attach_tooltip(e_dur, "duration_sec"); attach_tooltip(lbl_finfo, "duration_sec")

    chk_r = ttk.Checkbutton(lf_flags, text="Random Seed Each Run", variable=v_rand_seed); chk_r.grid(row=5, column=2, columnspan=2, sticky="w", padx=4)
    attach_tooltip(chk_r, "rand_seed")
    l_s = ttk.Label(lf_flags, text="Sampler:"); l_s.grid(row=6, column=0, sticky="w", padx=4, pady=2)
    cb_samp = ttk.Combobox(lf_flags, textvariable=v_sampler, values=["uni_pc", "euler", "dpmpp_2m"], state="readonly")
    cb_samp.grid(row=6, column=1, sticky="ew", padx=4, pady=2); cb_samp.bind("<<ComboboxSelected>>", refresh_cmd)
    attach_tooltip(l_s, "sampler"); attach_tooltip(cb_samp, "sampler")
    l_sc = ttk.Label(lf_flags, text="Scheduler:"); l_sc.grid(row=6, column=2, sticky="w", padx=4, pady=2)
    cb_sched = ttk.Combobox(lf_flags, textvariable=v_scheduler, values=["simple", "normal", "karras"], state="readonly")
    cb_sched.grid(row=6, column=3, sticky="ew", padx=4, pady=2); cb_sched.bind("<<ComboboxSelected>>", refresh_cmd)
    attach_tooltip(l_sc, "scheduler"); attach_tooltip(cb_sched, "scheduler")
    l_on = ttk.Label(lf_flags, text="Output Name:"); l_on.grid(row=7, column=0, sticky="w", padx=4, pady=2)
    e_out = ttk.Entry(lf_flags, textvariable=v_outname); e_out.grid(row=7, column=1, columnspan=3, sticky="ew", padx=4, pady=2); e_out.bind("<KeyRelease>", refresh_cmd)
    attach_tooltip(l_on, "output_name"); attach_tooltip(e_out, "output_name")
    l_img = ttk.Label(lf_flags, text="Start Image (I2V):"); l_img.grid(row=8, column=0, sticky="w", padx=4, pady=2)
    img_row = ttk.Frame(lf_flags); img_row.grid(row=8, column=1, columnspan=3, sticky="ew", padx=4, pady=2)
    e_img = ttk.Entry(img_row, textvariable=v_image); e_img.pack(side="left", fill="x", expand=True); e_img.bind("<KeyRelease>", refresh_cmd)
    b_br = ttk.Button(img_row, text="Browse...", command=browse_start_image); b_br.pack(side="left", padx=(4, 2))
    b_cl = ttk.Button(img_row, text="Clear", command=clear_start_image); b_cl.pack(side="left")
    attach_tooltip(l_img, "start_image"); attach_tooltip(e_img, "start_image"); attach_tooltip(b_br, "browse_image"); attach_tooltip(b_cl, "clear_image")
    l_cmd = ttk.Label(lf_flags, text="CLI Command:"); l_cmd.grid(row=9, column=0, sticky="w", padx=4, pady=2)
    e_cmd = ttk.Entry(lf_flags, textvariable=v_cmd, state="readonly"); e_cmd.grid(row=9, column=1, columnspan=3, sticky="ew", padx=4, pady=2)
    attach_tooltip(l_cmd, "cli_cmd"); attach_tooltip(e_cmd, "cli_cmd")
    c_row = ttk.Frame(lf_flags); c_row.grid(row=10, column=0, columnspan=4, sticky="ew", padx=4, pady=(2, 0))
    ttk.Label(c_row, textvariable=v_compat, font=get_font("small_bold")).pack(side="left", fill="x", expand=True)
    b_un = ttk.Button(c_row, text="🔓 Unlock All", command=unlock_video_all); b_un.pack(side="right")
    attach_tooltip(b_un, "Clear compatibility restrictions and unlock all models and Generate button.")

    lf_prompt = ttk.LabelFrame(left, text="Scene Descriptions", padding=8)
    lf_prompt.grid(row=1, column=0, sticky="ew", pady=(0, 8)); lf_prompt.columnconfigure(0, weight=1)
    qbar = build_quick_bar(lf_prompt, lambda t: apply_video_prompt(t, replace=True), lambda: launch_builder("video"), include_motion=True)
    qbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
    hdr_p = ttk.Frame(lf_prompt); hdr_p.grid(row=1, column=0, sticky="ew")
    l_pos = ttk.Label(hdr_p, text="Positive Description (--prompt):"); l_pos.pack(side="left"); attach_tooltip(l_pos, "prompt")
    b_pref = ttk.Button(hdr_p, text="+ Anime VN Style Prefix", command=lambda: (txt_prompt.insert("1.0", ANIME_PREFIX), refresh_cmd())); b_pref.pack(side="right"); attach_tooltip(b_pref, "style_prefix_video")

    txt_prompt = tk.Text(lf_prompt, height=3, wrap="word", bg="#0a0f1f", fg="#eef2fc", insertbackground="#44e0ff", relief="flat", padx=6, pady=6, font=get_font("ui"))
    txt_prompt.grid(row=2, column=0, sticky="ew", pady=(4, 6))
    txt_prompt.insert("1.0", ANIME_PREFIX + "waist-up shot of a friend smiling warmly and waving goodbye on an evening street.")
    txt_prompt.bind("<KeyRelease>", refresh_cmd); attach_tooltip(txt_prompt, "prompt")

    l_neg = ttk.Label(lf_prompt, text="Negative Prompt (--negative):"); l_neg.grid(row=3, column=0, sticky="w"); attach_tooltip(l_neg, "negative")
    txt_neg = tk.Text(lf_prompt, height=2, wrap="word", bg="#0a0f1f", fg="#cdd6ef", insertbackground="#44e0ff", relief="flat", padx=6, pady=4, font=get_font("ui"))
    txt_neg.grid(row=4, column=0, sticky="ew", pady=(2, 6)); txt_neg.insert("1.0", DEFAULT_NEGATIVE); txt_neg.bind("<KeyRelease>", refresh_cmd); attach_tooltip(txt_neg, "negative")

    act_row = ttk.Frame(lf_prompt); act_row.grid(row=5, column=0, sticky="ew")
    btn_gen = ttk.Button(act_row, text="▶ Generate Cutscene", style="Accent.TButton", command=start_generate); btn_gen.pack(side="left", padx=(0, 6))
    btn_cancel = ttk.Button(act_row, text="⏹ Cancel", state="disabled", command=cancel_generate); btn_cancel.pack(side="left", padx=(0, 10))
    attach_tooltip(btn_gen, "generate"); attach_tooltip(btn_cancel, "cancel")
    prog = ttk.Progressbar(act_row, mode="determinate", maximum=100, length=s(180)); prog.pack(side="left", padx=(0, 8))
    ttk.Label(act_row, textvariable=v_status).pack(side="left", fill="x", expand=True)

    lf_log = ttk.LabelFrame(left, text="Generation Log", padding=6)
    lf_log.grid(row=2, column=0, sticky="nsew"); lf_log.rowconfigure(0, weight=1); lf_log.columnconfigure(0, weight=1)
    txt_log = tk.Text(lf_log, height=5, wrap="word", bg="#070a14", fg="#a7e9c4", state="disabled", relief="flat", font=get_font("mono"))
    txt_log._is_log = True
    txt_log.grid(row=0, column=0, sticky="nsew")

    _vid_menu = [
        ("Open / Play Video", open_selected_video),
        ("Import into Prompt Builder", import_selected_video),
        (_sc.get("select_menu", "Reveal in File Manager"), select_in_fm),
        (_sc.get("open_outputs_menu", "Open Outputs Folder"), open_folder_fm),
        *([(_sc.get("video_menu_label", "Copy to Export Folder"), copy_to_export)] if _export_cutscenes else []),
    ]
    _vid_btns = [
        ("▶ Open / Play Video", open_selected_video, 0, 0, 1, "TButton", "open_output"),
        (_sc.get("select_btn", "📂 Reveal File"), select_in_fm, 0, 1, 1, "TButton", _sc.get("tt_select", "select_file")),
        (_sc.get("open_outputs_btn", "📁 Open Outputs Folder"), open_folder_fm, 1, 0, 1 if _export_cutscenes else 2, "TButton", _sc.get("tt_folder", "open_folder")),
        *([(_sc.get("video_copy_label", "🎬 Copy to Export"), copy_to_export, 1, 1, 1, "TButton", _sc.get("tt_copy", "copy_export"))] if _export_cutscenes else []),
        ("📥 Import into Prompt Builder", import_selected_video, 2, 0, 2, "Accent.TButton", "Put back everything this clip was made with: dropdowns, vision, Final prompt, model, size and seed."),
        ("🔄 Refresh List", refresh_outputs, 3, 0, 2, "TButton", "refresh_list"),
    ]
    _, tree, lbl_thumb = build_outputs_panel(
        main_pane, root, "Generated Cutscenes & Files", "Select a video to preview frame",
        on_select_output, open_selected_video, _vid_menu, _vid_btns,
    )

    def _on_video_rescale(_scale):
        if prog.winfo_exists():
            prog.configure(length=s(180))
        on_select_output()

    register_scale_listener(_on_video_rescale)
    refresh_cmd(); refresh_outputs()
    root.after(80, poll_queue)
    return {
        "apply_prompt": apply_video_prompt,
        "get_prompt": lambda: txt_prompt.get("1.0", "end").strip(),
        "send_photo_to_i2v": send_photo_to_i2v,
        "start_generate": start_generate,
        "cancel_generate": cancel_generate,
        "active_api": {
            "open_selected": open_selected_video,
            "select_file": select_in_fm,
            "open_folder": open_folder_fm,
            **({"copy_export": copy_to_export} if _export_cutscenes else {}),
            "refresh": refresh_outputs,
        },
    }


def launch_app():
    import tkinter as tk
    from tkinter import ttk
    from PIL import Image, ImageTk

    video_enabled = addons.REGISTRY.video_enabled
    vui = addons.REGISTRY.video_ui_strings
    root = tk.Tk()
    root.title("Graphical Studio — Video & Image Generator (RTX 5060 Ti 8GB)" if video_enabled else "Graphical Studio — Image & Asset Studio")
    v_scale = tk.StringVar(value=load_saved_scale())
    apply_ui_scale(root, v_scale.get())
    fit_window_geometry(root, 1260, 880, 980, 680)
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "graphical_studio_icon.png")
    if os.path.isfile(icon_path):
        root._app_icon = ImageTk.PhotoImage(Image.open(icon_path))
        root.iconphoto(True, root._app_icon)
    v_theme = tk.StringVar(value=load_saved_theme_id())
    apply_theme(root, v_theme.get())
    v_status = tk.StringVar(value="Ready (RTX 5060 Ti 8GB configured)")

    def show_startup_status():
        """Status + models.json sync check, off the Tk thread."""
        import threading

        def worker():
            from wan_models import startup_notice

            parts = [addons.desktop_status_label() or ""]
            try:
                notice = startup_notice()
            except Exception as exc:
                notice = f"Model check failed: {exc}"
            if notice:
                parts.append(notice)
            root.after(0, v_status.set, " · ".join(p for p in parts if p))

        threading.Thread(target=worker, daemon=True).start()

    root.after(600, show_startup_status)

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=6, pady=6)
    tab_video = ttk.Frame(notebook) if video_enabled else None
    tab_photo = ttk.Frame(notebook)
    tab_assets = ttk.Frame(notebook)
    tab_themes = ttk.Frame(notebook)
    if tab_video is not None:
        notebook.add(tab_video, text=vui.get("video_tab_title", "🎬 Video Cutscenes"))
    notebook.add(tab_photo, text=addons.REGISTRY.photo_tab_title or "🖼 Photos & Images (FLUX / Qwen-Image)")
    notebook.add(tab_assets, text="✨ Asset Studio (Icons / Backgrounds / Textures)")
    notebook.add(tab_themes, text="🎨 Themes & Menu")

    photo_api_ref: dict = {}
    video_ctrl_ref: dict = {}

    def apply_photo_prompt(text: str, replace: bool = True, builder_vals: dict | None = None, vision: str = "",
                           settings: dict | None = None, builder: dict | None = None):
        photo_api_ref["api"]["set_prompt"](text, replace=replace, builder_vals=builder_vals, vision=vision,
                                           settings=settings, builder=builder)
        notebook.select(tab_photo)

    def launch_builder(_mode: str = "photo"):
        def get_active_prompt():
            if tab_video is not None and notebook.select() == str(tab_video):
                return video_ctrl_ref["ctrl"]["get_prompt"]()
            return photo_api_ref["api"]["get_prompt"]()
        apply_vid = video_ctrl_ref["ctrl"]["apply_prompt"] if tab_video is not None else None
        return open_builder_window(root, apply_vid, apply_photo_prompt, get_active_prompt=get_active_prompt)

    def import_into_builder(asset: dict):
        """Open the Prompt Builder with a library item's dropdowns, vision, target and Final prompt."""
        st = asset.get("settings") or {}
        win = launch_builder(asset["kind"])
        shown = {k: st.get(k) for k in ("model", "version", "steps", "cfg", "sampler", "scheduler", "fps", "width", "height")}
        shown["duration_sec"] = st.get("duration_sec")
        win._import_recipe(asset["builder"], shown, asset["kind"])

    def select_theme(tid: str):
        v_theme.set(tid)
        apply_theme(root, tid, persist=True)
        v_status.set(f"Theme applied: {THEMES_BY_ID[tid][1]}")

    def select_scale(pref: str):
        v_scale.set(pref)
        eff = apply_ui_scale(root, pref, persist=True)
        apply_theme(root, v_theme.get())
        fit_window_geometry(root, 1260, 880, 980, 680)
        v_status.set(f"UI scale set to {int(round(eff * 100))}% ({'Auto DPI' if pref == 'auto' else 'Manual'})")

    def step_scale(delta: float):
        nxt = max(0.70, min(2.25, round((wan_dpi.CURRENT_SCALE + delta) * 20.0) / 20.0))
        select_scale(f"{nxt:.2f}")

    if tab_video is not None:
        video_ctrl_ref["ctrl"] = _build_video_tab(
            tab_video, root, notebook, lambda: photo_api_ref["api"], launch_builder, import_into_builder, v_status,
        )

    build_themes_tab(tab_themes, root, v_theme, select_theme, scale_var=v_scale, on_select_scale=select_scale)
    on_send_i2v = video_ctrl_ref["ctrl"]["send_photo_to_i2v"] if tab_video is not None else None
    photo_api = build_photos_tab(tab_photo, root, on_send_to_i2v=on_send_i2v, on_open_builder=launch_builder,
                                 on_import_builder=import_into_builder)
    photo_api_ref["api"] = photo_api
    from wan_assets_tab import build_assets_tab
    assets_api = build_assets_tab(tab_assets, root)

    def active_api():
        sel = notebook.select()
        if sel == str(tab_assets):
            return assets_api
        if sel == str(tab_photo):
            return photo_api
        if tab_video is not None and sel == str(tab_video):
            return video_ctrl_ref["ctrl"]["active_api"]
        return photo_api

    _sc = addons.REGISTRY.private_desktop_shortcuts
    _export_cutscenes = _sc.get("cutscenes_dir", "") if video_enabled else ""
    menubar = tk.Menu(root, bg="#11192e", fg="#eef2fc", activebackground="#1d3566", activeforeground="#ffffff")
    m_file = tk.Menu(menubar, tearoff=0, bg="#11192e", fg="#eef2fc")
    if tab_video is not None:
        m_file.add_command(label="Generate Video Cutscene", command=video_ctrl_ref["ctrl"]["start_generate"])
        m_file.add_command(label="Cancel Video Run", command=video_ctrl_ref["ctrl"]["cancel_generate"])
        m_file.add_separator()
    m_file.add_command(label="Exit", command=root.destroy)
    menubar.add_cascade(label="File", menu=m_file)
    m_out = tk.Menu(menubar, tearoff=0, bg="#11192e", fg="#eef2fc")
    _out_menu = [
        ("Open / View Selected", "open_selected"),
        (_sc.get("select_menubar", "Reveal File in File Manager"), "select_file"),
        (_sc.get("open_outputs_menubar", "Open Outputs Folder"), "open_folder"),
        *([(_sc.get("video_menubar_label", "Copy to Export Folder"), "copy_export")] if _export_cutscenes else []),
        ("Refresh Outputs List", "refresh"),
    ]
    for lbl, key in _out_menu:
        m_out.add_command(label=lbl, command=lambda k=key: active_api().get(k, lambda: None)())
    menubar.add_cascade(label="Outputs", menu=m_out)
    m_themes = tk.Menu(menubar, tearoff=0)
    for cat_name, items in THEME_CATEGORIES:
        sub = tk.Menu(m_themes, tearoff=0)
        for tid, tname, _ in items:
            sub.add_radiobutton(label=tname, variable=v_theme, value=tid, command=lambda k=tid: select_theme(k))
        m_themes.add_cascade(label=cat_name, menu=sub)
    menubar.add_cascade(label="Themes", menu=m_themes)
    m_view = tk.Menu(menubar, tearoff=0)
    for skey, slbl in SCALE_OPTIONS:
        m_view.add_radiobutton(label=slbl, variable=v_scale, value=skey, command=lambda k=skey: select_scale(k))
    m_view.add_separator()
    m_view.add_command(label="Zoom In (Ctrl++)", command=lambda: step_scale(0.10))
    m_view.add_command(label="Zoom Out (Ctrl+-)", command=lambda: step_scale(-0.10))
    m_view.add_command(label="Reset to Auto DPI (Ctrl+0)", command=lambda: select_scale("auto"))
    menubar.add_cascade(label="View / Scale", menu=m_view)
    root.config(menu=menubar)
    root.bind_all("<Control-plus>", lambda *_: step_scale(0.10))
    root.bind_all("<Control-equal>", lambda *_: step_scale(0.10))
    root.bind_all("<Control-minus>", lambda *_: step_scale(-0.10))
    root.bind_all("<Control-0>", lambda *_: select_scale("auto"))
    apply_theme(root, v_theme.get())
    root.mainloop()


def run_self_test():
    built_photo = assemble_builder_prompt({"style": "Real: RAW photo", "symmetry": "High: symmetrical face"}, include_motion=False)
    assert built_photo == "RAW photo, symmetrical face"
    assert all(tkey in TOOLTIPS for _, _, tkey, _ in ALL_FIELDS), "Missing builder tooltips"
    assert THEME_CATEGORIES[0][0].startswith("Google Pixel") and len(THEMES_BY_ID) >= 15, "Invalid theme catalog"
    asc = ascertain_fields_from_prompt("RAW candid photo, 1woman, brunette waves, hazel eyes, cowboy shot, bedroom vlogging, warm genuine smile")
    assert "American Realistic" in asc["style"] and "Brunette" in asc["hair_color"] and "Waves" in asc["hair_style"] and "Hazel" in asc["eyes"] and "Cowboy" in asc["framing"] and "Bedroom" in asc["scene"]
    photos = [r["name"] for r in scan_photo_outputs(PHOTOS_DIR)]
    if addons.REGISTRY.video_enabled:
        import generate_photo  # noqa: F401
        cmd = build_cli_command({"version": "2.2", "prompt": "test hallway entrance", "width": 768, "height": 432, "duration_sec": 4.73, "fps": 16, "steps": 20, "image": "/tmp/start.jpg"})
        assert duration_to_frames(4.73, 16) == (77, 4.81) and "--frames" in cmd and "77" in cmd and "--image" in cmd and "/tmp/start.jpg" in cmd
        pcmd = build_photo_cli_command({"model": "all", "prompt": "boardroom dusk", "width": 1280, "height": 720, "steps": 28})
        assert "--model" in pcmd and "all" in pcmd and "--width" in pcmd and "1280" in pcmd
        built = assemble_builder_prompt({"style": "Real: RAW photo", "symmetry": "High: symmetrical face", "motion": "Wave: waving hand"}, include_motion=True)
        assert built.endswith("waving hand")
        assert assemble_motion_only({"motion": "Wave: waving hand", "camera_move": "Push: slow push-in"}) == "waving hand, slow push-in"
        rows = scan_outputs(OUTPUTS_DIR)
        names = [r["name"] for r in rows]
        thumbs = [extract_thumbnail(r["path"]) for r in rows[:2]]
        assert all(tp and os.path.isfile(tp) and os.path.getsize(tp) > 500 for tp in thumbs)
    if addons.REGISTRY.self_test_hook:
        addons.REGISTRY.self_test_hook()
    print(json.dumps({"self_test": "passed", "photos_found": photos, "tooltips_count": len(TOOLTIPS), "builder_sample": built_photo}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--self-test", action="store_true")
    known, _ = p.parse_known_args()
    run_self_test() if known.self_test else launch_app()
