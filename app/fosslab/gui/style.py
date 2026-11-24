"""Fonts, colours and ttk styles shared by all windows."""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

MONO = ("DejaVu Sans Mono", 10)

PASS = "#1b7f3b"
FAIL = "#b3261e"
WARN = "#9a6700"
MUTED = "#6b6f76"
ACCENT = "#1f5fa8"
RO_BG = "#fff4e5"

MARK = {"pass": "✔", "fail": "✘", "error": "!", "": ""}

_done: set[int] = set()


def apply(widget: tk.Misc) -> None:
    root = widget.winfo_toplevel()
    key = id(root.tk)
    if key in _done:
        return
    _done.add(key)
    s = ttk.Style(root)
    if "clam" in s.theme_names():
        s.theme_use("clam")
    base = tkfont.nametofont("TkDefaultFont")
    base.configure(size=10)
    bold = base.copy()
    bold.configure(weight="bold")
    big = base.copy()
    big.configure(size=12, weight="bold")
    s.configure("Treeview", rowheight=22)
    s.configure("Banner.TLabel", font=big)
    s.configure("Pass.TLabel", font=big, foreground=PASS)
    s.configure("Fail.TLabel", font=big, foreground=FAIL)
    s.configure("Error.TLabel", font=big, foreground=WARN)
    s.configure("Head.TLabel", font=bold)
    s.configure("Muted.TLabel", foreground=MUTED)
    s.configure("RO.TLabel", background=RO_BG, foreground=WARN, font=bold, padding=(8, 2))
    s.configure("Accent.TButton", font=bold)
    root.option_add("*Menu.tearOff", 0)
