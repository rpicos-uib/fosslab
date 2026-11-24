"""Hierarchy browser: the whole design tree of a schematic, with each cell's
views and verification status, and every view one double-click away."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Callable

from .. import hierarchy, tools
from ..workspace import View, Workspace
from . import style


class HierarchyWindow(tk.Toplevel):
    def __init__(self, master, ws: Workspace, sch: Path,
                 reveal: Callable[[str, str], None] | None = None):
        super().__init__(master)
        self.ws, self.sch, self.reveal = ws, Path(sch), reveal
        self.nodes: dict[str, hierarchy.Node] = {}
        self.title(f"Hierarchy: {self.sch.stem}")
        self.geometry("980x560")
        style.apply(self)

        bar = ttk.Frame(self, padding=8)
        bar.pack(fill="x")
        ttk.Label(bar, text=f"Top: {self.sch}", style="Head.TLabel").pack(side="left")
        ttk.Button(bar, text="Refresh", command=self.refresh).pack(side="right")
        self.show_pdk = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="Show PDK devices", variable=self.show_pdk,
                        command=self.refresh).pack(side="right", padx=8)

        cols = ("cell", "views", "drc", "lvs", "pex")
        frame = ttk.Frame(self, padding=(8, 0, 8, 8))
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, columns=cols, selectmode="browse")
        self.tree.heading("#0", text="Instance")
        self.tree.heading("cell", text="Library / cell")
        self.tree.heading("views", text="Views")
        for c, t in (("drc", "DRC"), ("lvs", "LVS"), ("pex", "PEX")):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=50, anchor="center", stretch=False)
        self.tree.column("#0", width=230)
        self.tree.column("cell", width=280)
        self.tree.column("views", width=250)
        ys = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ys.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ys.pack(side="right", fill="y")
        self.tree.tag_configure("pdk", foreground=style.MUTED)
        self.tree.tag_configure("missing", foreground=style.FAIL)

        self.status = ttk.Label(self, padding=(8, 0, 8, 8), style="Muted.TLabel",
                                text="Double-click: open schematic (or symbol). Right-click: more.")
        self.status.pack(fill="x")

        self.menu = tk.Menu(self)
        self.tree.bind("<Double-1>", lambda e: self._open("schematic"))
        self.tree.bind("<Button-3>", self._popup)
        self.refresh()

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.nodes.clear()
        root = hierarchy.build(self.ws, self.sch)
        self._insert("", root, top=True)
        counts = hierarchy.flatten_counts(root)
        design = sum(v for k, v in counts.items() if not k.startswith(("sg13g2_pr/", "devices/")))
        prim = sum(v for k, v in counts.items() if k.startswith("sg13g2_pr/"))
        self.status.configure(text=f"{design} block instances, {prim} PDK devices in total. "
                                   "Double-click: open schematic. Right-click: more.")

    def _insert(self, parent: str, node: hierarchy.Node, top: bool = False) -> None:
        is_ws = bool(node.lib) and any(lib.name == node.lib for lib in
                                       self.ws.libraries(include_pdk=False))
        if not top and not is_ws and node.is_leaf and not self.show_pdk.get():
            return
        views = ""
        drc = lvs = pex = ""
        if is_ws:
            vs = [v.label for v in self.ws.views(node.lib, node.cell) if not v.derived]
            views = ", ".join(dict.fromkeys(vs))
            st = self.ws.status(node.lib, node.cell)
            drc, lvs, pex = (style.MARK.get(st.get(f), "") for f in ("drc", "lvs", "pex"))
        elif node.symbol is None:
            views = "symbol not found"
        else:
            views = "PDK device" if node.is_leaf else "schematic"
        name = f"{node.lib}/{node.cell}" if node.lib else node.cell
        label = node.cell if top else node.instance
        if node.recursive:
            views += "  (recursive!)"
        tags = ("missing",) if node.symbol is None and not top else (() if is_ws or top else ("pdk",))
        iid = self.tree.insert(parent, "end", text=label, open=True,
                               values=(name, views, drc, lvs, pex), tags=tags)
        self.nodes[iid] = node
        for child in node.children:
            self._insert(iid, child)

    def _selected(self) -> hierarchy.Node | None:
        sel = self.tree.selection()
        return self.nodes.get(sel[0]) if sel else None

    def _open(self, kind: str) -> None:
        node = self._selected()
        if node is None:
            return
        if kind == "schematic" and node.schematic is not None:
            tools.open_xschem(self.ws, node.schematic)
        elif kind in ("schematic", "symbol") and node.symbol is not None:
            tools.open_xschem(self.ws, node.symbol)
        elif kind == "layout" and node.lib:
            try:
                views = [v for v in self.ws.views(node.lib, node.cell) if v.kind == "layout"]
            except KeyError:
                views = []
            if views:
                tools.open_view(self.ws, views[0])
            else:
                self.bell()
        elif kind == "veriloga" and node.lib:
            p = self.ws.view_path(node.lib, node.cell, "veriloga")
            if p.is_file():
                tools.open_view(self.ws, View("veriloga", p))

    def _popup(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        self.tree.selection_set(iid)
        node = self.nodes[iid]
        m = self.menu
        m.delete(0, "end")
        m.add_command(label="Open schematic", command=lambda: self._open("schematic"),
                      state="normal" if node.schematic else "disabled")
        m.add_command(label="Open symbol", command=lambda: self._open("symbol"),
                      state="normal" if node.symbol else "disabled")
        m.add_command(label="Open layout", command=lambda: self._open("layout"))
        m.add_command(label="Open Verilog-A", command=lambda: self._open("veriloga"))
        if self.reveal and node.lib:
            m.add_separator()
            m.add_command(label="Show in Library Manager",
                          command=lambda: self.reveal(node.lib, node.cell))
        if node.schematic:
            m.add_command(label="Hierarchy from here",
                          command=lambda: HierarchyWindow(self.master, self.ws, node.schematic,
                                                          self.reveal))
        m.tk_popup(event.x_root, event.y_root)
