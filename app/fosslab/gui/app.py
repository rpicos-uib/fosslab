"""The Library Manager: libraries | cells | views.

In supervisor mode a "Student" selector switches the whole window to a
student's workspace, read-only; the Roster window summarises everyone.
"""

from __future__ import annotations

import os
import queue
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from .. import __version__, config, flows, ipc, templates, tools
from ..workspace import KIND_BY_NAME, VIEW_KINDS, Library, View, Workspace, fmt_time
from . import style
from .flow_window import FlowWindow
from .hierarchy_window import HierarchyWindow

MY_WS = "— my workspace —"


def _short(p: Path) -> str:
    """A path for display: ~ for the home directory, and never too long."""

    s = str(p)
    home = str(Path.home())
    if s == home or s.startswith(home + "/"):
        s = "~" + s[len(home):]
    return s if len(s) <= 70 else "..." + s[-67:]


class MainWindow:
    def __init__(self, root: tk.Tk, ws: Workspace, supervisor: bool = False):
        self.root = root
        self.home_ws = ws
        self.ws = ws
        self.supervisor = supervisor
        self.student = ""
        self.libs: dict[str, Library] = {}
        self.cell_rows: dict[str, str] = {}
        self.view_rows: dict[str, View] = {}
        style.apply(root)
        root.title("FOSSLab Supervisor" if supervisor else "FOSSLab Library Manager")
        root.geometry("1180x700")
        root.minsize(900, 500)
        self._build_menu()
        self._build()
        self.refresh_libraries()
        root.bind("<FocusIn>", self._on_focus)
        root.bind("<F5>", lambda e: self.refresh_all())
        # Messages arrive on the server's thread; Tk is only touched here.
        self.inbox: queue.Queue = queue.Queue()
        self.server = ipc.Server(self.inbox.put, mode="supervisor" if supervisor else "main")
        try:
            self.server.start()
        except OSError:
            pass
        root.protocol("WM_DELETE_WINDOW", self.quit)
        self._poll_inbox()

    def _poll_inbox(self) -> None:
        try:
            while True:
                self._on_message(self.inbox.get_nowait())
        except queue.Empty:
            pass
        self.root.after(200, self._poll_inbox)

    # --- layout -------------------------------------------------------------------

    def _build_menu(self) -> None:
        mb = tk.Menu(self.root)
        self.root.config(menu=mb)
        f = tk.Menu(mb)
        mb.add_cascade(label="File", menu=f)
        f.add_command(label="New library...", command=self.new_library)
        f.add_command(label="New cell...", command=self.new_cell, accelerator="Ctrl+N")
        f.add_separator()
        f.add_command(label="Open terminal in workspace", command=lambda: tools.open_terminal(self.ws.root))
        f.add_command(label="Edit library definitions (fosslab.lib)",
                      command=lambda: tools.open_editor(self.ws.lib_file))
        f.add_command(label="Refresh", command=self.refresh_all, accelerator="F5")
        f.add_separator()
        f.add_command(label="Quit", command=self.quit, accelerator="Ctrl+Q")
        self.root.bind("<Control-q>", lambda e: self.quit())
        self.root.bind("<Control-n>", lambda e: self.new_cell())

        self.cell_menu = tk.Menu(mb, postcommand=lambda: self._fill_cell_menu(self.cell_menu))
        mb.add_cascade(label="Cell", menu=self.cell_menu)

        t = tk.Menu(mb)
        mb.add_cascade(label="Tools", menu=t)
        t.add_command(label="xschem (schematics)", command=self._start_xschem)
        t.add_command(label="KLayout (layout)",
                      command=lambda: tools.spawn(["klayout", "-e", "-n", config.KLAYOUT_TECH],
                                                  cwd=self.ws.root, env=tools.ws_env(self.ws)))
        t.add_command(label="Magic (layout)",
                      command=lambda: tools.spawn(["magic", "-d", "XR", "-rcfile", str(config.IHP_MAGICRC)],
                                                  cwd=self.ws.root))
        t.add_command(label="Terminal", command=lambda: tools.open_terminal(self.ws.root))
        t.add_separator()
        t.add_command(label="Run self-test (all tools and flows)", command=self.selftest)
        t.add_command(label="Retake tutorial screenshots...", command=self.open_shots)
        t.add_separator()
        ui = tk.Menu(t)
        t.add_cascade(label="Interface", menu=ui)
        self.ui_var = tk.StringVar(value=style.mode())
        for value, label in (("new", "New interface"), ("classic", "Classical interface")):
            ui.add_radiobutton(label=label, value=value, variable=self.ui_var,
                               command=lambda: self.set_interface(self.ui_var.get()))

        h = tk.Menu(mb)
        mb.add_cascade(label="Help", menu=h)
        if config.TUTORIAL_URL:
            h.add_command(label="Tutorial", command=lambda: webbrowser.open(config.TUTORIAL_URL))
        h.add_command(label="Quick guide", command=self.quick_guide)
        h.add_command(label="About", command=lambda: messagebox.showinfo(
            "FOSSLab", f"FOSSLab {__version__}\nIHP SG13G2 design manager\nPDK: {config.PDK_PATH}",
            parent=self.root))

    def _build(self) -> None:
        top = ttk.Frame(self.root, padding=(8, 8, 8, 4))
        top.pack(fill="x")
        # Right-hand widgets first, so a long path never pushes them away.
        if self.supervisor:
            ttk.Button(top, text="Roster...", command=self.open_roster).pack(side="right")
            self.student_var = tk.StringVar(value=MY_WS)
            names = [MY_WS] + [u for u, _ in config.roster()]
            cb = ttk.Combobox(top, textvariable=self.student_var, values=names, width=22,
                              state="readonly")
            cb.pack(side="right", padx=6)
            cb.bind("<<ComboboxSelected>>", lambda e: self.switch_student(self.student_var.get()))
            ttk.Label(top, text="Student:", style="Head.TLabel").pack(side="right")
        ttk.Label(top, text="Workspace:", style="Head.TLabel").pack(side="left")
        self.ro_label = ttk.Label(top, text="READ ONLY", style="RO.TLabel")
        self.ws_label = ttk.Label(top, text=_short(self.ws.root))
        self.ws_label.pack(side="left", padx=(4, 12))

        panes = ttk.PanedWindow(self.root, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=8, pady=4)

        # Libraries
        lf = ttk.Frame(panes)
        ttk.Label(lf, text="Libraries", style="Head.TLabel").pack(anchor="w")
        self.lib_tree = ttk.Treeview(lf, show="tree", selectmode="browse")
        self.lib_tree.pack(fill="both", expand=True)
        self.lib_tree.tag_configure("ro", foreground=style.MUTED)
        self.lib_tree.bind("<<TreeviewSelect>>", lambda e: self.refresh_cells())
        self.lib_tree.bind("<Button-3>", self._lib_popup)
        panes.add(lf, weight=1)

        # Cells
        cf = ttk.Frame(panes)
        head = ttk.Frame(cf)
        head.pack(fill="x")
        ttk.Label(head, text="Cells", style="Head.TLabel").pack(side="left")
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *a: self.refresh_cells())
        ttk.Entry(head, textvariable=self.filter_var, width=16).pack(side="right")
        ttk.Label(head, text="filter", style="Muted.TLabel").pack(side="right", padx=4)
        cols = ("sch", "sym", "lay", "sim", "drc", "lvs", "pex")
        self.cell_tree = ttk.Treeview(cf, columns=cols, selectmode="browse")
        self.cell_tree.heading("#0", text="Cell")
        self.cell_tree.column("#0", width=200)
        for c, t in zip(cols, ("Sch", "Sym", "Lay", "Sim", "DRC", "LVS", "PEX")):
            self.cell_tree.heading(c, text=t)
            self.cell_tree.column(c, width=style.col_width(self.root, t, 42), anchor="center", stretch=False)
        self.cell_tree.tag_configure("fail", foreground=style.FAIL)
        self.cell_tree.pack(fill="both", expand=True)
        self.cell_tree.bind("<<TreeviewSelect>>", lambda e: self.refresh_views())
        self.cell_tree.bind("<Double-1>", lambda e: self.open_cell_default())
        self.cell_tree.bind("<Button-3>", self._cell_popup)
        panes.add(cf, weight=2)

        # Views
        vf = ttk.Frame(panes)
        ttk.Label(vf, text="Views", style="Head.TLabel").pack(anchor="w")
        self.view_tree = ttk.Treeview(vf, columns=("file", "date"), selectmode="browse")
        self.view_tree.heading("#0", text="View")
        self.view_tree.heading("file", text="File")
        self.view_tree.heading("date", text="Modified")
        self.view_tree.column("#0", width=150)
        self.view_tree.column("file", width=170)
        self.view_tree.column("date", width=120, stretch=False)
        self.view_tree.tag_configure("derived", foreground=style.MUTED)
        self.view_tree.pack(fill="both", expand=True)
        self.view_tree.bind("<Double-1>", lambda e: self.open_selected_view())
        self.view_tree.bind("<Button-3>", self._view_popup)
        panes.add(vf, weight=2)

        # Action buttons for the selected cell
        bar = ttk.Frame(self.root, padding=(8, 2))
        bar.pack(fill="x")
        for text, cmd in (("Schematic", lambda: self.open_kind("schematic")),
                          ("Symbol", lambda: self.open_kind("symbol")),
                          ("Layout", lambda: self.open_kind("layout")),
                          ("Hierarchy", self.open_hierarchy)):
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=(0, 4))
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        for text, flow in (("Simulate", "sim"), ("DRC", "drc"), ("LVS", "lvs"), ("PEX", "pex")):
            ttk.Button(bar, text=text, command=lambda f=flow: self.run_flow(f)).pack(side="left", padx=(0, 4))
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(bar, text="Sim. Environment", command=self.open_simenv).pack(side="left")

        self.status = ttk.Label(self.root, padding=(8, 2, 8, 6), style="Muted.TLabel")
        self.status.pack(fill="x")
        self._info("Right-click a library, cell or view for everything you can do with it.")

    def _start_xschem(self) -> None:
        rc, env = tools.xschem_setup(self.ws)
        tools.spawn(["xschem", "--rcfile", str(rc)], cwd=self.ws.root, env=env)

    # --- selection helpers ------------------------------------------------------------

    def _info(self, text: str) -> None:
        self.status.configure(text=text)

    def current_lib(self) -> Library | None:
        sel = self.lib_tree.selection()
        return self.libs.get(sel[0]) if sel else None

    def current_cell(self) -> str | None:
        sel = self.cell_tree.selection()
        return self.cell_rows.get(sel[0]) if sel else None

    def current_view(self) -> View | None:
        sel = self.view_tree.selection()
        return self.view_rows.get(sel[0]) if sel else None

    def _need_cell(self) -> tuple[Library, str] | None:
        lib, cell = self.current_lib(), self.current_cell()
        if lib is None or cell is None:
            messagebox.showinfo("FOSSLab", "Select a cell first.", parent=self.root)
            return None
        return lib, cell

    def _writable(self, lib: Library) -> bool:
        if lib.readonly or self.ws.readonly:
            messagebox.showinfo("FOSSLab", f"Library {lib.name} is read only.\n"
                                "Copy the cell to one of your libraries to change it.",
                                parent=self.root)
            return False
        return True

    # --- refresh ------------------------------------------------------------------------

    def refresh_all(self) -> None:
        lib, cell = self.current_lib(), self.current_cell()
        self.refresh_libraries(select=lib.name if lib else None, cell=cell)

    def refresh_libraries(self, select: str | None = None, cell: str | None = None) -> None:
        self.lib_tree.delete(*self.lib_tree.get_children())
        self.libs.clear()
        if not self.ws.exists():
            self._info(f"No workspace in {self.ws.root}")
            self.refresh_cells()
            return
        mine = self.lib_tree.insert("", "end", text="Workspace", open=True)
        pdk = self.lib_tree.insert("", "end", text="PDK and examples (read only)", open=True)
        first = None
        for lib in self.ws.libraries():
            is_pdk = lib.flat
            iid = self.lib_tree.insert(pdk if is_pdk else mine, "end", text=lib.name,
                                       tags=("ro",) if lib.readonly else ())
            self.libs[iid] = lib
            if first is None and not is_pdk:
                first = iid
            if lib.name == select:
                first = iid
        if first:
            self.lib_tree.selection_set(first)
            self.lib_tree.see(first)
        self.refresh_cells(select=cell)

    def refresh_cells(self, select: str | None = None) -> None:
        keep = select or self.current_cell()
        self.cell_tree.delete(*self.cell_tree.get_children())
        self.cell_rows.clear()
        lib = self.current_lib()
        if lib is None:
            self.refresh_views()
            return
        flt = self.filter_var.get().strip().lower()
        target = None
        for cell in self.ws.cells(lib):
            if flt and flt not in cell.lower():
                continue
            row = self._cell_row(lib, cell)
            failing = "✘" in row
            iid = self.cell_tree.insert("", "end", text=cell, values=row,
                                        tags=("fail",) if failing else ())
            self.cell_rows[iid] = cell
            if cell == keep:
                target = iid
        if target:
            self.cell_tree.selection_set(target)
            self.cell_tree.see(target)
        self.refresh_views()

    def _cell_row(self, lib: Library, cell: str) -> tuple[str, ...]:
        kinds = {v.kind for v in self.ws.views(lib, cell)} if not lib.flat else set()
        if lib.flat:
            for k in ("schematic", "symbol"):
                if self.ws.view_path(lib, cell, k).is_file():
                    kinds.add(k)
            if lib.layout_file:
                kinds.add("layout")
        dot = lambda k: "●" if k in kinds else ""  # noqa: E731
        st = self.ws.status(lib.name, cell) if not lib.flat else None
        mark = lambda f: style.MARK.get(st.get(f), "") if st else ""  # noqa: E731
        return (dot("schematic"), dot("symbol"), dot("layout"), mark("sim"),
                mark("drc"), mark("lvs"), mark("pex"))

    def refresh_views(self) -> None:
        self.view_tree.delete(*self.view_tree.get_children())
        self.view_rows.clear()
        lib, cell = self.current_lib(), self.current_cell()
        if lib is None or cell is None:
            if lib is not None:
                self._info(lib.description or f"{lib.name}: {lib.path}")
            return
        for v in self.ws.views(lib, cell):
            try:
                date = fmt_time(v.path.stat().st_mtime)
            except OSError:
                date = ""
            label = v.label if v.path.stem == cell or v.derived or v.cell_in_file else f"{v.label} ({v.path.stem})"
            iid = self.view_tree.insert("", "end", text=label,
                                        values=(v.path.name + (f" : {v.cell_in_file}" if v.cell_in_file else ""), date),
                                        tags=("derived",) if v.derived else ())
            self.view_rows[iid] = v
        st = self.ws.status(lib.name, cell)
        notes = [f"{f.upper()}: {r.get('summary', '')}" for f, r in st.results.items()]
        self._info(f"{lib.name}/{cell}   " + ("   |   ".join(notes) if notes else
                                              "Double-click a view to open it."))

    def _on_focus(self, event) -> None:
        if event.widget is self.root:
            self.refresh_views()

    def _on_message(self, msg: dict) -> None:
        if msg.get("cmd") == "reveal":
            self.reveal(msg.get("lib", ""), msg.get("cell", ""))
        elif msg.get("cmd") == "refresh":
            self.refresh_all()

    def reveal(self, lib: str, cell: str) -> None:
        self.refresh_libraries(select=lib, cell=cell)
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    # --- opening views ---------------------------------------------------------------------

    def open_selected_view(self) -> None:
        v = self.current_view()
        if v:
            tools.open_view(self.ws, v)
            self._info(f"Opened {v.path}")

    def open_kind(self, kind: str) -> None:
        sel = self._need_cell()
        if not sel:
            return
        lib, cell = sel
        views = [v for v in self.ws.views(lib, cell) if v.kind == kind]
        views.sort(key=lambda v: v.path.stem != cell)
        if views:
            tools.open_view(self.ws, views[0])
            return
        if lib.readonly or self.ws.readonly:
            messagebox.showinfo("FOSSLab", f"{lib.name}/{cell} has no {kind} view.", parent=self.root)
            return
        if messagebox.askyesno("FOSSLab", f"{lib.name}/{cell} has no {kind} view. Create it?",
                               parent=self.root):
            self.create_view(kind, open_after=True)

    def open_cell_default(self) -> None:
        sel = self._need_cell()
        if not sel:
            return
        lib, cell = sel
        views = [v for v in self.ws.views(lib, cell) if not v.derived]
        views.sort(key=lambda v: (v.path.stem != cell, [k.name for k in VIEW_KINDS].index(v.kind)))
        if views:
            tools.open_view(self.ws, views[0])

    def open_hierarchy(self) -> None:
        sel = self._need_cell()
        if not sel:
            return
        lib, cell = sel
        v = self.current_view()
        sch = v.path if v and v.kind == "schematic" else self.ws.view_path(lib, cell, "schematic")
        if not sch.is_file():
            messagebox.showinfo("FOSSLab", f"{lib.name}/{cell} has no schematic.", parent=self.root)
            return
        HierarchyWindow(self.root, self.ws, sch, reveal=self.reveal)

    # --- creating and changing -------------------------------------------------------------

    def new_library(self) -> None:
        if self.ws.readonly:
            return
        name = simpledialog.askstring("New library", "Library name:", parent=self.root)
        if not name:
            return
        try:
            self.ws.add_library(name)
        except (ValueError, PermissionError) as e:
            messagebox.showerror("FOSSLab", str(e), parent=self.root)
            return
        self.refresh_libraries(select=name)

    def new_cell(self) -> None:
        lib = self.current_lib()
        if lib is None or not self._writable(lib):
            return
        dlg = NewCellDialog(self.root, lib.name)
        if not dlg.result:
            return
        cell, kinds = dlg.result
        try:
            self.ws.new_cell(lib.name, cell)
            for k in kinds:
                templates.create_view(self.ws, lib.name, cell, k)
        except (ValueError, PermissionError, FileExistsError) as e:
            messagebox.showerror("FOSSLab", str(e), parent=self.root)
            return
        self.refresh_cells(select=cell)
        if kinds:
            self.open_kind(kinds[0])

    def create_view(self, kind: str, open_after: bool = True) -> None:
        sel = self._need_cell()
        if not sel or not self._writable(sel[0]):
            return
        lib, cell = sel
        try:
            p = templates.create_view(self.ws, lib.name, cell, kind)
        except (ValueError, FileExistsError, PermissionError) as e:
            messagebox.showerror("FOSSLab", str(e), parent=self.root)
            return
        self.refresh_views()
        if open_after:
            tools.open_view(self.ws, View(kind, p))

    def update_symbol(self) -> None:
        sel = self._need_cell()
        if not sel or not self._writable(sel[0]):
            return
        lib, cell = sel
        if self.ws.view_path(lib, cell, "symbol").exists() and not messagebox.askyesno(
                "FOSSLab", "Replace the symbol with a new one made from the schematic pins?\n"
                           "(the old one is kept as .sym.bak)", parent=self.root):
            return
        try:
            p = templates.update_symbol(self.ws, lib.name, cell)
        except (ValueError, FileNotFoundError) as e:
            messagebox.showerror("FOSSLab", str(e), parent=self.root)
            return
        self.refresh_cells(select=cell)
        tools.open_xschem(self.ws, p)

    def new_testbench(self) -> None:
        sel = self._need_cell()
        if not sel or not self._writable(sel[0]):
            return
        lib, cell = sel
        name = simpledialog.askstring("New testbench", "Testbench cell name:",
                                      initialvalue=f"tb_{cell}", parent=self.root)
        if not name:
            return
        try:
            sch = templates.create_testbench(self.ws, lib.name, cell, name)
        except (ValueError, FileNotFoundError, PermissionError) as e:
            messagebox.showerror("FOSSLab", str(e), parent=self.root)
            return
        self.refresh_cells(select=name)
        tools.open_xschem(self.ws, sch)

    def copy_cell(self, to_my_workspace: bool = False) -> None:
        sel = self._need_cell()
        if not sel:
            return
        lib, cell = sel
        dst_ws = self.home_ws if to_my_workspace else self.ws
        targets = [l.name for l in dst_ws.libraries(include_pdk=False) if not l.readonly]
        if not targets:
            messagebox.showerror("FOSSLab", "No writable library to copy into.", parent=self.root)
            return
        dlg = CopyDialog(self.root, f"{lib.name}/{cell}", targets, cell if to_my_workspace else f"{cell}_copy")
        if not dlg.result:
            return
        dst_lib, new_name = dlg.result
        try:
            dst_ws.copy_cell(self.ws, lib.name, cell, dst_lib, new_name)
        except (ValueError, PermissionError, OSError) as e:
            messagebox.showerror("FOSSLab", str(e), parent=self.root)
            return
        if dst_ws is self.ws:
            self.refresh_libraries(select=dst_lib, cell=new_name)
        else:
            self._info(f"Copied {lib.name}/{cell} to your {dst_lib}/{new_name}")

    def rename_cell(self) -> None:
        sel = self._need_cell()
        if not sel or not self._writable(sel[0]):
            return
        lib, cell = sel
        new = simpledialog.askstring("Rename cell", f"New name for {cell}\n"
                                     "(instances in your schematics are updated):",
                                     initialvalue=cell, parent=self.root)
        if not new or new == cell:
            return
        try:
            self.ws.rename_cell(lib.name, cell, new)
        except (ValueError, PermissionError, OSError) as e:
            messagebox.showerror("FOSSLab", str(e), parent=self.root)
            return
        self.refresh_cells(select=new)

    def delete_cell(self) -> None:
        sel = self._need_cell()
        if not sel or not self._writable(sel[0]):
            return
        lib, cell = sel
        if not messagebox.askyesno("Delete cell", f"Delete {lib.name}/{cell} and all its views?\n"
                                   "This cannot be undone.", icon="warning", parent=self.root):
            return
        self.ws.delete_cell(lib.name, cell)
        self.refresh_cells()

    def copy_view(self, v: View) -> None:
        """Another view of the same kind in the same cell, e.g. a second
        Verilog-A model (opamp_2pole.va next to opamp.va)."""

        sel = self._need_cell()
        if not sel:
            return
        lib, cell = sel
        name = simpledialog.askstring("Copy view", f"Name of the copy of {v.path.name} (without {v.path.suffix}):",
                                      initialvalue=f"{v.path.stem}_2", parent=self.root)
        if not name:
            return
        try:
            from ..workspace import check_name
            name = check_name(name.strip(), "view name")
        except ValueError as e:
            messagebox.showerror("FOSSLab", str(e), parent=self.root)
            return
        dst = self.ws.cell_dir(lib, cell) / f"{name}{v.path.suffix}"
        if dst.exists():
            messagebox.showerror("FOSSLab", f"{dst.name} already exists.", parent=self.root)
            return
        dst.write_bytes(v.path.read_bytes())
        self.refresh_views()
        self._info(f"{lib.name}/{cell}: copied {v.path.name} to {dst.name}")

    def delete_view(self) -> None:
        v = self.current_view()
        lib = self.current_lib()
        if v is None or lib is None or v.cell_in_file or not self._writable(lib):
            return
        if messagebox.askyesno("Delete view", f"Delete {v.path.name}?", icon="warning",
                               parent=self.root):
            v.path.unlink(missing_ok=True)
            self.refresh_cells()

    # --- flows ------------------------------------------------------------------------------

    def run_flow(self, flow: str, **kwargs) -> None:
        sel = self._need_cell()
        if not sel:
            return
        lib, cell = sel
        if lib.flat:
            messagebox.showinfo("FOSSLab", "Copy the cell to your workspace to run flows on it.",
                                parent=self.root)
            return
        v = self.current_view()
        if flow == "sim" and v and v.kind == "schematic" and v.path.stem != cell:
            kwargs.setdefault("schematic", v.path)
        if flow == "va" and v and v.kind == "veriloga" and not v.derived:
            kwargs.setdefault("stem", v.path.stem)      # the selected model, e.g. opamp_2pole.va
        FlowWindow(self.root, self.ws, flow, lib.name, cell,
                   on_done=lambda res: self.refresh_cells(select=cell), **kwargs)

    def open_simenv(self) -> None:
        sel = self._need_cell()
        if not sel:
            return
        lib, cell = sel
        if not self.ws.view_path(lib, cell, "schematic").is_file():
            messagebox.showinfo("FOSSLab", "The Simulation Environment works on a testbench: "
                                "a cell with a schematic that simulates something.", parent=self.root)
            return
        from .simenv_window import SimEnvWindow

        SimEnvWindow(self.root, self.ws, lib.name, cell)

    def run_postlayout_sim(self) -> None:
        sel = self._need_cell()
        if not sel:
            return
        lib, cell = sel
        candidates = [c for c in self.ws.cells(lib)
                      if (self.ws.run_dir(lib.name, c, "pex") / f"{c}_pex.spice").is_file()]
        if not candidates:
            messagebox.showinfo("FOSSLab", "No cell of this library has an extracted (PEX) view yet.\n"
                                "Run PEX on the block first.", parent=self.root)
            return
        dlg = PickCellsDialog(self.root, "Simulate with extracted views",
                              "Use the extracted (PEX) netlist instead of the schematic for:",
                              candidates)
        if dlg.result:
            self.run_flow("sim", use_extracted=dlg.result)

    def show_result(self, flow: str) -> None:
        sel = self._need_cell()
        if not sel:
            return
        lib, cell = sel
        st = self.ws.status(lib.name, cell).results.get(flow)
        if not st:
            messagebox.showinfo("FOSSLab", f"No {flow.upper()} run for {lib.name}/{cell} yet.",
                                parent=self.root)
            return
        out = st.get("outputs", {})
        gds = self.ws.view_path(lib, cell, "layout")
        if flow == "drc" and out.get("reports"):
            tools.open_klayout(self.ws, gds, rdb=Path(out["reports"][0]))
        elif flow == "lvs" and out.get("lvsdb"):
            tools.open_klayout(self.ws, gds, l2n=Path(out["lvsdb"][0]))
        elif st.get("log"):
            tools.open_editor(Path(st["log"]))

    def set_interface(self, m: str) -> None:
        """Tools > Interface: switch the look of every open window, and remember it."""
        style.save_mode(m)
        style.apply(self.root, m)
        for c in self.cell_tree["columns"]:
            self.cell_tree.column(c, width=style.col_width(self.root, self.cell_tree.heading(c, "text"), 42))
        self._info("New interface." if m == "new" else "Classical interface.")

    def open_shots(self) -> None:
        from .shots_window import ShotsWindow

        ShotsWindow(self.root)

    def selftest(self) -> None:
        tools.spawn(["xterm", "-hold", "-title", "FOSSLab self-test", "-e",
                     "python3", "-m", "fosslab", "selftest"], cwd=Path.home())

    # --- context menus --------------------------------------------------------------------------

    def _fill_cell_menu(self, m: tk.Menu) -> None:
        m.delete(0, "end")
        lib, cell = self.current_lib(), self.current_cell()
        if lib is None or cell is None:
            m.add_command(label="New cell...", command=self.new_cell)
            return
        ro = lib.readonly or self.ws.readonly
        st = "disabled" if ro else "normal"
        m.add_command(label=f"{lib.name}/{cell}", state="disabled")
        m.add_separator()
        for k in ("schematic", "symbol", "layout"):
            m.add_command(label=f"Open {KIND_BY_NAME[k].label.lower()}", command=lambda k=k: self.open_kind(k))
        m.add_command(label="Hierarchy browser", command=self.open_hierarchy)
        new = tk.Menu(m)
        have = {v.kind for v in self.ws.views(lib, cell)}
        for k in VIEW_KINDS:
            new.add_command(label=k.label, command=lambda k=k.name: self.create_view(k),
                            state="disabled" if (k.name in have or ro) else "normal")
        m.add_cascade(label="New view", menu=new, state=st)
        m.add_command(label="Create/update symbol from schematic pins", command=self.update_symbol, state=st)
        m.add_command(label="New testbench for this cell...", command=self.new_testbench, state=st)
        m.add_separator()
        m.add_command(label="Simulation Environment (variables, corners, Monte Carlo)...",
                      command=self.open_simenv, state="disabled" if lib.flat else "normal")
        run = tk.Menu(m)
        run.add_command(label="Simulate", command=lambda: self.run_flow("sim"))
        run.add_command(label="Simulate with extracted views...", command=self.run_postlayout_sim)
        run.add_separator()
        run.add_command(label="DRC", command=lambda: self.run_flow("drc"))
        run.add_command(label="LVS", command=lambda: self.run_flow("lvs"))
        run.add_command(label="PEX (parasitic extraction)", command=lambda: self.run_flow("pex"))
        run.add_separator()
        run.add_command(label="Compile Verilog-A (OpenVAF)", command=lambda: self.run_flow("va"))
        m.add_cascade(label="Run", menu=run, state="disabled" if lib.flat else "normal")
        res = tk.Menu(m)
        res.add_command(label="DRC errors in KLayout", command=lambda: self.show_result("drc"))
        res.add_command(label="LVS report in KLayout", command=lambda: self.show_result("lvs"))
        res.add_command(label="PEX log", command=lambda: self.show_result("pex"))
        res.add_command(label="Simulation log", command=lambda: self.show_result("sim"))
        res.add_command(label="Terminal in simulation folder",
                        command=lambda: tools.open_terminal(self._mkdir(self.ws.sim_dir(lib.name, cell))))
        m.add_cascade(label="Results", menu=res, state="disabled" if lib.flat else "normal")
        m.add_separator()
        m.add_command(label="Copy cell...", command=self.copy_cell,
                      state="disabled" if self.ws.readonly else "normal")
        if self.supervisor and self.ws is not self.home_ws:
            m.add_command(label="Copy to my workspace...", command=lambda: self.copy_cell(True))
        m.add_command(label="Rename cell...", command=self.rename_cell, state=st)
        m.add_command(label="Delete cell", command=self.delete_cell, state=st)

    @staticmethod
    def _mkdir(p: Path) -> Path:
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _cell_popup(self, event) -> None:
        iid = self.cell_tree.identify_row(event.y)
        if iid:
            self.cell_tree.selection_set(iid)
            self.refresh_views()
        m = tk.Menu(self.root)
        self._fill_cell_menu(m)
        m.tk_popup(event.x_root, event.y_root)

    def _lib_popup(self, event) -> None:
        iid = self.lib_tree.identify_row(event.y)
        if iid:
            self.lib_tree.selection_set(iid)
        lib = self.current_lib()
        m = tk.Menu(self.root)
        m.add_command(label="New library...", command=self.new_library,
                      state="disabled" if self.ws.readonly else "normal")
        if lib:
            ro = "disabled" if (lib.readonly or self.ws.readonly) else "normal"
            m.add_command(label=f"New cell in {lib.name}...", command=self.new_cell, state=ro)
            m.add_command(label="Terminal in library folder", command=lambda: tools.open_terminal(lib.path))
            m.add_separator()
            m.add_command(label=f"Remove {lib.name} from the workspace...", state=ro,
                          command=lambda: self._remove_library(lib))
        m.tk_popup(event.x_root, event.y_root)

    def _remove_library(self, lib: Library) -> None:
        if not messagebox.askyesno("Remove library",
                                   f"Remove library {lib.name} from fosslab.lib?\n"
                                   f"Its files stay in {lib.path}.", parent=self.root):
            return
        self.ws.remove_library(lib.name)
        self.refresh_libraries()

    def _view_popup(self, event) -> None:
        iid = self.view_tree.identify_row(event.y)
        if not iid:
            return
        self.view_tree.selection_set(iid)
        v = self.view_rows[iid]
        m = tk.Menu(self.root)
        m.add_command(label="Open", command=self.open_selected_view)
        with_ = tk.Menu(m)
        for tool in ("xschem", "klayout", "magic", "editor"):
            with_.add_command(label=tool, command=lambda t=tool: tools.open_view(self.ws, v, tool=t))
        m.add_cascade(label="Open with", menu=with_)
        if v.kind == "veriloga" and not v.derived:
            m.add_command(label="Compile (OpenVAF)", command=lambda: self.run_flow("va", stem=v.path.stem))
        if v.kind == "schematic":
            m.add_command(label="Hierarchy browser",
                          command=lambda: HierarchyWindow(self.root, self.ws, v.path, reveal=self.reveal))
            m.add_command(label="Simulate this schematic", command=lambda: self.run_flow("sim"))
        m.add_command(label="Copy path", command=lambda: (self.root.clipboard_clear(),
                                                          self.root.clipboard_append(str(v.path))))
        m.add_command(label="Terminal here", command=lambda: tools.open_terminal(v.path.parent))
        if not v.derived and not v.cell_in_file:
            m.add_separator()
            lib = self.current_lib()
            if v.kind in ("schematic", "veriloga", "verilog", "spice", "notes"):
                m.add_command(label="Copy view...", command=lambda: self.copy_view(v),
                              state="disabled" if (lib is None or lib.readonly or self.ws.readonly) else "normal")
            m.add_command(label="Delete view", command=self.delete_view,
                          state="disabled" if (lib is None or lib.readonly or self.ws.readonly) else "normal")
        m.tk_popup(event.x_root, event.y_root)

    # --- supervisor ----------------------------------------------------------------------------

    def switch_student(self, user: str) -> None:
        if user == MY_WS or not user:
            self.ws, self.student = self.home_ws, ""
        else:
            home = dict(config.roster()).get(user)
            if home is None:
                return
            ws = Workspace(home / config.WS_NAME, readonly=True, owner=user,
                           run_root=self.home_ws.root / ".fosslab" / "supervisor" / user)
            if not ws.lib_file.exists():
                reason = ("no access (check the ACLs)" if ws.root.exists() and not os.access(ws.root, os.R_OK)
                          else "no workspace yet")
                messagebox.showinfo("FOSSLab", f"{user}: {reason}\n{ws.root}", parent=self.root)
                self.student_var.set(MY_WS if not self.student else self.student)
                return
            self.ws, self.student = ws, user
        self.ws_label.configure(text=_short(self.ws.root) + (f"   (student {self.student})" if self.student else ""))
        if self.ws.readonly:
            self.ro_label.pack(side="left", before=self.ws_label, padx=(4, 0))
        else:
            self.ro_label.pack_forget()
        if self.supervisor:
            self.student_var.set(self.student or MY_WS)
        self.refresh_libraries()

    def open_roster(self) -> None:
        from .supervisor import RosterWindow

        RosterWindow(self.root, self.home_ws, on_open=self.switch_student)

    def quick_guide(self) -> None:
        messagebox.showinfo("FOSSLab quick guide", QUICK_GUIDE, parent=self.root)

    def quit(self) -> None:
        self.server.stop()
        self.root.destroy()


QUICK_GUIDE = """Libraries hold cells; a cell has views (schematic, symbol, layout, ...).

Double-click a cell or view to open it in its tool:
  schematic/symbol -> xschem, layout -> KLayout, text -> editor.

Right-click anything for all actions. Typical flow for a block:
  1. New cell (with a schematic), draw it with ipin/opin/iopin pins.
  2. Create symbol from schematic pins.
  3. New testbench for the cell, then Simulate.
  4. New view > Layout, draw it in KLayout (IHP PCells).
  5. Run DRC, LVS, PEX; simulate with extracted views.

Inside xschem and KLayout, the FOSSLab menu links back here:
open the layout of a schematic (and vice versa), the hierarchy
browser, DRC/LVS/PEX."""


# --- dialogs ----------------------------------------------------------------------------------

class _Dialog(tk.Toplevel):
    def __init__(self, master, title: str):
        super().__init__(master)
        self.title(title)
        self.transient(master)
        self.result = None
        self.body = ttk.Frame(self, padding=12)
        self.body.pack(fill="both", expand=True)
        btns = ttk.Frame(self, padding=(12, 0, 12, 12))
        btns.pack(fill="x")
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="OK", style="Accent.TButton", command=self._ok).pack(side="right", padx=6)
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())

    def run(self):
        self.grab_set()
        self.wait_window()
        return self.result

    def _ok(self) -> None:
        raise NotImplementedError


class NewCellDialog(_Dialog):
    def __init__(self, master, lib: str):
        super().__init__(master, f"New cell in {lib}")
        ttk.Label(self.body, text="Cell name:").grid(row=0, column=0, sticky="w")
        self.name = tk.StringVar()
        e = ttk.Entry(self.body, textvariable=self.name, width=30)
        e.grid(row=0, column=1, sticky="ew", pady=(0, 8))
        e.focus_set()
        ttk.Label(self.body, text="Create views:").grid(row=1, column=0, sticky="nw")
        self.vars = {}
        f = ttk.Frame(self.body)
        f.grid(row=1, column=1, sticky="w")
        for i, k in enumerate(VIEW_KINDS):
            var = tk.BooleanVar(value=k.name == "schematic")
            self.vars[k.name] = var
            ttk.Checkbutton(f, text=k.label, variable=var).grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 12))
        self.run()

    def _ok(self) -> None:
        name = self.name.get().strip()
        if not name:
            return
        self.result = (name, [k for k, v in self.vars.items() if v.get()])
        self.destroy()


class CopyDialog(_Dialog):
    def __init__(self, master, what: str, libs: list[str], default_name: str):
        super().__init__(master, f"Copy {what}")
        ttk.Label(self.body, text="To library:").grid(row=0, column=0, sticky="w")
        self.lib = tk.StringVar(value=libs[0])
        ttk.Combobox(self.body, textvariable=self.lib, values=libs, state="readonly").grid(
            row=0, column=1, sticky="ew", pady=4)
        ttk.Label(self.body, text="New cell name:").grid(row=1, column=0, sticky="w")
        self.name = tk.StringVar(value=default_name)
        ttk.Entry(self.body, textvariable=self.name, width=30).grid(row=1, column=1, sticky="ew", pady=4)
        self.run()

    def _ok(self) -> None:
        self.result = (self.lib.get(), self.name.get().strip())
        self.destroy()


class PickCellsDialog(_Dialog):
    def __init__(self, master, title: str, prompt: str, cells: list[str]):
        super().__init__(master, title)
        ttk.Label(self.body, text=prompt, wraplength=360).pack(anchor="w", pady=(0, 8))
        self.vars = {}
        for c in cells:
            v = tk.BooleanVar(value=True)
            self.vars[c] = v
            ttk.Checkbutton(self.body, text=c, variable=v).pack(anchor="w")
        self.run()

    def _ok(self) -> None:
        self.result = [c for c, v in self.vars.items() if v.get()]
        self.destroy()


# --- entry points ------------------------------------------------------------------------------

def _root() -> tk.Tk:
    root = tk.Tk(className="FOSSLab")
    style.apply(root)
    return root


def run_gui(ws: Workspace, supervisor: bool = False, select: tuple[str, str] | None = None) -> int:
    if not ws.exists() and not ws.readonly:
        ws.init()
    if not ws.readonly:
        tools.xschem_setup(ws)
        tools.ensure_user_xschemrc(ws)
    root = _root()
    win = MainWindow(root, ws, supervisor=supervisor)
    if select:
        win.reveal(*select)
    root.mainloop()
    return 0


def run_hierarchy(ws: Workspace, sch: Path) -> int:
    root = _root()
    root.withdraw()
    w = HierarchyWindow(root, ws, sch, reveal=lambda lib, cell: (
        ipc.send({"cmd": "reveal", "lib": lib, "cell": cell}) or
        tools.spawn(["python3", "-m", "fosslab", "gui", "--select", f"{lib}/{cell}"], env=tools.ws_env(ws))))
    w.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()
    return 0


def run_simenv(ws: Workspace, lib: str, cell: str, setup: str = "") -> int:
    from .simenv_window import SimEnvWindow

    root = _root()
    root.withdraw()
    w = SimEnvWindow(root, ws, lib, cell, setup)
    w.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()
    return 0


def run_flow_window(ws: Workspace, flow: str, lib: str, cell: str, **kwargs) -> int:
    root = _root()
    root.withdraw()
    result = {}

    def done(res: flows.FlowResult) -> None:
        result["res"] = res
        ipc.send({"cmd": "refresh"})

    w = FlowWindow(root, ws, flow, lib, cell, on_done=done, **kwargs)
    w.protocol("WM_DELETE_WINDOW", root.destroy)
    w.bind("<Destroy>", lambda e: root.destroy() if e.widget is w else None)
    root.mainloop()
    res = result.get("res")
    return 0 if res is not None and res.ok else 1

