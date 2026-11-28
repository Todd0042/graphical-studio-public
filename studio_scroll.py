"""Layouts that keep every control reachable on screens smaller than the window was designed for.

`flow_row(parent)` lays its children out left to right and wraps them onto more rows when narrow.

`scrollable(parent)` returns `(outer, inner)`: place `outer` like any frame and build into `inner`.
Scrollbars appear only when the content doesn't fit. When the viewport is larger than the content,
the content is stretched to fill it, so `expand=True` / grid weights inside still work.

Mouse wheel scrolls the area under the pointer (Shift+wheel sideways). Widgets that scroll
themselves (Text, Listbox, Treeview) keep their own wheel. Comboboxes do not: Tk's class binding
would cycle their value, silently changing a pick while the user is only scrolling the page.

One wheel dispatcher per application finds the innermost scroll area under the pointer, so several
areas (a tab and a dialog) never fight over global bindings.
"""

import tkinter as tk
from tkinter import ttk

_SELF_SCROLLING = ("Text", "Listbox", "Treeview")
_WHEEL = ("<MouseWheel>", "<Button-4>", "<Button-5>")
_SHIFT_WHEEL = ("<Shift-MouseWheel>", "<Shift-Button-4>", "<Shift-Button-5>")
_GUARD_TAG = "StudioPageWheel"  # in front of each Combobox's class tag inside a scroll area


def _steps(event) -> int:
    if event.num == 4:
        return -1
    if event.num == 5:
        return 1
    delta = getattr(event, "delta", 0)
    return -1 if delta > 0 else 1 if delta < 0 else 0


class _Area:
    def __init__(self, outer, canvas):
        self.outer, self.canvas = outer, canvas

    def scroll(self, event, horizontal: bool) -> None:
        n = _steps(event)
        if not n:
            return
        first, last = (self.canvas.xview if horizontal else self.canvas.yview)()
        if (n < 0 and first > 0) or (n > 0 and last < 1):
            (self.canvas.xview_scroll if horizontal else self.canvas.yview_scroll)(n, "units")


def _areas(root) -> list:
    """This application's scroll areas; installs the wheel dispatcher the first time."""
    areas = getattr(root, "_studio_scroll_areas", None)
    if areas is not None:
        return areas
    areas = root._studio_scroll_areas = []

    def area_for(widget):
        try:
            path = str(widget)
        except Exception:
            return None
        # Innermost first: the longest outer path that contains the widget.
        best = None
        for a in areas:
            o = str(a.outer)
            if (path == o or path.startswith(o + ".")) and (best is None or len(o) > len(str(best.outer))):
                best = a
        return best

    def dispatch(event, horizontal: bool, from_guard: bool):
        w = event.widget
        if isinstance(w, str):  # events from Tk internals (e.g. a combobox popdown) arrive as names
            return None
        if not from_guard and w.winfo_class() in _SELF_SCROLLING:
            return None
        area = area_for(w)
        if area is not None:
            area.scroll(event, horizontal)
        return "break" if from_guard else None

    for seq in _WHEEL:
        root.bind_all(seq, lambda e: dispatch(e, False, False), add="+")
        root.bind_class(_GUARD_TAG, seq, lambda e: dispatch(e, False, True))
    for seq in _SHIFT_WHEEL:
        root.bind_all(seq, lambda e: dispatch(e, True, False), add="+")
        root.bind_class(_GUARD_TAG, seq, lambda e: dispatch(e, True, True))
    return areas


def _guard_comboboxes(widget) -> None:
    for child in widget.winfo_children():
        if isinstance(child, ttk.Combobox) and _GUARD_TAG not in child.bindtags():
            child.bindtags((_GUARD_TAG,) + child.bindtags())
        _guard_comboboxes(child)


def scrollable(parent, *, bg: str | None = None):
    """Return (outer, inner): a frame with auto-hiding scrollbars, and the frame to build into."""
    outer = ttk.Frame(parent)
    outer.rowconfigure(0, weight=1)
    outer.columnconfigure(0, weight=1)
    canvas = tk.Canvas(outer, highlightthickness=0, borderwidth=0, **({"bg": bg} if bg else {}))
    vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    hsb = ttk.Scrollbar(outer, orient="horizontal", command=canvas.xview)
    canvas.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
    canvas.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")
    hsb.grid(row=1, column=0, sticky="ew")
    inner = ttk.Frame(canvas)
    item = canvas.create_window((0, 0), window=inner, anchor="nw")
    pending = {"id": None}

    areas = _areas(outer.winfo_toplevel()._root())
    area = _Area(outer, canvas)
    areas.append(area)

    def layout():
        pending["id"] = None
        if not outer.winfo_exists():
            return
        _guard_comboboxes(inner)  # dropdowns added since the last layout
        need_w, need_h = inner.winfo_reqwidth(), inner.winfo_reqheight()
        avail_w, avail_h = outer.winfo_width(), outer.winfo_height()
        if avail_w <= 1 or avail_h <= 1:
            return
        # Decide both bars together: one bar takes room that can make the other necessary.
        show_v = need_h > avail_h
        show_h = need_w > avail_w - (vsb.winfo_reqwidth() if show_v else 0)
        show_v = need_h > avail_h - (hsb.winfo_reqheight() if show_h else 0)
        vsb.grid() if show_v else vsb.grid_remove()
        hsb.grid() if show_h else hsb.grid_remove()
        view_w = avail_w - (vsb.winfo_reqwidth() if show_v else 0)
        view_h = avail_h - (hsb.winfo_reqheight() if show_h else 0)
        w, h = max(need_w, view_w), max(need_h, view_h)
        canvas.itemconfigure(item, width=w, height=h)
        canvas.configure(scrollregion=(0, 0, w, h))
        if not show_v:
            canvas.yview_moveto(0)
        if not show_h:
            canvas.xview_moveto(0)

    def schedule(_e=None):
        if pending["id"] is None:
            pending["id"] = outer.after_idle(layout)

    def forget(e):
        if e.widget is outer and area in areas:
            areas.remove(area)

    outer.bind("<Configure>", schedule, add="+")
    inner.bind("<Configure>", schedule, add="+")
    outer.bind("<Destroy>", forget, add="+")
    return outer, inner


def flow_row(parent, *, gap: int = 6, **frame_kw):
    """A frame that arranges its children (create them in it; don't pack or grid them) left to
    right in creation order, wrapping onto more rows when they don't fit its width."""
    frame = ttk.Frame(parent, **frame_kw)
    state = {"key": None}

    def reflow(_e=None):
        width = frame.winfo_width()
        kids = [k for k in frame.winfo_children() if k.winfo_manager() in ("", "place")]
        if not kids:
            return
        for k in kids:  # a child whose size changes (new label, UI scale) re-flows the row
            if not getattr(k, "_flow_bound", False):
                k.bind("<Configure>", reflow, add="+")
                k._flow_bound = True
        if width <= 1:  # not shown yet: one row, so the window can size itself from it
            width = sum(k.winfo_reqwidth() + gap for k in kids)
        key = (width, tuple((k.winfo_reqwidth(), k.winfo_reqheight()) for k in kids))
        if state["key"] == key:
            return
        state["key"] = key
        x = y = row_h = 0
        for k in kids:
            w, h = k.winfo_reqwidth(), k.winfo_reqheight()
            if x and x + w > width:
                x, y, row_h = 0, y + row_h + gap, 0
            k.place(x=x, y=y)
            x, row_h = x + w + gap, max(row_h, h)
        frame.configure(height=y + row_h)

    frame.bind("<Configure>", reflow, add="+")
    frame.reflow = lambda: frame.after_idle(reflow)
    return frame
