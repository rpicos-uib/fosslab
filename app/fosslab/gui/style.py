"""Fonts, colours and ttk styles shared by all windows.

Two interfaces, chosen in Tools > Interface and remembered per user
(~/.config/fosslab/gui.json, or FOSSLAB_UI=new|classic):

- new: a flat, light theme (ttk theme "fosslab", built on clam) with a
  modern font, roomier lists and an accent colour;
- classic: the plain clam look of the first FOSSLab versions.
"""

from __future__ import annotations

import json
import os
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk

MONO = "TkFixedFont"   # a named font: follows the interface

PASS = "#1b7f3b"
FAIL = "#b3261e"
WARN = "#9a6700"
MUTED = "#6b6f76"
ACCENT = "#1f5fa8"
RO_BG = "#fff4e5"

MARK = {"pass": "✔", "fail": "✘", "error": "!", "": ""}

MODES = ("new", "classic")
_PREFS = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "fosslab" / "gui.json"

# the new interface's palette
BG = "#f4f6f9"        # window
SURFACE = "#ffffff"   # lists, entries, text
LINE = "#d9dee5"      # borders
HOVER = "#eaeef3"
TEXT = "#1f2933"
SOFT = "#e3edfb"      # selected row
BLUE = "#2563eb"      # accent
BLUE_DARK = "#1d4ed8"

BTN_LINE = "#c6cdd6"

_applied: dict[int, str] = {}
_keep: list = []      # fonts and images Tk styles refer to: Python must not delete them


def mode() -> str:
    env = os.environ.get("FOSSLAB_UI", "").lower()
    if env in MODES:
        return env
    try:
        m = json.loads(_PREFS.read_text()).get("interface", "new")
        return m if m in MODES else "new"
    except (OSError, ValueError, AttributeError):
        return "new"


def save_mode(m: str) -> None:
    try:
        _PREFS.parent.mkdir(parents=True, exist_ok=True)
        try:
            d = json.loads(_PREFS.read_text())
        except (OSError, ValueError):
            d = {}
        d["interface"] = m
        _PREFS.write_text(json.dumps(d, indent=1) + "\n")
    except OSError:
        pass


def _family(root: tk.Misc, *names: str) -> str | None:
    have = set(tkfont.families(root))
    return next((n for n in names if n in have), None)


def apply(widget: tk.Misc, m: str | None = None) -> None:
    """Style the application (once per Tk instance, or again to switch interface)."""

    root = widget.winfo_toplevel()
    key = id(root.tk)
    m = m or _applied.get(key) or mode()
    if _applied.get(key) == m:
        return
    _applied[key] = m
    s = ttk.Style(root)
    root.option_add("*Menu.tearOff", 0)
    if m == "new":
        _new(root, s)
    else:
        _classic(root, s)
    _restyle_tk(root, m)


def _fonts(root, family: str | None, size: int, mono: str | None) -> tuple:
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont",
                 "TkSmallCaptionFont", "TkIconFont", "TkTooltipFont"):
        f = tkfont.nametofont(name)
        f.configure(size=size, weight="normal", slant="roman")
        if family:
            f.configure(family=family)
    tkfont.nametofont("TkFixedFont").configure(size=size, **({"family": mono} if mono else {}))
    base = tkfont.nametofont("TkDefaultFont")
    bold = base.copy()
    bold.configure(weight="bold")
    big = base.copy()
    big.configure(size=size + 2, weight="bold")
    _keep.extend((bold, big))
    return base, bold, big


def col_width(widget: tk.Misc, text: str, minimum: int = 40) -> int:
    """Width of a list column whose heading is ``text``, in the current interface."""

    f = tkfont.nametofont("TkHeadingFont", root=widget)
    bold = f.copy()
    bold.configure(weight="bold")
    w = bold.measure(text)
    del bold
    return max(minimum, w + 16)


def _common(s: ttk.Style, bold, big) -> None:
    s.configure("Banner.TLabel", font=big)
    s.configure("Pass.TLabel", font=big, foreground=PASS)
    s.configure("Fail.TLabel", font=big, foreground=FAIL)
    s.configure("Error.TLabel", font=big, foreground=WARN)
    s.configure("Head.TLabel", font=bold)
    s.configure("Muted.TLabel", foreground=MUTED)
    s.configure("RO.TLabel", background=RO_BG, foreground=WARN, font=bold, padding=(8, 2))


def _classic(root, s: ttk.Style) -> None:
    if "clam" in s.theme_names():
        s.theme_use("clam")
    _, bold, big = _fonts(root, _family(root, "DejaVu Sans"), 10, _family(root, "DejaVu Sans Mono"))
    s.configure("Treeview", rowheight=22)
    _common(s, bold, big)
    s.configure("Accent.TButton", font=bold)


def _new(root, s: ttk.Style) -> None:
    family = _family(root, "Ubuntu Sans", "Ubuntu", "Lato", "Noto Sans", "Cantarell", "DejaVu Sans")
    mono = _family(root, "Ubuntu Sans Mono", "Ubuntu Mono", "Noto Sans Mono", "DejaVu Sans Mono")
    base, bold, big = _fonts(root, family, 10, mono)
    semi = bold
    if "fosslab" not in s.theme_names():
        s.theme_create("fosslab", parent="clam")
    s.theme_use("fosslab")
    flat = dict(bordercolor=LINE, lightcolor=SURFACE, darkcolor=SURFACE)
    s.configure(".", background=BG, foreground=TEXT, troughcolor=BG, focuscolor=BLUE,
                selectbackground=SOFT, selectforeground=TEXT, fieldbackground=SURFACE,
                insertcolor=TEXT, **flat)
    s.configure("TFrame", background=BG)
    s.configure("TLabel", background=BG, foreground=TEXT)
    s.configure("TButton", background=SURFACE, padding=(12, 5), relief="raised", anchor="center",
                bordercolor=BTN_LINE, lightcolor=SURFACE, darkcolor=SURFACE)
    s.map("TButton", relief=[("pressed", "raised")], background=[("disabled", BG), ("pressed", LINE), ("active", HOVER)],
          bordercolor=[("focus", BLUE)], foreground=[("disabled", MUTED)],
          lightcolor=[("pressed", LINE), ("active", HOVER)], darkcolor=[("pressed", LINE), ("active", HOVER)])
    s.configure("Accent.TButton", background=BLUE, foreground="#ffffff", font=semi,
                bordercolor=BLUE, lightcolor=BLUE, darkcolor=BLUE)
    s.map("Accent.TButton", background=[("disabled", LINE), ("pressed", BLUE_DARK), ("active", BLUE_DARK)],
          foreground=[("disabled", MUTED)], bordercolor=[("active", BLUE_DARK)],
          lightcolor=[("active", BLUE_DARK)], darkcolor=[("active", BLUE_DARK)])
    s.configure("TEntry", padding=(6, 4), **flat)
    s.map("TEntry", bordercolor=[("focus", BLUE)], lightcolor=[("focus", SURFACE)])
    s.configure("TCombobox", padding=(6, 4), arrowcolor=TEXT, background=SURFACE, **flat)
    s.map("TCombobox", bordercolor=[("focus", BLUE)], fieldbackground=[("readonly", SURFACE)],
          background=[("active", HOVER)], selectbackground=[("readonly", SURFACE)],
          selectforeground=[("readonly", TEXT)])
    s.configure("TSpinbox", padding=(6, 4), arrowcolor=TEXT, background=SURFACE, **flat)
    _indicators(root, s)
    s.configure("TCheckbutton", background=BG)
    s.map("TCheckbutton", background=[("active", BG)])
    s.configure("TRadiobutton", background=BG)
    s.map("TRadiobutton", background=[("active", BG)])
    s.configure("Treeview", background=SURFACE, fieldbackground=SURFACE, rowheight=28, **flat)
    s.map("Treeview", background=[("selected", SOFT)], foreground=[("selected", TEXT)])
    s.configure("Treeview.Heading", background=BG, foreground=MUTED, font=semi, relief="flat",
                padding=(6, 5), bordercolor=LINE, lightcolor=BG, darkcolor=BG)
    s.map("Treeview.Heading", background=[("active", HOVER)])
    s.configure("TNotebook", background=BG, tabmargins=(0, 4, 0, 0), **flat)
    s.configure("TNotebook.Tab", background=BG, foreground=MUTED, padding=(14, 6), **flat)
    s.map("TNotebook.Tab", background=[("selected", SURFACE), ("active", HOVER)],
          foreground=[("selected", BLUE)], lightcolor=[("selected", SURFACE)],
          expand=[("selected", (0, 0, 0, 0))])
    s.configure("TLabelframe", background=BG, **flat)
    s.configure("TLabelframe.Label", background=BG, foreground=MUTED, font=semi)
    s.configure("Horizontal.TProgressbar", thickness=8)
    s.configure("TProgressbar", background=BLUE, troughcolor="#e6eaf0", bordercolor=LINE,
                lightcolor=BLUE, darkcolor=BLUE, thickness=6)
    s.configure("TScrollbar", background=BG, troughcolor=BG, arrowcolor=MUTED, gripcount=0,
                bordercolor=BG, lightcolor=BG, darkcolor=BG)
    s.map("TScrollbar", background=[("active", HOVER)])
    s.configure("TPanedwindow", background=BG)
    s.configure("Sash", sashthickness=8, gripcount=0, background=BG, lightcolor=BG, bordercolor=BG)
    s.configure("TSeparator", background=LINE)
    _common(s, semi, big)
    s.configure("Head.TLabel", font=semi, foreground=TEXT)
    s.configure("RO.TLabel", padding=(10, 3))


def _indicator_png(kind: str, on: bool, disabled: bool) -> bytes | None:
    """A 20x16 check box or radio button (drawn at 4x and reduced: smooth edges)."""

    try:
        import io
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    k = 4
    im = Image.new("RGBA", (20 * k, 16 * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    box = (1 * k, 1 * k, 15 * k - 1, 15 * k - 1)
    fill = (BLUE if not disabled else MUTED) if on else SURFACE
    edge = (BLUE if not disabled else MUTED) if on else "#8d97a5"
    if kind == "check":
        d.rounded_rectangle(box, radius=3 * k, fill=fill, outline=edge, width=k + k // 2)
        if on:
            d.line([(4 * k, 8 * k), (7 * k, 11 * k), (12 * k, 5 * k)], fill="#ffffff", width=2 * k, joint="curve")
    else:
        d.ellipse(box, fill=SURFACE, outline=edge, width=k + k // 2 if not on else 5 * k)
    im = im.resize((20, 16), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _indicators(root, s: ttk.Style) -> None:
    """Modern check boxes and radio buttons (image elements of the "fosslab" theme)."""

    if "Fosslab.Checkbutton.indicator" in s.element_names():
        return
    import base64
    imgs = {}
    for kind in ("check", "radio"):
        for on in (False, True):
            for dis in (False, True):
                png = _indicator_png(kind, on, dis)
                if png is None:
                    return
                imgs[kind, on, dis] = tk.PhotoImage(master=root, data=base64.b64encode(png))
    _keep.extend(imgs.values())
    for kind, cls in (("check", "Checkbutton"), ("radio", "Radiobutton")):
        s.element_create(f"Fosslab.{cls}.indicator", "image", imgs[kind, False, False],
                         ("disabled", "selected", imgs[kind, True, True]),
                         ("disabled", imgs[kind, False, True]),
                         ("selected", imgs[kind, True, False]), sticky="w")
        s.layout(f"T{cls}", [(f"{cls}.padding", {"sticky": "nswe", "children": [
            (f"Fosslab.{cls}.indicator", {"side": "left", "sticky": ""}),
            (f"{cls}.focus", {"side": "left", "sticky": "w", "children": [
                (f"{cls}.label", {"sticky": "nswe"})]})]})])


def _tk_colours(m: str) -> dict:
    if m == "new":
        return dict(menu=dict(background=SURFACE, foreground=TEXT, activebackground=SOFT,
                              activeforeground=TEXT, relief="flat", borderwidth=1, activeborderwidth=0,
                              selectcolor=BLUE),
                    text=dict(background=SURFACE, foreground=TEXT, insertbackground=TEXT, relief="flat",
                              borderwidth=0, highlightthickness=1, highlightbackground=LINE,
                              highlightcolor=BLUE, selectbackground=SOFT, selectforeground=TEXT,
                              padx=8, pady=6),
                    window=BG)
    return dict(menu=dict(background="#d9d9d9", foreground="#000000", activebackground="#ececec",
                          activeforeground="#000000", relief="raised", borderwidth=1, activeborderwidth=1,
                          selectcolor="#000000"),
                text=dict(background="#ffffff", foreground="#000000", insertbackground="#000000",
                          relief="sunken", borderwidth=1, highlightthickness=1, highlightbackground="#d9d9d9",
                          highlightcolor="#000000", selectbackground="#c3c3c3", selectforeground="#000000",
                          padx=1, pady=1),
                window="#dcdad5")


def _restyle_tk(root: tk.Misc, m: str) -> None:
    """Colours of the plain Tk widgets (menus, text boxes, windows), new and existing."""

    c = _tk_colours(m)
    for k, v in c["menu"].items():
        root.option_add(f"*Menu.{k}", v, "interactive")
    for k, v in c["text"].items():
        root.option_add(f"*Text.{k}", v, "interactive")
    root.option_add("*Toplevel.background", c["window"], "interactive")
    root.option_add("*Canvas.background", SURFACE if m == "new" else "#ffffff", "interactive")

    def walk(w):
        try:
            if isinstance(w, tk.Menu):
                w.configure(**c["menu"])
            elif isinstance(w, tk.Text):
                w.configure(**c["text"])
            elif isinstance(w, (tk.Tk, tk.Toplevel)):
                w.configure(background=c["window"])
        except tk.TclError:
            pass
        for ch in w.winfo_children():
            walk(ch)
    walk(root)
    try:  # the menu bar of every window
        for w in [root] + [t for t in root.winfo_children() if isinstance(t, tk.Toplevel)]:
            if w["menu"]:
                w.nametowidget(w["menu"]).configure(**c["menu"])
    except tk.TclError:
        pass
