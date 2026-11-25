"""Click a list's column heading to sort by it: ascending, click again for
descending; an arrow marks the column. The order is kept when the list is
filled again (call ``apply()`` after refilling). Empty cells always go last.
"""

from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk
from typing import Callable

UP, DOWN = " ▲", " ▼"

# How the Library Manager's marks compare: a view's dot is one view; results
# from good to bad.
RANK = {"●": 1, "✔": 0, "!": 1, "✘": 2}


def natural(s: str):
    """'cell10' after 'cell9'; numbers as numbers; case-insensitive."""
    s = s.strip()
    if s in RANK:
        return (0, RANK[s], "")
    try:
        return (0, float(s), "")
    except ValueError:
        pass
    return (1, 0, [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)])


class Sorter:
    def __init__(self, tree: ttk.Treeview, keys: dict[str, Callable[[str], object]] | None = None,
                 on_sort: Callable[[], None] | None = None):
        self.tree = tree
        self.keys = keys or {}
        self.on_sort = on_sort
        self.col: str | None = None
        self.reverse = False
        self.titles: dict[str, str] = {}
        self.widths: dict[str, int] = {}
        for c in ("#0",) + tuple(tree["columns"]):
            self.titles[c] = tree.heading(c, "text")
            tree.heading(c, command=lambda c=c: self.click(c))

    def _fit(self, col: str) -> None:
        """Narrow columns (e.g. "DRC") widen while they show the arrow."""
        if not self.tree.column(col, "stretch"):
            from tkinter import font as tkfont
            f = tkfont.nametofont("TkHeadingFont", root=self.tree)
            need = int(f.measure(self.tree.heading(col, "text"))) + 26
            self.widths.setdefault(col, int(self.tree.column(col, "width")))
            self.tree.column(col, width=max(self.widths[col], need))

    def title(self, col: str) -> str:
        return self.titles.get(col, "")

    def click(self, col: str) -> None:
        if col == self.col:
            self.reverse = not self.reverse
        else:
            self.col, self.reverse = col, False
        for c, t in self.titles.items():
            self.tree.heading(c, text=t + ((DOWN if self.reverse else UP) if c == self.col else ""))
            if c in self.widths and c != self.col:
                self.tree.column(c, width=self.widths.pop(c))
        self._fit(col)
        self.apply()
        if self.on_sort:
            self.on_sort()

    def _value(self, iid: str) -> str:
        return str(self.tree.item(iid, "text") if self.col == "#0" else self.tree.set(iid, self.col))

    def apply(self, parent: str = "") -> None:
        if self.col is None:
            return
        key = self.keys.get(self.col, natural)
        items = list(self.tree.get_children(parent))
        full = [i for i in items if self._value(i).strip()]
        empty = [i for i in items if not self._value(i).strip()]
        full.sort(key=lambda i: key(self._value(i)), reverse=self.reverse)
        for n, i in enumerate(full + empty):
            self.tree.move(i, parent, n)
        sel = self.tree.selection()
        if sel:
            self.tree.see(sel[0])
