#!/usr/bin/env python3
"""E2E: the desktop Prompt Builder and Assets tab keep every control reachable on small screens.

Opens the real windows (needs a display; a window flashes briefly) and drives them like a user:
mouse-wheel scrolling over dropdowns, narrow and short windows, and a large screen. Checks positions
and values, not pixels.

Run:  python3 tests/test_small_screen_e2e.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import tkinter as tk  # noqa: E402
from tkinter import ttk  # noqa: E402

failures: list[str] = []


def check(cond: bool, label: str) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        failures.append(label)


def pump(root, sec: float = 0.4) -> None:
    end = time.time() + sec
    while time.time() < end:
        root.update()
        time.sleep(0.02)


def descendants(w):
    for c in w.winfo_children():
        yield c
        yield from descendants(c)


def scroll_area(win):
    canvas = next(w for w in descendants(win) if isinstance(w, tk.Canvas))
    bars = {str(b.cget("orient")): b for b in canvas.master.winfo_children() if isinstance(b, ttk.Scrollbar)}
    inner = canvas.nametowidget(canvas.itemcget(canvas.find_all()[0], "window"))
    return canvas, inner, bars["vertical"], bars["horizontal"]


def fully_inside(w, box) -> bool:
    x, y = w.winfo_rootx(), w.winfo_rooty()
    return (x >= box.winfo_rootx() and y >= box.winfo_rooty()
            and x + w.winfo_width() <= box.winfo_rootx() + box.winfo_width()
            and y + w.winfo_height() <= box.winfo_rooty() + box.winfo_height())


def wheel(w, down: bool = True, shift: bool = False) -> None:
    # X11 delivers wheel as buttons 4/5; Shift+wheel is horizontal.
    w.event_generate(f"<{'Shift-' if shift else ''}Button-{5 if down else 4}>", x=2, y=2)
    w.update()


def bring_into_view(canvas, inner, w) -> None:
    """What dragging the scrollbars does: move the view so `w` sits at its top-left."""
    total_w, total_h = inner.winfo_width(), inner.winfo_height()
    canvas.xview_moveto(max(0.0, (w.winfo_rootx() - inner.winfo_rootx() - 4) / total_w))
    canvas.yview_moveto(max(0.0, (w.winfo_rooty() - inner.winfo_rooty() - 4) / total_h))
    canvas.update()


def reachable(canvas, inner, widgets) -> list[str]:
    hidden = []
    for w in widgets:
        bring_into_view(canvas, inner, w)
        if not fully_inside(w, canvas):
            hidden.append(str(w))
    canvas.yview_moveto(0)
    canvas.xview_moveto(0)
    return hidden


def bars_match_content(canvas, inner, vsb, hsb) -> bool:
    """A bar shows exactly when content overflows; otherwise the content fills the view."""
    v_over = inner.winfo_reqheight() > canvas.winfo_height()
    h_over = inner.winfo_reqwidth() > canvas.winfo_width()
    fills = inner.winfo_width() >= canvas.winfo_width() and inner.winfo_height() >= canvas.winfo_height()
    return vsb.winfo_ismapped() == v_over and hsb.winfo_ismapped() == h_over and fills


def open_builder(root, screen):
    from studio_builder_dialog import open_builder_window

    with patch("studio_dpi.detect_monitor_size", return_value=screen):
        win = open_builder_window(root, {}, lambda *a, **k: None)
    pump(root, 0.8)
    return win


def scenario_small_screen(root) -> None:
    from studio_prompt_catalog import ALL_FIELDS

    print("\n== Prompt Builder on a 1024x600 screen ==")
    win = open_builder(root, (1024, 600))
    check(win.winfo_height() <= 540 and win.winfo_width() <= 973,
          f"the window fits the screen ({win.winfo_width()}x{win.winfo_height()})")
    canvas, inner, vsb, hsb = scroll_area(win)
    combos = [w for w in descendants(inner) if isinstance(w, ttk.Combobox)]
    check(len(combos) >= len(ALL_FIELDS) + 2, f"every dropdown is in the scroll area ({len(combos)} for {len(ALL_FIELDS)} fields + template + LLM)")
    check(vsb.winfo_ismapped(), "the form is taller than the window, so a vertical scrollbar shows")
    check(any(not fully_inside(c, canvas) for c in combos), "some dropdowns start out of view (the case being fixed)")
    check(bars_match_content(canvas, inner, vsb, hsb), "scrollbars show exactly when needed")

    # A user scrolls down with the wheel while the pointer happens to sit on a dropdown.
    # Each step uses a dropdown with real choices that is on screen at that moment.
    before = {str(c): c.get() for c in combos}
    choosy = [c for c in combos if len(c.cget("values")) > 1]
    used = set()
    for _ in range(300):
        y0 = canvas.yview()
        under = [c for c in choosy if fully_inside(c, canvas)]
        target = under[len(used) % len(under)] if under else inner
        used.add(str(target))
        wheel(target)
        if canvas.yview() == y0:
            break
    check(len(used) >= 5, f"the wheel went over {len(used)} different dropdowns on the way down")
    check(canvas.yview()[1] >= 0.999, f"wheel over a dropdown scrolls the page to the bottom ({canvas.yview()})")
    changed = [k for k, v in before.items() if root.nametowidget(k).get() != v]
    check(not changed, f"scrolling never changes a dropdown's value ({len(changed)} changed)")
    lowest = max(combos, key=lambda c: c.winfo_rooty())
    check(fully_inside(lowest, canvas), "at the bottom, the lowest dropdown is fully visible")

    # Wheel back up over the page itself.
    for _ in range(300):
        y0 = canvas.yview()
        wheel(inner, down=False)
        if canvas.yview() == y0:
            break
    check(canvas.yview()[0] == 0.0, "wheel up returns to the top")

    hidden = reachable(canvas, inner, combos)
    check(not hidden, f"every dropdown can be scrolled fully into view ({len(hidden)} can't: {hidden[:3]})")

    texts = [w for w in descendants(inner) if isinstance(w, tk.Text)]
    bring_into_view(canvas, inner, texts[-1])
    y0 = canvas.yview()
    wheel(texts[-1])
    check(canvas.yview() == y0, "wheel over the Final prompt box scrolls the box, not the page")
    canvas.yview_moveto(0)

    footer = [w for w in win.winfo_children() if not isinstance(w, tk.Toplevel) and w is not canvas.master][0]
    buttons = [w for w in footer.winfo_children() if isinstance(w, ttk.Button)]
    names = [b.cget("text") for b in buttons]
    check(any("Send" in n for n in names) and "Close" in names, f"Send and Close are in the pinned footer ({names})")
    check(all(fully_inside(b, win) for b in buttons), "every footer button is fully on screen")

    print("\n== Same window made narrow and short (600x420) ==")
    win.geometry("600x420")
    pump(root, 0.8)
    check(win.winfo_width() <= 610, f"the window could be made that small ({win.winfo_width()}x{win.winfo_height()})")
    check(vsb.winfo_ismapped() and hsb.winfo_ismapped(), "both scrollbars show")
    check(bars_match_content(canvas, inner, vsb, hsb), "scrollbars show exactly when needed")
    rows = {b.winfo_rooty() for b in buttons}
    check(len(rows) > 1, f"footer buttons wrap onto {len(rows)} rows instead of being cut off")
    check(all(fully_inside(b, win) for b in buttons), "every footer button is still fully on screen")
    check(canvas.master.winfo_height() > 40, "the scroll area keeps room even with a wrapped footer")
    x0 = canvas.xview()
    wheel(inner, shift=True)
    check(canvas.xview() != x0, "Shift+wheel scrolls sideways")
    hidden = reachable(canvas, inner, combos)
    check(not hidden, f"every dropdown can still be scrolled fully into view ({len(hidden)} can't: {hidden[:3]})")
    win.destroy()
    pump(root, 0.2)


def scenario_large_screen(root) -> None:
    print("\n== Prompt Builder on a large screen ==")
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    win = open_builder(root, (sw, sh))
    win.geometry(f"{min(sw, 1900)}x{sh - 80}")
    pump(root, 0.8)
    canvas, inner, vsb, hsb = scroll_area(win)
    check(not hsb.winfo_ismapped(), f"no sideways scrollbar at {win.winfo_width()}px wide")
    check(bars_match_content(canvas, inner, vsb, hsb), "scrollbars show exactly when needed; content fills the window")
    check(inner.winfo_width() == canvas.winfo_width(), "the form stretches to the window's full width")
    win.destroy()
    pump(root, 0.2)


def scenario_assets_tab(root) -> None:
    from studio_assets_tab import build_assets_tab

    print("\n== Assets tab (same scroll helper) in a short window ==")
    top = tk.Toplevel(root)
    top.geometry("1000x380")
    build_assets_tab(top, root)
    pump(root, 0.8)
    canvas, inner, vsb, hsb = scroll_area(top)
    check(vsb.winfo_ismapped(), "the settings column scrolls when the window is short")
    combos = [w for w in descendants(inner) if isinstance(w, ttk.Combobox)]
    before = [c.get() for c in combos]
    for _ in range(300):
        y0 = canvas.yview()
        wheel(combos[0])
        if canvas.yview() == y0:
            break
    check(canvas.yview()[1] >= 0.999 and [c.get() for c in combos] == before,
          "wheel over a dropdown scrolls the column and changes nothing")
    tree = next(w for w in descendants(top) if isinstance(w, ttk.Treeview))
    y0 = canvas.yview()
    wheel(tree)
    check(canvas.yview() == y0, "wheel over the outputs list doesn't move the settings column")
    top.destroy()
    pump(root, 0.2)


def main() -> int:
    from studio_dpi import apply_ui_scale
    from studio_themes import DEFAULT_THEME_ID, apply_theme

    root = tk.Tk()
    apply_ui_scale(root, "1.0")
    apply_theme(root, DEFAULT_THEME_ID)
    root.geometry("200x100+0+0")
    try:
        for scenario in (scenario_small_screen, scenario_large_screen, scenario_assets_tab):
            try:
                scenario(root)
            except Exception as exc:  # a crashed scenario is a failure, not a stop
                import traceback

                traceback.print_exc()
                check(False, f"{scenario.__name__} crashed: {exc}")
    finally:
        root.destroy()
    print("\nSMALL-SCREEN E2E TESTS PASSED!" if not failures else f"\n{len(failures)} FAILED:\n  - " + "\n  - ".join(failures))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
