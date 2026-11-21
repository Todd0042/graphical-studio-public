"""Plain-English hover tooltips for all Graphical Studio controls, flags, and builder dropdowns."""

import addons

CURRENT_PALETTE = {
    "bg": "#121318", "panel": "#1b1d24", "input_bg": "#232630", "fg": "#e3e2e9",
    "muted": "#9ea3b4", "accent": "#a8c7fa", "accent_btn": "#2b4776", "accent_fg": "#ffffff",
    "btn_bg": "#252936", "border": "#383d4d", "log_bg": "#101217", "log_fg": "#b8dec4",
}

TOOLTIPS = {
    "model_photo": "Pick the image model (FLUX.2 klein 4B, FLUX.1 dev, FLUX.1 schnell, or Qwen-Image 20B).",
    "preset": "One-click size preset that sets Width and Height safely for an 8 GB GPU.",
    "width": "Image width in pixels (multiple of 16). Wider takes more VRAM and time.",
    "height": "Image height in pixels (multiple of 16). 1280x720 matches 16:9 widescreen.",
    "swap_wh": "Swap the Width and Height numbers directly (e.g. 1280x720 <-> 720x1280).",
    "steps": "How many denoising passes the AI runs. FLUX.2 klein uses 4, FLUX.1 dev uses 24, Qwen-Image uses 8.",
    "cfg": "Prompt strictness (Classifier-Free Guidance). FLUX and Qwen-Image Lightning use 1.0.",
    "seed": "Starting random noise number. Same seed + same settings recreates the exact same image.",
    "rand_seed": "When checked, picks a new random seed every run so you get a fresh variation each time.",
    "sampler": "Math solver used at each step. 'euler' works well for FLUX and Qwen-Image.",
    "scheduler": "Controls how noise decreases across steps. 'simple' fits FLUX and Qwen-Image.",
    "output_name": "Optional custom filename (e.g. concept_scene_01). Leave blank to auto-name from your prompt and timestamp.",
    "cli_cmd": "Exact terminal command that will run when you click Generate (read-only preview).",
    "prompt": "Describe the scene, subject, clothing, setting, composition, and lighting.",
    "negative": "Things you want the AI to avoid generating (blur, extra fingers, watermarks, bad anatomy).",
    "generate": "Start generating using the settings above. Progress appears in the bar and live log below.",
    "cancel": "Stop the running generation process right away.",
    "open_output": "Open the selected image in your default system viewer.",
    "select_file": "Open the file manager with this exact output file highlighted.",
    "open_folder": "Open the outputs folder in your file manager.",
    "copy_export": "Copy the selected file directly into the configured project assets folder.",
    "send_to_ref": "Send this selected output photo into the Reference Image slot above.",
    "refresh_list": "Rescan the outputs folder on disk for newly created files.",
    "outputs_list": "Click any item to preview its thumbnail. Double-click to open, or right-click for quick actions.",
    "open_builder": "Open the full Scene & Person Builder window with all trait dropdowns.",
    "apply_quick_builder": "Build a clean prompt from the dropdowns you picked here and insert it into the description box below.",
    "style_bg_photo": "Prepend empty anime background tags to keep characters out of scenic backdrops.",
    "style_gs_photo": "Prepend bright green (#00FF00) chroma-key portrait sprite tags.",
    "style_real_photo": "Prepend realistic DSLR lifestyle photography tags for natural skin texture and lighting.",
    "style": "Overall visual aesthetic (realistic photo, anime, cinematic film, noir, 2.5D semi-realistic).",
    "lighting": "Time of day and light mood (soft ring light, golden hour sun, neon rain, cozy bedside lamp).",
    "framing": "How close the camera is to the subject (close-up face, waist-up vlogger shot, wide room, over-the-shoulder).",
    "gender": "Subject count and gender presentation (solo woman, solo man, couple, group).",
    "symmetry": "Facial attractiveness & symmetry cues — balanced proportions, clear cheekbones, even features, vivid eye catchlights.",
    "age": "Adult age look and overall presence (early 20s college, mid 20s modern, 30s confident, sharp executive).",
    "build": "Body type & posture (athletic, slender, curvy/hourglass, broad-shouldered, relaxed natural posture).",
    "hair_color": "Hair color and dye style only (chestnut brunette, golden honey blonde, balayage, jet black, copper auburn, pastel pink, silver-white).",
    "hair_style": "Haircut and styling only, independent of color (soft waves, curtain bangs, messy bun, sleek ponytail, wolf cut, bob, braids, fade undercut).",
    "eyes": "Eye color and eye shape only (hazel, emerald green, ocean blue, espresso brown, amber, heterochromia) without forcing makeup or lighting.",
    "skin": "Skin tone and natural surface texture only (fair, freckles, olive, golden-bronze, caramel, deep warm, dewy) without forcing art style or makeup.",
    "makeup_acc": "Optional makeup, eyewear, jewelry, headwear, headphones, or tattoos — kept separate from eyes, skin, and attire.",
    "attire": "Clothing and garments only (crop tops, hoodies, jeans, dresses, suits, armor) without forcing location.",
    "pose": "Pure body posture and limb arrangement only (standing, seated, leaning, cross-legged, reclining, walking) without forcing furniture or props.",
    "surface_prop": "Optional furniture, surface, or held prop (bed, chair, couch, counter, mirror, phone, coffee cup, desk mic, weapon) kept separate from pose and location.",
    "scene": "Physical location and environment only (bedroom, studio, living room, gym, penthouse, beach, tavern, starship) without forcing time-of-day or lighting.",
    "composition": "Where the subject sits in the frame. Image models follow this loosely by prompt; anything but Centered gets a wide 16:9 canvas.",
    "color_treatment": "Saturation and palette for the whole image: full color, muted, greyscale, sepia, duotone... Spot Color keeps one feature in color (pick it in Color Kept On).",
    "spot_color": "With Spot Color: the one feature that stays in color while everything else is grey.",
    "bg_type": "What the backdrop is when you don't want a location: solid, gradient, stripes, paint splashes, abstract shapes, bokeh... Overrides a conflicting Scene.",
    "bg_color": "Backdrop color. Pure Black / Very Dark Grey keep the image dark around the subject.",
    "builder_notes": "Your vision: what the picture should be. Reconcile checks your dropdowns against it and fixes conflicts; Fill dropdowns from my vision picks dropdown values from it.",
    "builder_send_photo": "Fill the Photos tab Positive Prompt and switch to Photos tab. If you only typed Extra Custom Details (every dropdown left at None), every dropdown is first auto-filled to match the vibe of your text.",
    "builder_random": "Pick a balanced sample combination across all dropdowns so you can customize from there.",
    "builder_clear": "Reset every builder dropdown and extra note back to blank.",
    "builder_template": "Saved Prompt Builder templates. Every Send to Photos auto-saves the current dropdowns and custom text here (newest first).",
    "builder_template_apply": "Set every dropdown from the selected template one at a time, then fill in its Extra Custom Details text.",
    "builder_template_save": "Save the current dropdowns and Extra Custom Details as a named template.",
    "builder_template_delete": "Delete the selected template.",
    "builder_ascertain": "Read your current Photos prompt (or preview box) and auto-set every dropdown to its closest match.",
    "rating": "Set the content tone for the scene.",
    "ref_image": "Optional reference photo used to guide a person or room layout.",
    "browse_ref": "Pick a reference photo from disk.",
    "clear_ref": "Clear the Reference Image and generate from text prompt only.",
    "ref_mode": "Choose what to extract from the Reference Image: Person or Background.",
    "ref_style": "Target output style prefix to prepend to your prompt.",
    "ref_weight": "How strongly the Reference Image influences the output (0.65-0.80).",
    "apply_ref_style": "Insert the selected Convert-To-Style keywords into the Positive Prompt box.",
    "anti_zoom_neg": "Add anti-zoom tags (close-up, headshot, portrait, cropped) to Negative Prompt.",
    "char_profile": "Choose 'Vary Person Each Run' to automatically inject distinct facial structure cues every run (breaks same-face syndrome), 'None' for prompt-only, or pick a saved Character Profile.",
    "save_profile": "Save the person in the currently selected generated photo as a reusable Character Profile.",
    "delete_profile": "Delete the currently selected saved Character Profile.",
}

if addons.REGISTRY.video_tooltips:
    TOOLTIPS.update(addons.REGISTRY.video_tooltips)
if addons.REGISTRY.tooltips_override:
    TOOLTIPS.update(addons.REGISTRY.tooltips_override)
if addons.REGISTRY.extend_tooltips:
    addons.REGISTRY.extend_tooltips(TOOLTIPS)


class ToolTip:
    """Lightweight dark-themed hover tooltip for any Tkinter/ttk widget."""

    def __init__(self, widget, text: str, delay_ms: int = 220):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._after_id = None
        self._win = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")
        widget.bind("<Destroy>", self._hide, add="+")

    def _schedule(self, _=None):
        self._cancel()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _cancel(self):
        if self._after_id:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        import tkinter as tk
        from wan_dpi import get_font, s

        if self._win or not self.text or not self.widget.winfo_exists():
            return
        x = min(self.widget.winfo_rootx() + s(14), max(0, self.widget.winfo_screenwidth() - s(365)))
        y = min(self.widget.winfo_rooty() + self.widget.winfo_height() + s(6), max(0, self.widget.winfo_screenheight() - s(110)))
        self._win = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        p = CURRENT_PALETTE
        tk.Label(
            tw, text=self.text, justify="left", wraplength=s(340), padx=s(8), pady=s(6),
            bg=p["panel"], fg=p["fg"], relief="solid", bd=1, highlightthickness=1,
            highlightbackground=p["accent"], font=get_font("small"),
        ).pack()

    def _hide(self, _=None):
        self._cancel()
        if self._win:
            try:
                self._win.destroy()
            except Exception:
                pass
            self._win = None


def attach_tooltip(widget, text_or_key: str) -> ToolTip:
    """Attach a plain-English hover tooltip to a widget using a TOOLTIPS key or literal text."""
    return ToolTip(widget, TOOLTIPS.get(text_or_key, text_or_key))


def build_wh_row(parent, v_width, v_height, on_change, row: int = 2):
    """Build Width entry + Swap (⇄) button + Height entry on a 4-column LabelFrame."""
    from tkinter import ttk

    lw = ttk.Label(parent, text="Width:"); lw.grid(row=row, column=0, sticky="w", padx=4, pady=2)
    w_box = ttk.Frame(parent); w_box.grid(row=row, column=1, sticky="ew", padx=4, pady=2)
    ew = ttk.Entry(w_box, textvariable=v_width, width=8); ew.pack(side="left", fill="x", expand=True)
    ew.bind("<KeyRelease>", on_change)

    def swap_wh():
        w, h = v_width.get(), v_height.get()
        v_width.set(h); v_height.set(w)
        on_change()

    bs = ttk.Button(w_box, text="⇄", width=3, command=swap_wh); bs.pack(side="left", padx=(4, 0))
    lh = ttk.Label(parent, text="Height:"); lh.grid(row=row, column=2, sticky="w", padx=4, pady=2)
    eh = ttk.Entry(parent, textvariable=v_height, width=10); eh.grid(row=row, column=3, sticky="ew", padx=4, pady=2)
    eh.bind("<KeyRelease>", on_change)
    attach_tooltip(lw, "width"); attach_tooltip(ew, "width")
    attach_tooltip(bs, "swap_wh")
    attach_tooltip(lh, "height"); attach_tooltip(eh, "height")


def pick_file_native(title: str, start_dir: str, kdialog_filter: str, tk_filetypes) -> str:
    """Open native KDE kdialog (with Drives, Recent, Pinned Places), falling back to Tk filedialog."""
    import os
    import shutil
    import subprocess
    from tkinter import filedialog

    init_dir = start_dir if (start_dir and os.path.isdir(start_dir)) else os.path.expanduser("~")
    if shutil.which("kdialog"):
        res = subprocess.run(
            ["kdialog", "--title", title, "--getopenfilename", init_dir, kdialog_filter],
            capture_output=True, text=True,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
        if res.returncode == 1:
            return ""
    return filedialog.askopenfilename(initialdir=init_dir, title=title, filetypes=tk_filetypes) or ""


def apply_dark_style(root):
    from tkinter import ttk

    style = ttk.Style(root)
    style.theme_use("clam")
    for k, cfg in {
        ".": {"background": "#0d1324", "foreground": "#eef2fc", "fieldbackground": "#121a32"},
        "TFrame": {"background": "#0d1324"},
        "TNotebook": {"background": "#0d1324", "bordercolor": "#26365e"},
        "TNotebook.Tab": {"background": "#131d38", "foreground": "#9fb4e0", "padding": (14, 6), "font": ("Sans", 10, "bold")},
        "TLabelframe": {"background": "#11192e", "foreground": "#44e0ff", "bordercolor": "#26365e"},
        "TLabelframe.Label": {"background": "#11192e", "foreground": "#44e0ff", "font": ("Sans", 10, "bold")},
        "TLabel": {"background": "#11192e", "foreground": "#d8e0f8"},
        "TButton": {"background": "#1b294c", "foreground": "#ffffff", "bordercolor": "#34508c", "padding": (8, 5)},
        "Accent.TButton": {"background": "#1d8f65", "foreground": "#ffffff", "bordercolor": "#36d496", "padding": (10, 6)},
        "TCheckbutton": {"background": "#11192e", "foreground": "#eef2fc"},
        "Treeview": {"background": "#0a0f1f", "foreground": "#eef2fc", "fieldbackground": "#0a0f1f", "rowheight": 24},
        "Treeview.Heading": {"background": "#162242", "foreground": "#44e0ff", "font": ("Sans", 9, "bold")},
    }.items():
        style.configure(k, **cfg)
    style.map("TCombobox", fieldbackground=[("readonly", "#121a32")], foreground=[("readonly", "#eef2fc")])
    style.map("TNotebook.Tab", background=[("selected", "#1d2d56")], foreground=[("selected", "#44e0ff")])

