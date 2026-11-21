"""Categorized UI themes (Google Pixel, COSMIC, KDE, GTK, Qt) for Graphical Studio."""

import json
import os

CAUTION_FG = "#e5484d"

SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui_settings.json")
DEFAULT_THEME_ID = "pixel_dark_blue"

THEME_CATEGORIES = [
    ("Google Pixel (Android — Material You)", [
        ("pixel_dark_blue", "Pixel Material You Dark (Tonal Slate Blue)", {
            "bg": "#121318", "panel": "#1b1d24", "input_bg": "#232630", "fg": "#e3e2e9",
            "muted": "#9ea3b4", "accent": "#a8c7fa", "accent_btn": "#2b4776", "accent_fg": "#ffffff",
            "btn_bg": "#252936", "border": "#383d4d", "log_bg": "#101217", "log_fg": "#b8dec4",
        }),
        ("pixel_dark_sage", "Pixel Material You Dark (Sage Green)", {
            "bg": "#111412", "panel": "#1a1f1c", "input_bg": "#222925", "fg": "#e1e4e0",
            "muted": "#9aa89e", "accent": "#a6d3b2", "accent_btn": "#265239", "accent_fg": "#ffffff",
            "btn_bg": "#242c27", "border": "#36423a", "log_bg": "#0f1210", "log_fg": "#bde3c7",
        }),
        ("pixel_dark_lavender", "Pixel Material You Dark (Soft Lavender)", {
            "bg": "#151218", "panel": "#1f1b24", "input_bg": "#292331", "fg": "#e8e0ec",
            "muted": "#afa4b8", "accent": "#d0bcff", "accent_btn": "#4b3872", "accent_fg": "#ffffff",
            "btn_bg": "#2b2533", "border": "#40374c", "log_bg": "#121015", "log_fg": "#d2c5f0",
        }),
        ("pixel_light", "Pixel Material You Light (Clean Daylight)", {
            "bg": "#f3f5f8", "panel": "#ffffff", "input_bg": "#eef1f6", "fg": "#1f2328",
            "muted": "#5f6672", "accent": "#1a73e8", "accent_btn": "#1a73e8", "accent_fg": "#ffffff",
            "btn_bg": "#e4e8f0", "border": "#cfd6e2", "log_bg": "#f7f9fc", "log_fg": "#1d5e3a",
        }),
    ]),
    ("COSMIC (Pop!_OS Desktop)", [
        ("cosmic_dark_teal", "COSMIC Dark (Warm Neutral + Teal)", {
            "bg": "#1b1b1d", "panel": "#252528", "input_bg": "#2f2f34", "fg": "#e8e8ea",
            "muted": "#a2a2a8", "accent": "#6ec8c8", "accent_btn": "#236b6b", "accent_fg": "#ffffff",
            "btn_bg": "#323238", "border": "#44444c", "log_bg": "#161618", "log_fg": "#9fe0cf",
        }),
        ("cosmic_dark_indigo", "COSMIC Dark (Deep Indigo)", {
            "bg": "#171923", "panel": "#212433", "input_bg": "#2a2e40", "fg": "#e4e6f0",
            "muted": "#9ba1b8", "accent": "#94a3f8", "accent_btn": "#3a4887", "accent_fg": "#ffffff",
            "btn_bg": "#2c3145", "border": "#3f4661", "log_bg": "#13151e", "log_fg": "#b8d7f5",
        }),
        ("cosmic_light", "COSMIC Light", {
            "bg": "#f2f2f5", "panel": "#ffffff", "input_bg": "#e8e8ee", "fg": "#1c1c1f",
            "muted": "#5d5d66", "accent": "#1e7e7e", "accent_btn": "#1e7e7e", "accent_fg": "#ffffff",
            "btn_bg": "#e2e2e8", "border": "#cbcdd6", "log_bg": "#f7f7fa", "log_fg": "#1f5f52",
        }),
    ]),
    ("KDE Plasma (Breeze)", [
        ("kde_breeze_dark", "KDE Breeze Dark", {
            "bg": "#232629", "panel": "#2a2e32", "input_bg": "#1b1e20", "fg": "#eff0f1",
            "muted": "#a1a9b1", "accent": "#3daee9", "accent_btn": "#1f6c94", "accent_fg": "#ffffff",
            "btn_bg": "#31363b", "border": "#454c54", "log_bg": "#181b1d", "log_fg": "#9adbc2",
        }),
        ("kde_breeze_twilight", "KDE Breeze Twilight", {
            "bg": "#1e2227", "panel": "#272c33", "input_bg": "#181b20", "fg": "#e6e9ec",
            "muted": "#9aa2ac", "accent": "#61afef", "accent_btn": "#2c5f8a", "accent_fg": "#ffffff",
            "btn_bg": "#2f353d", "border": "#424a55", "log_bg": "#15181c", "log_fg": "#a9dc9b",
        }),
        ("kde_breeze_light", "KDE Breeze Light", {
            "bg": "#eff0f1", "panel": "#fcfcfc", "input_bg": "#ffffff", "fg": "#232629",
            "muted": "#616870", "accent": "#2980b9", "accent_btn": "#2980b9", "accent_fg": "#ffffff",
            "btn_bg": "#e3e5e7", "border": "#c5c9ce", "log_bg": "#f8f9fa", "log_fg": "#1e6343",
        }),
    ]),
    ("GTK (GNOME Adwaita)", [
        ("gtk_adwaita_dark", "GTK Adwaita Dark", {
            "bg": "#242424", "panel": "#303030", "input_bg": "#1e1e1e", "fg": "#f0f0f0",
            "muted": "#a8a8a8", "accent": "#78aeed", "accent_btn": "#356199", "accent_fg": "#ffffff",
            "btn_bg": "#3a3a3a", "border": "#4c4c4c", "log_bg": "#1a1a1a", "log_fg": "#a9dec0",
        }),
        ("gtk_adwaita_warm", "GTK Adwaita Warm Slate", {
            "bg": "#26252b", "panel": "#323139", "input_bg": "#1f1e24", "fg": "#f2f1f5",
            "muted": "#aba9b5", "accent": "#91b8f2", "accent_btn": "#435d8a", "accent_fg": "#ffffff",
            "btn_bg": "#3c3b45", "border": "#504e5b", "log_bg": "#1b1a1f", "log_fg": "#b8dec7",
        }),
        ("gtk_adwaita_light", "GTK Adwaita Light", {
            "bg": "#f6f5f4", "panel": "#ffffff", "input_bg": "#ebebeb", "fg": "#2e2e2e",
            "muted": "#666666", "accent": "#3584e4", "accent_btn": "#3584e4", "accent_fg": "#ffffff",
            "btn_bg": "#e4e4e4", "border": "#cdcdcd", "log_bg": "#fafafa", "log_fg": "#20603d",
        }),
    ]),
    ("Qt (Fusion)", [
        ("qt_fusion_dark", "Qt Fusion Dark", {
            "bg": "#2d2d2d", "panel": "#353535", "input_bg": "#1f1f1f", "fg": "#e6e6e6",
            "muted": "#a4a4a4", "accent": "#5294e2", "accent_btn": "#36659e", "accent_fg": "#ffffff",
            "btn_bg": "#404040", "border": "#525252", "log_bg": "#1b1b1b", "log_fg": "#a8dbb9",
        }),
        ("qt_fusion_light", "Qt Fusion Light", {
            "bg": "#efefef", "panel": "#f8f8f8", "input_bg": "#ffffff", "fg": "#222222",
            "muted": "#5c5c5c", "accent": "#3071c4", "accent_btn": "#3071c4", "accent_fg": "#ffffff",
            "btn_bg": "#e2e2e2", "border": "#c6c6c6", "log_bg": "#ffffff", "log_fg": "#1e5c3b",
        }),
    ]),
]

THEMES_BY_ID = {tid: (cat, name, pal) for cat, items in THEME_CATEGORIES for tid, name, pal in items}


def load_saved_theme_id() -> str:
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            tid = json.load(f).get("theme_id", DEFAULT_THEME_ID)
            if tid in THEMES_BY_ID:
                return tid
    except Exception:
        pass
    return DEFAULT_THEME_ID


def save_theme_id(theme_id: str):
    data = {}
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            loaded = json.load(f)
            if isinstance(loaded, dict):
                data = loaded
    except Exception:
        pass
    data["theme_id"] = theme_id
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def _recolor_tk_widgets(widget, p: dict):
    cls = widget.winfo_class()
    try:
        if getattr(widget, "_is_swatch", False):
            pass
        elif cls in ("Tk", "Toplevel"):
            widget.configure(bg=p["bg"])
        elif cls == "Text":
            is_log = getattr(widget, "_is_log", False) or "Monospace" in str(widget.cget("font"))
            widget.configure(
                bg=p["log_bg"] if is_log else p["input_bg"],
                fg=p["log_fg"] if is_log else p["fg"],
                insertbackground=p["accent"],
                highlightbackground=p["border"],
                highlightcolor=p["accent"],
                highlightthickness=1,
                selectbackground=p["accent_btn"],
                selectforeground=p["accent_fg"],
            )
        elif cls == "Frame":
            widget.configure(bg=p["input_bg"], highlightbackground=p["border"])
        elif cls == "Label":
            widget.configure(bg=p["input_bg"], fg=p["muted"])
        elif cls == "Menu":
            widget.configure(bg=p["panel"], fg=p["fg"], activebackground=p["accent_btn"], activeforeground=p["accent_fg"])
    except Exception:
        pass
    for child in widget.winfo_children():
        _recolor_tk_widgets(child, p)


def apply_theme(root, theme_id: str | None = None, persist: bool = False) -> str:
    """Apply a categorized theme palette to ttk styles, tk widgets, and tooltips."""
    from tkinter import ttk
    from studio_dpi import get_font, s
    import studio_tooltips

    tid = theme_id if theme_id in THEMES_BY_ID else load_saved_theme_id()
    _, _, p = THEMES_BY_ID[tid]
    studio_tooltips.CURRENT_PALETTE = dict(p)

    f_ui = get_font("ui")
    f_bold = get_font("ui_bold")
    f_head = get_font("ui_heading")
    try:
        row_h = max(s(24), int(f_ui.metrics("linespace")) + s(6))
    except Exception:
        row_h = s(24)

    style = ttk.Style(root)
    style.theme_use("clam")
    for opt, val in [
        ("*TCombobox*Listbox.background", p["input_bg"]),
        ("*TCombobox*Listbox.foreground", p["fg"]),
        ("*TCombobox*Listbox.selectBackground", p["accent_btn"]),
        ("*TCombobox*Listbox.selectForeground", p["accent_fg"]),
        ("*TCombobox*Listbox.font", f_ui),
    ]:
        root.option_add(opt, val)

    for k, cfg in {
        ".": {"background": p["bg"], "foreground": p["fg"], "fieldbackground": p["input_bg"], "bordercolor": p["border"], "lightcolor": p["border"], "darkcolor": p["border"], "focuscolor": p["accent"], "selectbackground": p["accent_btn"], "selectforeground": p["accent_fg"], "font": f_ui},
        "TFrame": {"background": p["bg"]},
        "TNotebook": {"background": p["bg"], "bordercolor": p["border"], "lightcolor": p["border"], "darkcolor": p["border"]},
        "TNotebook.Tab": {"background": p["panel"], "foreground": p["muted"], "bordercolor": p["border"], "lightcolor": p["panel"], "darkcolor": p["panel"], "focuscolor": p["panel"], "padding": (s(14), s(6)), "font": f_bold},
        "TLabelframe": {"background": p["panel"], "foreground": p["accent"], "bordercolor": p["border"], "lightcolor": p["border"], "darkcolor": p["border"], "borderwidth": 1},
        "TLabelframe.Label": {"background": p["panel"], "foreground": p["accent"], "font": f_bold},
        "TLabel": {"background": p["panel"], "foreground": p["fg"], "font": f_ui},
        "TEntry": {"fieldbackground": p["input_bg"], "foreground": p["fg"], "insertcolor": p["accent"], "bordercolor": p["border"], "lightcolor": p["border"], "darkcolor": p["border"], "selectbackground": p["accent_btn"], "selectforeground": p["accent_fg"], "font": f_ui},
        "TCombobox": {"fieldbackground": p["input_bg"], "foreground": p["fg"], "background": p["btn_bg"], "arrowcolor": p["fg"], "bordercolor": p["border"], "lightcolor": p["border"], "darkcolor": p["border"], "selectbackground": p["accent_btn"], "selectforeground": p["accent_fg"], "font": f_ui},
        "TButton": {"background": p["btn_bg"], "foreground": p["fg"], "bordercolor": p["border"], "lightcolor": p["btn_bg"], "darkcolor": p["border"], "focuscolor": p["accent"], "padding": (s(8), s(5)), "font": f_ui},
        "Accent.TButton": {"background": p["accent_btn"], "foreground": p["accent_fg"], "bordercolor": p["accent"], "lightcolor": p["accent_btn"], "darkcolor": p["border"], "focuscolor": p["accent"], "padding": (s(10), s(6)), "font": f_ui},
        "TCheckbutton": {"background": p["panel"], "foreground": p["fg"], "indicatorbackground": p["input_bg"], "indicatorforeground": p["accent"], "focuscolor": p["panel"], "font": f_ui},
        "TRadiobutton": {"background": p["panel"], "foreground": p["fg"], "indicatorbackground": p["input_bg"], "indicatorforeground": p["accent"], "focuscolor": p["panel"], "font": f_ui},
        "TProgressbar": {"background": p["accent_btn"], "troughcolor": p["input_bg"], "bordercolor": p["border"], "lightcolor": p["accent_btn"], "darkcolor": p["border"]},
        "TScrollbar": {"background": p["btn_bg"], "troughcolor": p["input_bg"], "bordercolor": p["border"], "lightcolor": p["btn_bg"], "darkcolor": p["border"], "arrowcolor": p["fg"]},
        "Treeview": {"background": p["input_bg"], "foreground": p["fg"], "fieldbackground": p["input_bg"], "bordercolor": p["border"], "lightcolor": p["border"], "darkcolor": p["border"], "rowheight": row_h, "font": f_ui},
        "Treeview.Heading": {"background": p["btn_bg"], "foreground": p["accent"], "bordercolor": p["border"], "lightcolor": p["btn_bg"], "darkcolor": p["border"], "font": f_head},
    }.items():
        style.configure(k, **cfg)
    style.map("TCombobox", fieldbackground=[("readonly", p["input_bg"]), ("disabled", p["panel"])], foreground=[("readonly", p["fg"]), ("disabled", p["muted"])], bordercolor=[("focus", p["accent"])])
    style.map("TEntry", bordercolor=[("focus", p["accent"])])
    # Models with a caveat show in red while selected; readable on light and dark themes.
    style.map("Caution.TCombobox", fieldbackground=[("readonly", p["input_bg"]), ("disabled", p["panel"])],
              foreground=[("readonly", CAUTION_FG), ("disabled", CAUTION_FG), ("!disabled", CAUTION_FG)],
              bordercolor=[("focus", p["accent"])])
    style.map("TNotebook.Tab", background=[("selected", p["btn_bg"])], foreground=[("selected", p["accent"])], lightcolor=[("selected", p["accent"])])
    style.map("TButton", background=[("active", p["accent_btn"]), ("disabled", p["panel"])], foreground=[("active", p["accent_fg"]), ("disabled", p["muted"])])
    style.map("TCheckbutton", indicatorbackground=[("selected", p["accent_btn"])], background=[("active", p["btn_bg"])])
    style.map("TRadiobutton", indicatorbackground=[("selected", p["accent_btn"])], background=[("active", p["btn_bg"])])
    style.map("Treeview", background=[("selected", p["accent_btn"])], foreground=[("selected", p["accent_fg"])])

    _recolor_tk_widgets(root, p)
    if persist:
        save_theme_id(tid)
    return tid


def build_themes_tab(parent, root, active_var, on_select_theme, scale_var=None, on_select_scale=None):
    """Build the categorized Themes & Appearance tab (Pixel at top, then COSMIC, KDE, GTK, Qt)."""
    import tkinter as tk
    from tkinter import ttk
    import studio_dpi
    from studio_dpi import SCALE_OPTIONS, register_scale_listener, s
    from studio_tooltips import attach_tooltip

    outer = ttk.Frame(parent, padding=s(12))
    outer.pack(fill="both", expand=True)

    if scale_var is not None and on_select_scale is not None:
        dpi_box = ttk.LabelFrame(outer, text="Display & DPI Scaling (Local per Machine — Not Synced in Git)", padding=s(10))
        dpi_box.pack(fill="x", pady=(0, s(10)))
        row = ttk.Frame(dpi_box)
        row.pack(fill="x")
        ttk.Label(row, text="UI Scale:").pack(side="left", padx=(0, s(8)))
        scale_labels = [lbl for _, lbl in SCALE_OPTIONS]
        scale_by_lbl = {lbl: key for key, lbl in SCALE_OPTIONS}
        lbl_by_key = {key: lbl for key, lbl in SCALE_OPTIONS}
        v_scale_lbl = tk.StringVar(value=lbl_by_key.get(scale_var.get(), scale_labels[0]))
        cb_scale = ttk.Combobox(row, textvariable=v_scale_lbl, values=scale_labels, state="readonly", width=26)
        cb_scale.pack(side="left", padx=(0, s(10)))

        v_dpi_info = tk.StringVar()

        def _refresh_dpi_info(*_):
            v_scale_lbl.set(lbl_by_key.get(scale_var.get(), f"{int(round(studio_dpi.CURRENT_SCALE * 100))}%"))
            v_dpi_info.set(
                f"Detected {studio_dpi.LAST_DETECTED_DPI:.0f} DPI -> Auto {int(round(studio_dpi.LAST_AUTO_SCALE * 100))}% "
                f"| Active: {int(round(studio_dpi.CURRENT_SCALE * 100))}%  (Shortcuts: Ctrl++ / Ctrl+- / Ctrl+0)"
            )

        cb_scale.bind("<<ComboboxSelected>>", lambda *_: on_select_scale(scale_by_lbl.get(v_scale_lbl.get(), "auto")))
        b_auto = ttk.Button(row, text="Reset to Auto", command=lambda: on_select_scale("auto"))
        b_auto.pack(side="left", padx=(0, s(10)))
        ttk.Label(row, textvariable=v_dpi_info).pack(side="left", fill="x", expand=True)
        attach_tooltip(cb_scale, "Choose Auto (DPI) to adapt automatically on any monitor, or pick a manual scale saved locally on this computer.")
        _refresh_dpi_info()
        register_scale_listener(_refresh_dpi_info)

    hdr = ttk.LabelFrame(outer, text="UI Theme & Color Palette (Saved Automatically)", padding=s(10))
    hdr.pack(fill="x", pady=(0, s(10)))
    ttk.Label(hdr, text="Pick a softer palette from Google Pixel (Material You), COSMIC, KDE Breeze, GTK Adwaita, or Qt Fusion. Hover any swatch button for details.").pack(anchor="w")

    grid = ttk.Frame(outer)
    grid.pack(fill="both", expand=True)
    grid.columnconfigure(0, weight=1)
    grid.columnconfigure(1, weight=1)

    swatches = []
    for idx, (cat_name, items) in enumerate(THEME_CATEGORIES):
        r, c = (idx // 2, idx % 2) if idx < 4 else (2, 0)
        cs = 2 if idx == 4 else 1
        box = ttk.LabelFrame(grid, text=cat_name, padding=s(8))
        box.grid(row=r, column=c, columnspan=cs, sticky="nsew", padx=5, pady=5)
        box.columnconfigure(1, weight=1)
        for row_i, (tid, tname, pal) in enumerate(items):
            sw = tk.Frame(box, bg=pal["bg"], highlightbackground=pal["accent"], highlightthickness=2, width=s(44), height=s(22))
            sw._is_swatch = True
            sw.grid(row=row_i, column=0, padx=(0, 8), pady=3)
            sw.pack_propagate(False)
            accent_bar = tk.Frame(sw, bg=pal["accent"], width=s(14))
            accent_bar._is_swatch = True
            accent_bar.pack(side="right", fill="y")
            swatches.append((sw, accent_bar))
            rb = ttk.Radiobutton(box, text=tname, variable=active_var, value=tid, command=lambda k=tid: on_select_theme(k))
            rb.grid(row=row_i, column=1, sticky="w", pady=3)
            attach_tooltip(rb, f"Switch UI to {tname} ({cat_name}).")

    def _rescale_swatches(_scale):
        for sw, bar in swatches:
            if sw.winfo_exists():
                sw.configure(width=s(44), height=s(22))
                bar.configure(width=s(14))

    register_scale_listener(_rescale_swatches)
    return outer
