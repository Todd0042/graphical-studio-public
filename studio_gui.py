#!/usr/bin/env python3
"""Dark-themed Tkinter GUI wrapper for Graphical Studio."""

import argparse
import json
import os

import addons
import studio_dpi
from studio_builder_dialog import open_builder_window
from studio_dpi import SCALE_OPTIONS, apply_ui_scale, fit_window_geometry, load_saved_scale
from studio_helpers import PHOTOS_DIR, build_photo_cli_command, scan_photo_outputs
from studio_photo_tab import build_photos_tab
from studio_prompt_catalog import ALL_FIELDS, assemble_builder_prompt, ascertain_fields_from_prompt
from studio_themes import THEME_CATEGORIES, THEMES_BY_ID, apply_theme, build_themes_tab, load_saved_theme_id
from studio_tooltips import TOOLTIPS


def launch_app():
    import tkinter as tk
    from tkinter import ttk
    from PIL import Image, ImageTk

    root = tk.Tk()
    root.title(addons.REGISTRY.desktop.get("window_title") or "Graphical Studio — Image & Asset Studio")
    v_scale = tk.StringVar(value=load_saved_scale())
    apply_ui_scale(root, v_scale.get())
    fit_window_geometry(root, 1260, 880, 980, 680)
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "graphical_studio_icon.png")
    if os.path.isfile(icon_path):
        root._app_icon = ImageTk.PhotoImage(Image.open(icon_path))
        root.iconphoto(True, root._app_icon)
    v_theme = tk.StringVar(value=load_saved_theme_id())
    apply_theme(root, v_theme.get())
    v_status = tk.StringVar(value=addons.REGISTRY.desktop.get("ready_status") or "Ready (FLUX / Qwen-Image)")

    def show_startup_status():
        """Status + models.json sync check, off the Tk thread."""
        import threading

        def worker():
            from studio_models import startup_notice

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

    photo_api_ref: dict = {}
    extra_ctrls: list[dict] = []

    def apply_photo_prompt(text: str, replace: bool = True, builder_vals: dict | None = None, vision: str = "",
                           settings: dict | None = None, builder: dict | None = None):
        photo_api_ref["api"]["set_prompt"](text, replace=replace, builder_vals=builder_vals, vision=vision,
                                           settings=settings, builder=builder)
        notebook.select(tab_photo)

    def launch_builder(_mode: str = "photo"):
        def get_active_prompt():
            sel = notebook.select()
            for ctrl in extra_ctrls:
                if sel == str(ctrl["tab"]) and "get_prompt" in ctrl:
                    return ctrl["get_prompt"]()
            return photo_api_ref["api"]["get_prompt"]()

        extra_apply = {}
        for ctrl in extra_ctrls:
            if ctrl.get("target") and "apply_prompt" in ctrl:
                extra_apply[ctrl["target"]] = ctrl["apply_prompt"]
        return open_builder_window(
            root, extra_apply, apply_photo_prompt, get_active_prompt=get_active_prompt,
        )

    def import_into_builder(asset: dict):
        """Open the Prompt Builder with a library item's dropdowns, vision, target and Final prompt."""
        st = asset.get("settings") or {}
        win = launch_builder(asset["kind"])
        shown = {k: st.get(k) for k in ("model", "version", "steps", "cfg", "sampler", "scheduler", "fps", "width", "height")}
        if st.get("duration_sec") is not None:
            shown["duration_sec"] = st.get("duration_sec")
        win._import_recipe(asset["builder"], shown, asset["kind"])

    # Mount optional extension tabs before core tabs when registered
    extra_tab_frames = []
    for factory in addons.REGISTRY.desktop.get("extra_tabs", ()):
        tab_frame = ttk.Frame(notebook)
        notebook.add(tab_frame, text=factory["title"])
        extra_tab_frames.append((tab_frame, factory))

    tab_photo = ttk.Frame(notebook)
    tab_assets = ttk.Frame(notebook)
    tab_themes = ttk.Frame(notebook)
    notebook.add(tab_photo, text=addons.REGISTRY.desktop.get("photo_tab_title") or "🖼 Photos & Images (FLUX / Qwen-Image)")
    notebook.add(tab_assets, text="✨ Asset Studio (Icons / Backgrounds / Textures)")
    notebook.add(tab_themes, text="🎨 Themes & Menu")

    for tab_frame, factory in extra_tab_frames:
        ctrl = factory["build"](
            tab_frame, root, notebook,
            launch_builder=launch_builder, import_into_builder=import_into_builder, v_status=v_status,
        )
        ctrl["tab"] = tab_frame
        extra_ctrls.append(ctrl)

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
        nxt = max(0.70, min(2.25, round((studio_dpi.CURRENT_SCALE + delta) * 20.0) / 20.0))
        select_scale(f"{nxt:.2f}")

    build_themes_tab(tab_themes, root, v_theme, select_theme, scale_var=v_scale, on_select_scale=select_scale)
    photo_api = build_photos_tab(tab_photo, root, on_open_builder=launch_builder,
                                 on_import_builder=import_into_builder, extra_ctrls=extra_ctrls)
    photo_api_ref["api"] = photo_api
    from studio_assets_tab import build_assets_tab
    assets_api = build_assets_tab(tab_assets, root)

    def active_api():
        sel = notebook.select()
        if sel == str(tab_assets):
            return assets_api
        if sel == str(tab_photo):
            return photo_api
        for ctrl in extra_ctrls:
            if sel == str(ctrl["tab"]):
                return ctrl.get("active_api", photo_api)
        return photo_api

    _sc = addons.REGISTRY.desktop.get("shortcuts", {})
    menubar = tk.Menu(root, bg="#11192e", fg="#eef2fc", activebackground="#1d3566", activeforeground="#ffffff")
    m_file = tk.Menu(menubar, tearoff=0, bg="#11192e", fg="#eef2fc")
    added_file_items = False
    for ctrl in extra_ctrls:
        for lbl, fn in ctrl.get("file_menu_items", ()):
            m_file.add_command(label=lbl, command=fn)
            added_file_items = True
    if added_file_items:
        m_file.add_separator()
    m_file.add_command(label="Exit", command=root.destroy)
    menubar.add_cascade(label="File", menu=m_file)

    m_out = tk.Menu(menubar, tearoff=0, bg="#11192e", fg="#eef2fc")
    _out_menu = [
        ("Open / View Selected", "open_selected"),
        (_sc.get("select_menubar", "Reveal File in File Manager"), "select_file"),
        (_sc.get("open_outputs_menubar", "Open Outputs Folder"), "open_folder"),
        *([(_sc.get("extra_menubar_label", "Copy to Export Folder"), "copy_export")] if _sc.get("extra_menubar_enabled") else []),
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
    asc = ascertain_fields_from_prompt("RAW candid photo, brunette waves, hazel eyes, cowboy shot, bedroom studio, warm smile")
    assert "American Realistic" in asc["style"] and "Brunette" in asc["hair_color"] and "Waves" in asc["hair_style"] and "Hazel" in asc["eyes"] and "Cowboy" in asc["framing"]
    photos = [r["name"] for r in scan_photo_outputs(PHOTOS_DIR)]
    pcmd = build_photo_cli_command({"model": "flux2_klein", "prompt": "boardroom dusk", "width": 1280, "height": 720, "steps": 4})
    assert "--model" in pcmd and "--width" in pcmd and "1280" in pcmd
    st_hook = addons.REGISTRY.desktop.get("self_test_hook")
    if st_hook:
        st_hook()
    print(json.dumps({"self_test": "passed", "photos_found": len(photos), "tooltips_count": len(TOOLTIPS), "builder_sample": built_photo}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--self-test", action="store_true")
    known, _ = p.parse_known_args()
    run_self_test() if known.self_test else launch_app()
