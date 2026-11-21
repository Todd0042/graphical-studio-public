"""Quick-builder bar and full Scene & Person Builder dialog window."""

import random

import addons
from studio_prompt_catalog import (
    ALL_FIELDS,
    FIELD_BY_KEY,
    MOTION_FIELDS,
    PERSON_FIELDS,
    QUICK_PHOTO_KEYS,
    QUICK_VIDEO_KEYS,
    SCENE_ATTIRE_FIELDS,
    THEME_FIELDS,
    assemble_builder_prompt,
    ascertain_fields_from_prompt,
)
from studio_dpi import fit_window_geometry, get_font, s
from studio_tooltips import attach_tooltip
from studio_templates import auto_save_template, delete_template, get_template, load_templates, save_template


def build_quick_bar(parent, on_apply_text, on_open_full_builder, include_motion: bool = False):
    """Build a compact quick-pick prompt dropdown bar."""
    import tkinter as tk
    from tkinter import ttk

    extra_active = bool(include_motion and MOTION_FIELDS)
    lf = ttk.LabelFrame(
        parent,
        text="Quick Scene, Person & Motion Builder (Hover any item for help)" if extra_active
        else "Quick Scene & Person Builder (Hover any item for help)",
        padding=6,
    )
    keys = QUICK_VIDEO_KEYS if extra_active else QUICK_PHOTO_KEYS
    vars_map = {}

    grid = ttk.Frame(lf)
    grid.pack(fill="x")
    for idx, key in enumerate(keys):
        _, label, tkey, opts = FIELD_BY_KEY[key]
        r, c = divmod(idx, 3)
        cell = ttk.Frame(grid)
        cell.grid(row=r, column=c, sticky="ew", padx=3, pady=2)
        grid.columnconfigure(c, weight=1)
        lbl = ttk.Label(cell, text=f"{label}:", font=get_font("small_bold"))
        lbl.pack(anchor="w")
        var = tk.StringVar(value=opts[0])
        vars_map[key] = var
        cb = ttk.Combobox(cell, textvariable=var, values=opts, state="normal", width=22)
        cb.pack(fill="x")
        attach_tooltip(lbl, tkey)
        attach_tooltip(cb, tkey)

    def apply_quick():
        text = assemble_builder_prompt({k: v.get() for k, v in vars_map.items()}, include_motion=extra_active)
        if text:
            on_apply_text(text)

    def clear_quick():
        for key, var in vars_map.items():
            var.set(FIELD_BY_KEY[key][3][0])

    bar = ttk.Frame(lf)
    bar.pack(fill="x", pady=(4, 0))
    btn_apply = ttk.Button(bar, text="✨ Insert Quick Picks", command=apply_quick)
    btn_apply.pack(side="left", padx=(0, 6))
    attach_tooltip(btn_apply, "apply_quick_builder")

    btn_clear = ttk.Button(bar, text="🧹 Reset", command=clear_quick)
    btn_clear.pack(side="left", padx=(0, 6))
    attach_tooltip(btn_clear, "builder_clear")

    btn_full_lbl = addons.REGISTRY.desktop.get("builder_full_btn_label") or "🛠 Open Full Scene & Person Builder (All Traits)..."
    btn_full = ttk.Button(bar, text=btn_full_lbl, style="Accent.TButton", command=on_open_full_builder)
    btn_full.pack(side="right")
    attach_tooltip(btn_full, "open_builder")
    return lf


def _add_group_box(parent, title: str, fields, vars_map, on_change):
    import tkinter as tk
    from tkinter import ttk

    box = ttk.LabelFrame(parent, text=title, padding=8)
    box.columnconfigure(1, weight=1)
    for row, (key, label, tkey, opts) in enumerate(fields):
        lbl = ttk.Label(box, text=f"{label}:")
        lbl.grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        var = vars_map.setdefault(key, tk.StringVar(value=opts[0]))
        cb = ttk.Combobox(box, textvariable=var, values=opts, state="normal")
        cb.grid(row=row, column=1, sticky="ew", pady=3)
        cb.bind("<<ComboboxSelected>>", on_change)
        cb.bind("<KeyRelease>", on_change)
        attach_tooltip(lbl, tkey)
        attach_tooltip(cb, tkey)
    return box


def open_builder_window(root, extra_apply_targets, on_apply_photo, get_active_prompt=None):
    """Open or focus the full Scene & Person Builder Toplevel window."""
    import tkinter as tk
    from tkinter import ttk
    from studio_tooltips import CURRENT_PALETTE

    existing = getattr(root, "_studio_builder_win", None)
    if existing is not None and existing.winfo_exists():
        existing.deiconify()
        existing.lift()
        existing.focus_force()
        return existing

    extra_targets = list(addons.REGISTRY.desktop.get("builder_targets") or [])
    extra_section = bool(MOTION_FIELDS)
    p = CURRENT_PALETTE
    win = tk.Toplevel(root)
    root._studio_builder_win = win
    win.title(addons.REGISTRY.desktop.get("builder_title") or "🛠 Graphical Studio — Full Scene & Person Builder")
    fit_window_geometry(win, 1180, 960, 940, 720)
    win.configure(bg=p["bg"])

    vars_map: dict[str, tk.StringVar] = {}
    v_notes = tk.StringVar(value="")

    # ── Template bar (top) ──
    tpl_bar = ttk.Frame(win, padding=(10, 10, 10, 0))
    tpl_bar.pack(fill="x")
    lbl_tpl = ttk.Label(tpl_bar, text="Template:", font=get_font("small_bold"))
    lbl_tpl.pack(side="left", padx=(0, 6))
    v_template = tk.StringVar(value="")
    cb_template = ttk.Combobox(tpl_bar, textvariable=v_template, state="readonly", width=48)
    cb_template.pack(side="left", fill="x", expand=True, padx=(0, 6))
    attach_tooltip(lbl_tpl, "builder_template")
    attach_tooltip(cb_template, "builder_template")

    def reload_templates(select: str | None = None):
        names = [t["name"] for t in load_templates()]
        cb_template.configure(values=names)
        if select is not None and select in names:
            v_template.set(select)
        elif v_template.get() not in names:
            v_template.set(names[0] if names else "")

    # ── Presets ──
    from studio_presets import PRESETS

    preset_bar = ttk.LabelFrame(win, text="Presets (set only their own dropdowns; the rest stay as you left them)", padding=(8, 4))
    preset_bar.pack(fill="x", padx=10, pady=(8, 0))

    def apply_preset_clicked(preset: dict):
        for key, val in preset["values"].items():
            if key in vars_map:
                vars_map[key].set(val)
        refresh_preview()
        labels = ", ".join(FIELD_BY_KEY[k][1] for k in preset["values"])
        scope["v_rect_info"].set(f"🎛 Preset '{preset['name']}' set {labels}. Everything else unchanged.")

    for i, preset in enumerate(PRESETS):
        b = ttk.Button(preset_bar, text=preset["name"], command=lambda pr=preset: apply_preset_clicked(pr))
        b.grid(row=i // 5, column=i % 5, sticky="ew", padx=3, pady=2)
        attach_tooltip(b, preset["about"])
    for c in range(5):
        preset_bar.columnconfigure(c, weight=1)

    outer = ttk.Frame(win, padding=10)
    outer.pack(fill="both", expand=True)
    outer.columnconfigure(0, weight=1)
    outer.columnconfigure(1, weight=1)
    outer.rowconfigure(0, weight=1)

    col_left = ttk.Frame(outer)
    col_left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
    col_left.columnconfigure(0, weight=1)

    col_right = ttk.Frame(outer)
    col_right.grid(row=0, column=1, sticky="nsew")
    col_right.columnconfigure(0, weight=1)

    scope: dict = {}

    def refresh_preview(*_):
        from studio_rectifier import rectify_builder_fields

        if "txt_prev" not in scope:
            return
        vals = {k: v.get() for k, v in vars_map.items()}
        extras = [("extra_notes", v_notes.get().strip())] if v_notes.get().strip() else None
        assembled, notes = rectify_builder_fields(vals, extra_clauses=extras, include_motion=(scope["v_target"].get() != "photo"))
        txt_prev = scope["txt_prev"]
        txt_prev.configure(state="normal")
        txt_prev.delete("1.0", "end")
        if assembled:
            txt_prev.insert("1.0", assembled)
        txt_prev.configure(state="disabled")
        scope["mark_stale"]()
        if notes:
            scope["v_rect_info"].set(f"⚖ Rectifier fixed {len(notes)} conflict(s): " + " | ".join(notes[:2]))
        else:
            scope["v_rect_info"].set("⚖ Conflict Rectifier: clean (no conflicting dropdown tags)")

    _add_group_box(col_left, "1. Theme, Style & Camera", THEME_FIELDS, vars_map, refresh_preview).pack(fill="x", pady=(0, 8))
    _add_group_box(col_left, "3. Attire, Pose, Props & Location", SCENE_ATTIRE_FIELDS, vars_map, refresh_preview).pack(
        fill="both" if not extra_section else "x", expand=not extra_section, pady=(0, 8 if extra_section else 0),
    )
    if extra_section:
        sec4 = addons.REGISTRY.desktop.get("builder_section4_title") or "4. Extra Action & Motion"
        _add_group_box(col_left, sec4, MOTION_FIELDS, vars_map, refresh_preview).pack(fill="both", expand=True)
    _add_group_box(col_right, "2. Person Characteristics", PERSON_FIELDS, vars_map, refresh_preview).pack(fill="both", expand=True)

    bottom = ttk.LabelFrame(outer, text="Vision, Preview & Final Prompt", padding=8)
    bottom.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    bottom.columnconfigure(1, weight=1)

    from studio_models import prompt_llm_options
    from studio_themes import CAUTION_FG

    ui = addons.llm_ui_strings()
    llm_res_key = ui["result_model_key"]

    top_row = ttk.Frame(bottom)
    top_row.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
    v_target = tk.StringVar(value="photo")
    if extra_targets:
        ttk.Label(top_row, text="Building for:", font=get_font("small_bold")).pack(side="left", padx=(0, 6))
        for val, lbl in [("photo", "🖼 Photo")] + extra_targets:
            ttk.Radiobutton(top_row, text=lbl, value=val, variable=v_target, command=lambda: on_target()).pack(side="left", padx=(0, 8))
    llm_opts = prompt_llm_options()
    llm_by_label = {(d["label"] if d["installed"] else f"{d['label']} (not installed: --llm-sync)"): d for d in llm_opts}
    llm_labels = list(llm_by_label)
    v_llm = tk.StringVar(value=next((lbl for lbl, d in llm_by_label.items() if d["default"] and d["installed"]),
                                    next((lbl for lbl, d in llm_by_label.items() if d["installed"]), llm_labels[0])))
    cb_llm = ttk.Combobox(top_row, textvariable=v_llm, values=llm_labels, state="readonly", width=46)
    cb_llm.pack(side="right")
    ttk.Label(top_row, text=f"{ui['picker_label']}:", font=get_font("small_bold")).pack(side="right", padx=(12, 6))
    attach_tooltip(cb_llm, ui["desktop_picker_tooltip"])

    def on_llm(*_):
        d = llm_by_label.get(v_llm.get())
        cb_llm.configure(style="Caution.TCombobox" if d and d["caution"] else "TCombobox")

    def colour_llm_list():
        try:
            lb = f"{win.tk.call('ttk::combobox::PopdownWindow', cb_llm)}.f.l"
            normal = win.tk.call(lb, "cget", "-foreground")
            for i, lbl in enumerate(llm_labels):
                win.tk.call(lb, "itemconfigure", i, "-foreground", CAUTION_FG if llm_by_label[lbl]["caution"] else normal)
        except tk.TclError:
            pass

    cb_llm.configure(postcommand=colour_llm_list)
    cb_llm.bind("<<ComboboxSelected>>", on_llm)
    on_llm()

    lbl_notes = ttk.Label(bottom, text="Your vision:")
    lbl_notes.grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(0, 6))
    e_notes = ttk.Entry(bottom, textvariable=v_notes)
    e_notes.grid(row=1, column=1, sticky="ew", pady=(0, 6))
    e_notes.bind("<KeyRelease>", refresh_preview)
    attach_tooltip(lbl_notes, "builder_notes")
    attach_tooltip(e_notes, "builder_notes")

    fill_row = ttk.Frame(bottom)
    fill_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 6))
    v_fill_replace = tk.BooleanVar(value=False)
    btn_fill = ttk.Button(fill_row, text="✨ Fill dropdowns from my vision", command=lambda: fill_from_vision_clicked())
    btn_fill.pack(side="left")
    ttk.Checkbutton(fill_row, text="Replace my picks too", variable=v_fill_replace).pack(side="left", padx=(8, 0))
    attach_tooltip(btn_fill, ui["fill_tooltip"])

    ttk.Label(bottom, text=ui["preview_label"], font=get_font("small_bold")).grid(row=3, column=0, columnspan=2, sticky="w")
    txt_prev = tk.Text(bottom, height=3, wrap="word", bg=p["panel"], fg=p["fg"], relief="flat", padx=6, pady=6, font=get_font("ui"))
    txt_prev.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 4))
    attach_tooltip(txt_prev, "What your dropdowns and vision make right now. Read-only: edit the Final prompt after reconciling.")
    v_rect_info = tk.StringVar(value="⚖ Conflict Rectifier: ready")
    ttk.Label(bottom, textvariable=v_rect_info, font=get_font("small_bold")).grid(row=5, column=0, columnspan=2, sticky="w", pady=(0, 6))

    rec_row = ttk.Frame(bottom)
    rec_row.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(0, 6))
    btn_reconcile = ttk.Button(rec_row, text=ui["reconcile_btn"], style="Accent.TButton", command=lambda: reconcile_clicked())
    btn_reconcile.pack(side="left")
    v_rec_status = tk.StringVar(value="")
    ttk.Label(rec_row, textvariable=v_rec_status, font=get_font("small_bold")).pack(side="left", padx=(10, 0), fill="x", expand=True)

    ttk.Label(bottom, text="Final prompt (edit freely; this exact text is sent):", font=get_font("small_bold")).grid(row=7, column=0, columnspan=2, sticky="w")
    txt_final = tk.Text(bottom, height=4, wrap="word", bg=p["input_bg"], fg=p["fg"], insertbackground=p["accent"], relief="flat", padx=6, pady=6, font=get_font("ui"))
    txt_final.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(0, 4))
    attach_tooltip(txt_final, "prompt")
    v_final_info = tk.StringVar(value="Reconcile to fill this in.")
    ttk.Label(bottom, textvariable=v_final_info, font=get_font("small"), wraplength=1000).grid(row=9, column=0, columnspan=2, sticky="w", pady=(0, 6))
    rec_state = {"result": None, "snapshot": None, "busy": False}

    def get_vals():
        return {k: v.get() for k, v in vars_map.items()}

    def snapshot():
        return (v_target.get(), tuple(sorted(get_vals().items())), v_notes.get().strip())

    def mark_stale(*_):
        if rec_state["result"] and rec_state["snapshot"] != snapshot():
            v_rec_status.set("⚠ Dropdowns or vision changed since reconciling: Reconcile again (replaces your edits) or send as is.")

    def chosen_llm() -> str:
        d = llm_by_label.get(v_llm.get())
        return d["name"] if d else ""

    def run_llm_job(label: str, work, done):
        """Run LLM work off the Tk thread."""
        import threading
        from studio_models import resolve_prompt_llm

        if rec_state["busy"]:
            return
        rec_state["busy"] = True
        for b in (btn_fill, btn_reconcile):
            b.configure(state="disabled")
        v_rec_status.set(f"{ui['status_icon']} {label}...")

        def worker():
            notes: list[str] = []
            model, why = resolve_prompt_llm(chosen_llm())
            if why:
                notes.append(why)
            try:
                with addons.execution_session(f"builder {label}", needs=f"ollama:{model}" if model else "none",
                                              on_status=lambda m: root.after(0, v_rec_status.set, f"⏳ {m}")):
                    result = work(model)
            except (addons.session_error(), OSError) as exc:
                unavail = addons.REGISTRY.session.get("unavailable_note") or "Execution session unavailable"
                notes.append(f"{unavail} ({exc}); used the Python fallback without {ui['actor_name']}.")
                result = work(None)
            except Exception as exc:
                result, notes = None, notes + [f"⚠ {label} failed: {exc}"]

            def finish():
                rec_state["busy"] = False
                if not win.winfo_exists():
                    return
                for b in (btn_fill, btn_reconcile):
                    b.configure(state="normal")
                done(result, notes)

            root.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def fill_from_vision_clicked():
        from studio_vibe import fill_from_vision

        vision = v_notes.get().strip()
        if not vision:
            v_rec_status.set("⚠ Write your vision first.")
            return
        vals, replace = get_vals(), v_fill_replace.get()

        def done(result, notes):
            if not result:
                v_rec_status.set(" | ".join(notes) or "⚠ Fill failed.")
                return
            values, fill_notes = result
            apply_values(values, None, lambda: (v_rec_status.set(" | ".join(notes + fill_notes) + " Review the dropdowns, then Reconcile."), mark_stale()))

        run_llm_job("Filling dropdowns from your vision",
                    lambda model: fill_from_vision(vals, vision, replace=replace, use_llm=bool(model), model=model), done)

    def reconcile_clicked():
        from studio_reconcile import reconcile_for_target

        vals, vision, target, snap = get_vals(), v_notes.get().strip(), v_target.get(), snapshot()

        def done(result, notes):
            if not result:
                v_rec_status.set(" | ".join(notes) or "⚠ Reconcile failed.")
                return
            show_reconciled(result, notes + result["notes"], snap)
            v_rec_status.set("⚠ Refused by LLM safety filter." if result.get("refused") else "✅ Reconciled. Edit the Final prompt if you like, then Send.")

        run_llm_job("Reconciling", lambda model: reconcile_for_target(vals, vision, target, model), done)

    def show_reconciled(result: dict, notes: list[str], snap):
        rec_state.update(result=result, snapshot=snap)
        txt_final.delete("1.0", "end")
        txt_final.insert("1.0", result["prompt"])
        fmt_summary = addons.REGISTRY.desktop.get("format_target_summary")
        summary = fmt_summary(result) if (result["target"] != "photo" and fmt_summary) else (
            f"{result['model']}, {result['steps']} steps, CFG {result['cfg']}, {result['sampler']}/{result['scheduler']}"
        )
        by_val = result.get(llm_res_key) or result.get("llm") or ""
        by = f" · reconciled by {by_val}" if by_val else ""
        v_final_info.set(f"Will use {summary}{by}" + (f"\n{' | '.join(notes)}" if notes else ""))

    def on_target():
        labels = addons.REGISTRY.desktop.get("builder_send_labels", {})
        btn_send.configure(text=labels.get(v_target.get(), "🖼 Send to Photos Tab"))
        refresh_preview()
        mark_stale()

    def autosave(kind: str):
        try:
            saved = auto_save_template(kind, get_vals(), v_notes.get().strip())
        except OSError as exc:
            v_rect_info.set(f"⚠ Could not save template: {exc}")
            return
        reload_templates(select=saved)

    apply_state = {"busy": False}

    def set_busy(busy: bool):
        apply_state["busy"] = busy
        for b in tpl_buttons + send_buttons:
            b.configure(state="disabled" if busy else "normal")

    def apply_values(values: dict, notes: str | None, on_done=None):
        """Set every dropdown one at a time (letting Tk settle between each), then the custom text, then refresh."""
        queue = [(key, values.get(key, opts[0])) for key, _, _, opts in ALL_FIELDS]
        set_busy(True)

        def step(i: int = 0):
            if not win.winfo_exists():
                apply_state["busy"] = False
                return
            if i < len(queue):
                key, val = queue[i]
                vars_map[key].set(val)
                win.update_idletasks()
                win.after(10, step, i + 1)
                return
            if notes is not None:
                v_notes.set(notes)
            win.update_idletasks()
            refresh_preview()
            set_busy(False)
            if on_done:
                on_done()

        step()

    def apply_template():
        if apply_state["busy"]:
            return
        tpl = get_template(v_template.get())
        if not tpl:
            v_rect_info.set("⚠ Select a template to apply.")
            return
        v_rect_info.set(f"📋 Applying template '{tpl['name']}'...")
        apply_values(tpl.get("values", {}), tpl.get("notes", ""), lambda: v_rect_info.set(f"📋 Applied template '{tpl['name']}'."))

    def save_template_as():
        dlg = tk.Toplevel(win)
        dlg.title("Save Template")
        dlg.configure(bg=p["bg"])
        dlg.transient(win)
        dlg.resizable(False, False)
        frm = ttk.Frame(dlg, padding=12)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="Template name:").grid(row=0, column=0, sticky="w")
        v_name = tk.StringVar(value="" if v_template.get().startswith("Auto ·") else v_template.get())
        ent = ttk.Entry(frm, textvariable=v_name, width=40)
        ent.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 10))
        v_err = tk.StringVar(value="")
        ttk.Label(frm, textvariable=v_err, font=get_font("small_bold")).grid(row=2, column=0, columnspan=2, sticky="w")

        def do_save(*_):
            from tkinter import messagebox

            name = v_name.get().strip()
            if not name:
                v_err.set("Enter a name.")
                return
            if get_template(name) and not messagebox.askyesno("Overwrite Template", f"Template '{name}' already exists. Overwrite it?", parent=dlg):
                return
            try:
                save_template(name, get_vals(), v_notes.get().strip())
            except OSError as exc:
                v_err.set(f"Save failed: {exc}")
                return
            reload_templates(select=name)
            v_rect_info.set(f"💾 Saved template '{name}'.")
            dlg.destroy()

        btn_row = ttk.Frame(frm)
        btn_row.grid(row=3, column=0, columnspan=2, sticky="e", pady=(6, 0))
        ttk.Button(btn_row, text="Save", style="Accent.TButton", command=do_save).pack(side="left", padx=(0, 6))
        ttk.Button(btn_row, text="Cancel", command=dlg.destroy).pack(side="left")
        ent.bind("<Return>", do_save)
        dlg.bind("<Escape>", lambda *_: dlg.destroy())
        dlg.update_idletasks()
        dlg.geometry(f"+{win.winfo_rootx() + 80}+{win.winfo_rooty() + 60}")
        dlg.grab_set()
        ent.focus_set()

    def delete_selected_template():
        from tkinter import messagebox

        name = v_template.get()
        if not name:
            return
        if messagebox.askyesno("Delete Template", f"Delete template '{name}'?", parent=win):
            delete_template(name)
            v_template.set("")
            reload_templates()
            v_rect_info.set(f"🗑 Deleted template '{name}'.")

    tpl_buttons = []
    for label, fn, sty, tkey in (
        ("📋 Apply", apply_template, "Accent.TButton", "builder_template_apply"),
        ("💾 Save Template As...", save_template_as, "TButton", "builder_template_save"),
        ("🗑 Delete Template", delete_selected_template, "TButton", "builder_template_delete"),
    ):
        b = ttk.Button(tpl_bar, text=label, style=sty, command=fn)
        b.pack(side="left", padx=(0, 6))
        attach_tooltip(b, tkey)
        tpl_buttons.append(b)
    reload_templates()

    def send_final():
        if apply_state["busy"]:
            return
        res = rec_state["result"]
        final = txt_final.get("1.0", "end").strip()
        if not res or not final:
            v_rec_status.set("⚠ Reconcile first.")
            return
        target = res["target"]
        autosave(target.capitalize())
        from studio_library import builder_state

        vals = dict(rec_state["snapshot"][1])
        builder = builder_state(vals, rec_state["snapshot"][2], target, res["prompt"], final_prompt=final,
                                llm=res.get(llm_res_key) or res.get("llm") or "")
        apply = extra_apply_targets.get(target, on_apply_photo)
        apply(final, replace=True, builder_vals=vals, settings=res, builder=builder)

    def pick_random():
        for key, _, _, opts in ALL_FIELDS:
            vars_map[key].set(random.choice(opts[1:]) if len(opts) > 1 else opts[0])
        refresh_preview()

    def clear_all():
        for key, _, _, opts in ALL_FIELDS:
            vars_map[key].set(opts[0])
        v_notes.set("")
        refresh_preview()

    def ascertain_from_prompt():
        src = (get_active_prompt() if get_active_prompt else "") or txt_final.get("1.0", "end").strip()
        if not src:
            return
        matched = ascertain_fields_from_prompt(src)
        for key, val in matched.items():
            if key in vars_map:
                vars_map[key].set(val)
        refresh_preview()

    btns = ttk.Frame(bottom)
    btns.grid(row=10, column=0, columnspan=2, sticky="ew")
    btn_send = ttk.Button(btns, text="🖼 Send to Photos Tab", style="Accent.TButton", command=send_final)
    btn_send.pack(side="left", padx=(0, 6))
    attach_tooltip(btn_send, "Sends the Final prompt exactly as edited, with the auto-picked model and settings.")
    send_buttons = [btn_send, btn_fill, btn_reconcile]

    extra_builder_btns = []
    for act_spec in addons.REGISTRY.desktop.get("extra_builder_actions", ()):
        fn = act_spec["factory"](get_vals=get_vals, v_notes=v_notes, extra_apply_targets=extra_apply_targets)
        extra_builder_btns.append((act_spec["label"], fn, "TButton", act_spec["tooltip"]))

    extra_btns = (
        *extra_builder_btns,
        ("🔍 Ascertain From Prompt", ascertain_from_prompt, "TButton", "builder_ascertain"),
        ("🎲 Sample Mix", pick_random, "TButton", "builder_random"),
        ("🧹 Clear All", clear_all, "TButton", "builder_clear"),
    )
    for label, fn, sty, tkey in extra_btns:
        b = ttk.Button(btns, text=label, style=sty, command=fn)
        b.pack(side="left", padx=(0, 6))
        attach_tooltip(b, tkey)
    ttk.Button(btns, text="Close", command=win.destroy).pack(side="right")

    def import_recipe(builder: dict, settings: dict, kind: str):
        """Import into Prompt Builder (desktop gallery): dropdowns, vision, target and Final prompt."""
        v_target.set(kind)
        d_name = builder.get(llm_res_key) or builder.get("llm") or ""
        for lbl, d in llm_by_label.items():
            if d["name"] == d_name and d["installed"]:
                v_llm.set(lbl)
                on_llm()

        def after():
            snap = snapshot()
            res = {"target": kind, "prompt": builder.get("reconciled_prompt") or builder.get("final_prompt", ""),
                   llm_res_key: d_name, **settings}
            res.setdefault("model", settings.get("model", ""))
            res.setdefault("version", settings.get("version", ""))
            res.setdefault("duration", settings.get("duration_sec", ""))
            show_reconciled(res, ["Imported: this is the Final prompt it was made with."], snap)
            txt_final.delete("1.0", "end")
            txt_final.insert("1.0", builder.get("final_prompt") or res["prompt"])
            on_target()
            v_rec_status.set("📥 Imported. Change things and Reconcile, or edit the Final prompt and Send.")

        apply_values(builder.get("values", {}), builder.get("vision", ""), after)

    win._import_recipe = import_recipe
    scope.update(txt_prev=txt_prev, v_target=v_target, v_rect_info=v_rect_info, mark_stale=mark_stale)
    on_target()
    refresh_preview()
    return win


def build_outputs_panel(parent, root, title: str, placeholder: str, on_select, on_open, menu_items, buttons_spec):
    """Build shared right-side preview frame, outputs Treeview, context menu, and action buttons."""
    import tkinter as tk
    from tkinter import ttk

    right = ttk.LabelFrame(parent, text=title, padding=8)
    right.grid(row=0, column=1, sticky="nsew")
    right.rowconfigure(1, weight=1)
    right.columnconfigure(0, weight=1)

    preview_box = tk.Frame(right, bg="#060913", width=s(392), height=s(224), highlightbackground="#26365e", highlightthickness=1)
    preview_box.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    preview_box.pack_propagate(False)
    lbl_preview = tk.Label(preview_box, bg="#060913", fg="#8fa0c8", text=placeholder)
    lbl_preview.pack(fill="both", expand=True)

    col_specs = [("file", "Filename", 180, "w"), ("size", "Size", 72, "e"), ("mtime", "Created / Modified", 135, "w")]
    tree = ttk.Treeview(right, columns=("file", "size", "mtime", "path"), displaycolumns=("file", "size", "mtime"), show="headings", selectmode="browse")
    for col, txt, w, anc in col_specs:
        tree.heading(col, text=txt)
        tree.column(col, width=s(w), anchor=anc)

    def _rescale_outputs(_scale):
        if preview_box.winfo_exists():
            preview_box.configure(width=s(392), height=s(224))
        if tree.winfo_exists():
            for col, _, w, _ in col_specs:
                tree.column(col, width=s(w))

    register_scale_listener(_rescale_outputs)
    tree.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
    tree.bind("<<TreeviewSelect>>", on_select)
    tree.bind("<Double-1>", lambda *_: on_open())
    attach_tooltip(tree, "outputs_list")

    ctx = tk.Menu(root, tearoff=0, bg="#11192e", fg="#eef2fc")
    for lbl, fn in menu_items:
        ctx.add_command(label=lbl, command=fn)
    tree.bind("<Button-3>", lambda e: (tree.identify_row(e.y) and tree.selection_set(tree.identify_row(e.y)), ctx.tk_popup(e.x_root, e.y_root)))

    btn_box = ttk.Frame(right)
    btn_box.grid(row=2, column=0, sticky="ew")
    btn_box.columnconfigure((0, 1), weight=1)
    for blbl, fn, r, c, cs, sty, tkey in buttons_spec:
        b = ttk.Button(btn_box, text=blbl, style=sty, command=fn)
        b.grid(row=r, column=c, columnspan=cs, sticky="ew", padx=3, pady=3)
        attach_tooltip(b, tkey)
    return right, tree, lbl_preview
