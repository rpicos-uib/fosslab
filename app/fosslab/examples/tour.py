"""The annotated picture of the Library Manager for the tutorial's
"Getting started" chapter: the real window, with numbered markers placed from
the positions of its own widgets (so they stay right if the window changes).

Used by examples/shots.py; the numbers match the table in
wordpress/fosslab-tutorial/content/01-getting-started.html.
"""

from __future__ import annotations

import re
import subprocess
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from PIL import Image, ImageDraw, ImageFont

RED = (214, 39, 40)
R = 13  # badge radius


def _font(size: int):
    for f in ("DejaVuSans-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def badge(im: Image.Image, n: int, x: int, y: int) -> None:
    d = ImageDraw.Draw(im)
    d.ellipse((x - R - 2, y - R - 2, x + R + 2, y + R + 2), fill=(255, 255, 255))
    d.ellipse((x - R, y - R, x + R, y + R), fill=RED)
    d.text((x, y), str(n), fill=(255, 255, 255), font=_font(15), anchor="mm")


def _widgets(w):
    yield w
    for c in w.winfo_children():
        yield from _widgets(c)


def _find_button(root, text: str):
    for w in _widgets(root):
        if isinstance(w, ttk.Button) and str(w.cget("text")) == text:
            return w
    raise LookupError(text)


def menubar_height(root: tk.Tk) -> int:
    """Height of the menu bar, which Tk draws above the window's client area."""

    try:
        frame = int(root.wm_frame(), 16)
        out = subprocess.run(["xwininfo", "-id", str(frame)], capture_output=True, text=True).stdout
        top = int(re.search(r"Absolute upper-left Y:\s+(-?\d+)", out).group(1))
        h = root.winfo_rooty() - top
        if 0 < h < 80:
            return h
    except (ValueError, AttributeError, OSError):
        pass
    return tkfont.nametofont("TkMenuFont").metrics("linespace") + 10


def marks(win) -> list[tuple[int, int, int]]:
    """(number, x, y) of every marker, relative to the window's client area."""

    root = win.root
    ox, oy = root.winfo_rootx(), root.winfo_rooty()
    rel = lambda w: (w.winfo_rootx() - ox, w.winfo_rooty() - oy, w.winfo_width(), w.winfo_height())  # noqa: E731
    out = []

    # 1 menu bar: just right of "Help"
    mf = tkfont.nametofont("TkMenuFont")
    menu_w = sum(mf.measure(t) + 20 for t in ("File", "Cell", "Tools", "Help"))
    out.append((1, menu_w + R + 8, -menubar_height(root) // 2))

    # 2 workspace path
    x, y, w, h = rel(win.ws_label)
    out.append((2, x + w + R + 4, y + h // 2))

    # 3 libraries
    x, y, w, h = rel(win.lib_tree)
    out.append((3, x + w - R - 8, y + h * 3 // 4))

    # 4 cells, 5 view dots, 6 results: in the empty lower part of the cell list
    ct = win.cell_tree
    x, y, w, h = rel(ct)
    by = y + h * 3 // 4
    c0 = int(ct.column("#0", "width"))
    cw = [int(ct.column(c, "width")) for c in ct["columns"]]
    out.append((4, x + c0 // 2, by))
    out.append((5, x + c0 + sum(cw[:4]) // 2, by))
    out.append((6, x + c0 + sum(cw[:4]) + sum(cw[4:]) // 2, by))

    # 7 views
    x, y, w, h = rel(win.view_tree)
    out.append((7, x + w // 2, y + h * 3 // 4))

    # 8 open buttons, 9 flow buttons, 10 simulation environment: just above them
    for n, first, last in ((8, "Schematic", "Hierarchy"), (9, "Simulate", "PEX"),
                           (10, "Sim. Environment", "Sim. Environment")):
        x1, y1, _, _ = rel(_find_button(root, first))
        x2, _, w2, _ = rel(_find_button(root, last))
        out.append((n, (x1 + x2 + w2) // 2, y1 - R - 2))

    # 11 status line: at the end of its text
    x, y, w, h = rel(win.status)
    tw = tkfont.nametofont("TkDefaultFont").measure(str(win.status.cget("text")))
    out.append((11, min(x + 8 + tw + R + 10, x + w - R - 4), y + h // 2))
    return out


def grab(win, screen) -> Image.Image:
    """The window, menu bar included, with the numbered markers."""

    root = win.root
    mb = menubar_height(root)
    x, y, w, h = root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height()
    im = screen().crop((x, y - mb, x + w, y + h)).convert("RGB")
    for n, mx, my in marks(win):
        badge(im, n, mx, my + mb)
    return im
