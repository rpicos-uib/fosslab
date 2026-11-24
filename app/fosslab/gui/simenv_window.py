"""Simulation Environment window: design variables,
outputs with specifications, corners and Monte Carlo for one testbench.

Everything shown here is saved in <tb>.simenv.json next to the testbench, so
a setup made once is there the next time (and the supervisor sees it).
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from dataclasses import fields
from pathlib import Path
from tkinter import messagebox, ttk

from .. import simenv, flows, tools
from ..workspace import Workspace
from . import style


class RowDialog(tk.Toplevel):
    """Edit one row: a list of (key, label, kind, choices)."""

    def __init__(self, master, title: str, spec: list[tuple], values: dict):
        super().__init__(master)
        self.title(title)
        self.transient(master)
        self.result = None
        self.vars: dict[str, tk.Variable] = {}
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        for i, (key, label, kind, choices) in enumerate(spec):
            ttk.Label(body, text=label).grid(row=i, column=0, sticky="w", pady=3, padx=(0, 8))
            v = values.get(key, "")
            if kind == "bool":
                var = tk.BooleanVar(value=bool(v))
                ttk.Checkbutton(body, variable=var).grid(row=i, column=1, sticky="w")
            elif kind == "choice":
                var = tk.StringVar(value="" if v is None else str(v))
                ttk.Combobox(body, textvariable=var, values=choices, width=28).grid(row=i, column=1, sticky="ew")
            else:
                var = tk.StringVar(value="" if v is None else str(v))
                ttk.Entry(body, textvariable=var, width=30).grid(row=i, column=1, sticky="ew")
            self.vars[key] = var
        btn = ttk.Frame(self, padding=(12, 0, 12, 12))
        btn.pack(fill="x")
        ttk.Button(btn, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(btn, text="OK", style="Accent.TButton", command=self._ok).pack(side="right", padx=6)
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())
        self.grab_set()
        self.wait_window()

    def _ok(self) -> None:
        self.result = {k: v.get() for k, v in self.vars.items()}
        self.destroy()


def _num(s: str) -> float | None:
    s = str(s).strip()
    return float(s) if s not in ("", "-", "None") else None


def _vars_to_text(d: dict[str, str]) -> str:
    return " ".join(f"{k}={v}" for k, v in d.items())


def _text_to_vars(s: str) -> dict[str, str]:
    out = {}
    for item in s.split():
        if "=" in item:
            k, v = item.split("=", 1)
            out[k.strip()] = v.strip()
    return out


class SimEnvWindow(tk.Toplevel):
    def __init__(self, master, ws: Workspace, lib: str, cell: str):
        super().__init__(master)
        self.ws, self.lib, self.cell = ws, lib, cell
        self.setup = simenv.Setup.load(ws, lib, cell)
        self.last: simenv.RunSet | None = None
        self.q: queue.Queue = queue.Queue()
        self.busy = False
        self.images: list[tk.PhotoImage] = []
        self.title(f"Simulation Environment: {lib}/{cell}")
        self.geometry("1120x860")
        style.apply(self)
        self._build()
        self._fill_all()
        self.after(100, self._poll)

    # --- layout -------------------------------------------------------------------------

    def _build(self) -> None:
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text=f"Testbench  {self.lib} / {self.cell}", style="Banner.TLabel").pack(side="left")
        for text, cmd in (("Save setup", self.save), ("Open schematic", self.open_schematic),
                          ("Run nominal", lambda: self.run("nominal"))):
            ttk.Button(top, text=text, command=cmd).pack(side="right", padx=(6, 0))
        if self.ws.readonly:
            ttk.Label(top, text="READ ONLY: changes are not saved", style="RO.TLabel").pack(side="right", padx=8)

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=8)

        # Design variables
        f = ttk.Frame(self.nb, padding=8)
        self.nb.add(f, text="Design variables")
        ttk.Label(f, style="Muted.TLabel", wraplength=900, text=(
            "The .param values of the testbench. Change a value here to simulate with it, "
            "without editing the schematic. Corners can override any of them.")).pack(anchor="w")
        self.var_tree = self._tree(f, ("value",), ("Variable", "Value"), (200, 200))
        self._buttons(f, (("Add", self.var_add), ("Edit", self.var_edit), ("Delete", self.var_del),
                          ("Read from schematic", self.var_scan)))
        self.var_tree.bind("<Double-1>", lambda e: self.var_edit())

        # Outputs
        f = ttk.Frame(self.nb, padding=8)
        self.nb.add(f, text="Outputs")
        ttk.Label(f, style="Muted.TLabel", wraplength=900, text=(
            "Performance measurements. Name: a result the testbench prints (with meas or print), or a new "
            "one computed by Expression, in ngspice's language: a full 'meas' statement or an expression "
            "such as vdb(out)[0]. Lower/Upper: the specification (empty: none). Scale and Unit: how to "
            "show it, e.g. 1e-6 and MHz.")).pack(anchor="w")
        self.out_tree = self._tree(f, ("expr", "label", "min", "max", "scale", "unit"),
                                   ("Name", "Expression (ngspice)", "Label", "Lower", "Upper", "Scale", "Unit"),
                                   (90, 300, 170, 60, 60, 60, 60))
        self._buttons(f, (("Add", self.out_add), ("Edit", self.out_edit), ("Delete", self.out_del),
                          ("Up", lambda: self._move(self.setup.outputs, self.out_tree, -1, self._fill_outputs)),
                          ("Down", lambda: self._move(self.setup.outputs, self.out_tree, 1, self._fill_outputs)),
                          ("Add all from last run", self.out_from_last)))
        self.out_tree.bind("<Double-1>", lambda e: self.out_edit())
        wf = ttk.Frame(f)
        wf.pack(fill="x", pady=(10, 0))
        ttk.Label(wf, text="Waveform to plot for every run:").pack(side="left")
        self.wave_var = tk.StringVar()
        ttk.Entry(wf, textvariable=self.wave_var, width=30).pack(side="left", padx=6)
        self.wave_log = tk.BooleanVar()
        ttk.Checkbutton(wf, text="log x axis", variable=self.wave_log).pack(side="left")
        ttk.Label(wf, style="Muted.TLabel", text="  e.g. vdb(out) after an ac analysis, v(out) after tran").pack(side="left")

        # Corners: a grid with one column per corner
        f = ttk.Frame(self.nb, padding=8)
        self.nb.add(f, text="Corners")
        ttk.Label(f, style="Muted.TLabel", wraplength=1000, text=(
            "One column per corner. Rows: the IHP model section of transistors, capacitors and "
            "resistors, the temperature, and every design variable (empty: the nominal value from "
            "Design variables). Click a corner's name to select its column. Only ticked corners run.")).pack(anchor="w")
        holder = ttk.Frame(f)
        holder.pack(fill="both", expand=True, pady=6)
        self.grid_canvas = tk.Canvas(holder, height=300, highlightthickness=0)
        xs = ttk.Scrollbar(holder, orient="horizontal", command=self.grid_canvas.xview)
        self.grid_canvas.configure(xscrollcommand=xs.set)
        self.grid_canvas.pack(fill="both", expand=True)
        xs.pack(fill="x")
        self.grid_frame = ttk.Frame(self.grid_canvas)
        self.grid_canvas.create_window(0, 0, window=self.grid_frame, anchor="nw")
        self.grid_frame.bind("<Configure>", lambda e: self.grid_canvas.configure(
            scrollregion=self.grid_canvas.bbox("all")))
        self.sel_corner = None
        self._buttons(f, (("Add corner", self.cor_add), ("Copy corner", self.cor_dup),
                          ("Delete corner", self.cor_del), ("Standard set...", self.cor_standard)))
        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=(6, 0))
        ttk.Button(bar, text="Run corners", style="Accent.TButton",
                   command=lambda: self.run("corners")).pack(side="right")

        # Monte Carlo
        f = ttk.Frame(self.nb, padding=8)
        self.nb.add(f, text="Monte Carlo")
        ttk.Label(f, style="Muted.TLabel", wraplength=900, text=(
            "Each run draws new random device parameters from IHP's statistical models. "
            "'mismatch': device-to-device differences on one chip (offset, matching). "
            "'process': chip-to-chip shifts of the whole process (Vth, mobility, oxide...).")).pack(anchor="w")
        form = ttk.Frame(f, padding=(0, 10))
        form.pack(anchor="w")
        self.mc_runs = tk.StringVar()
        self.mc_var = tk.StringVar()
        self.mc_seed = tk.StringVar()
        self.mc_jobs = tk.StringVar()
        for i, (label, var, widget) in enumerate((
                ("Number of runs", self.mc_runs, "entry"),
                ("Analysis variation", self.mc_var, list(simenv.VARIATIONS)),
                ("Starting run # (seed)", self.mc_seed, "entry"),
                ("Parallel jobs", self.mc_jobs, "entry"))):
            ttk.Label(form, text=label).grid(row=i, column=0, sticky="w", pady=3, padx=(0, 10))
            if widget == "entry":
                ttk.Entry(form, textvariable=var, width=10).grid(row=i, column=1, sticky="w")
            else:
                ttk.Combobox(form, textvariable=var, values=widget, width=12, state="readonly").grid(
                    row=i, column=1, sticky="w")
        ttk.Label(f, style="Muted.TLabel", text=(
            "The same first seed gives the same samples: change it to draw a new set.")).pack(anchor="w")
        ttk.Button(f, text="Run Monte Carlo", style="Accent.TButton",
                   command=lambda: self.run("montecarlo")).pack(anchor="w", pady=10)

        # Results
        f = ttk.Frame(self.nb, padding=8)
        self.nb.add(f, text="Results")
        self.res_title = ttk.Label(f, text="No run yet.", style="Head.TLabel")
        self.res_title.pack(anchor="w")
        pw = ttk.PanedWindow(f, orient="vertical")
        pw.pack(fill="both", expand=True, pady=4)
        left = ttk.Frame(pw)
        self.res_tree = ttk.Treeview(left, show="headings", height=8)
        rx = ttk.Scrollbar(left, orient="horizontal", command=self.res_tree.xview)
        self.res_tree.configure(xscrollcommand=rx.set)
        self.res_tree.pack(fill="both", expand=True)
        rx.pack(fill="x")
        self.res_tree.tag_configure("fail", foreground=style.FAIL)
        self.res_tree.tag_configure("pass", foreground=style.PASS)
        self.res_tree.bind("<<TreeviewSelect>>", lambda e: self._show_hist())
        pw.add(left, weight=1)
        self.hist = ttk.Label(pw, anchor="center")
        pw.add(self.hist, weight=3)
        rb = ttk.Frame(f)
        rb.pack(fill="x")
        ttk.Button(rb, text="Open results.csv", command=self.open_csv).pack(side="left")
        ttk.Button(rb, text="Terminal in run folder", command=self.open_folder).pack(side="left", padx=6)

        # Log + progress
        lf = ttk.Frame(self, padding=8)
        lf.pack(fill="x")
        self.progress = ttk.Progressbar(lf, mode="determinate")
        self.progress.pack(fill="x")
        self.log = tk.Text(lf, height=3, font=style.MONO, wrap="none")
        self.log.pack(fill="x", pady=(4, 0))

    def _tree(self, parent, cols, heads, widths) -> ttk.Treeview:
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True, pady=6)
        t = ttk.Treeview(frame, columns=cols, selectmode="browse", height=10)
        t.heading("#0", text=heads[0])
        t.column("#0", width=widths[0])
        for c, h, w in zip(cols, heads[1:], widths[1:]):
            t.heading(c, text=h)
            t.column(c, width=w, anchor="w")
        ys = ttk.Scrollbar(frame, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=ys.set)
        t.pack(side="left", fill="both", expand=True)
        ys.pack(side="right", fill="y")
        return t

    def _buttons(self, parent, items) -> None:
        bar = ttk.Frame(parent)
        bar.pack(fill="x")
        for text, cmd in items:
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=(0, 6))

    # --- filling ------------------------------------------------------------------------

    def _fill_all(self) -> None:
        self._fill_vars()
        self._fill_outputs()
        self._fill_corners()
        self.wave_var.set(self.setup.wave)
        self.wave_log.set(self.setup.wave_logx)
        mc = self.setup.montecarlo
        self.mc_runs.set(str(mc.runs))
        self.mc_var.set(mc.variation)
        self.mc_seed.set(str(mc.seed))
        self.mc_jobs.set(str(mc.jobs))

    def _fill_vars(self) -> None:
        self.var_tree.delete(*self.var_tree.get_children())
        for k, v in self.setup.variables.items():
            self.var_tree.insert("", "end", iid=k, text=k, values=(v,))

    def _fill_outputs(self) -> None:
        self.out_tree.delete(*self.out_tree.get_children())
        for i, o in enumerate(self.setup.outputs):
            self.out_tree.insert("", "end", iid=str(i), text=o.name,
                                 values=(o.expr or "(from the testbench)", o.label, simenv.fmt(o.min),
                                         simenv.fmt(o.max), f"{o.scale:g}", o.unit))

    ROW_LABELS = [("name", "Corner"), ("enabled", "Run"), ("mos", "MOS models"),
                  ("cap", "CAP models"), ("res", "RES models"), ("temp", "temp (°C)")]

    def _fill_corners(self) -> None:
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.cell_vars: list[dict[str, tk.Variable]] = []
        rows = self.ROW_LABELS + [(f"var:{v}", v) for v in self.setup.variables]
        corner_label = ttk.Label(self.grid_frame, text="Variables ↓  /  Corners →", style="Head.TLabel")
        corner_label.grid(row=0, column=0, sticky="w", padx=(0, 10))
        for r, (_, label) in enumerate(rows[1:], start=1):
            ttk.Label(self.grid_frame, text=label).grid(row=r, column=0, sticky="w", padx=(0, 10), pady=1)
        for c, corner in enumerate(self.setup.corners, start=1):
            vars_: dict[str, tk.Variable] = {}
            name = tk.StringVar(value=corner.name)
            vars_["name"] = name
            head = ttk.Entry(self.grid_frame, textvariable=name, width=11,
                             font=("TkDefaultFont", 9, "bold"))
            head.grid(row=0, column=c, padx=1, pady=1)
            head.bind("<FocusIn>", lambda e, i=c - 1: self._select_corner(i))
            en = tk.BooleanVar(value=corner.enabled)
            vars_["enabled"] = en
            ttk.Checkbutton(self.grid_frame, variable=en).grid(row=1, column=c)
            for r, (key, choices) in enumerate((("mos", simenv.MOS_SECTIONS), ("cap", simenv.CAP_SECTIONS),
                                                ("res", simenv.RES_SECTIONS)), start=2):
                v = tk.StringVar(value=getattr(corner, key))
                vars_[key] = v
                ttk.Combobox(self.grid_frame, textvariable=v, values=choices, width=9).grid(
                    row=r, column=c, padx=1, pady=1)
            t = tk.StringVar(value=f"{corner.temp:g}")
            vars_["temp"] = t
            ttk.Entry(self.grid_frame, textvariable=t, width=11).grid(row=5, column=c, padx=1, pady=1)
            for r, var in enumerate(self.setup.variables, start=6):
                v = tk.StringVar(value=corner.vars.get(var, ""))
                vars_[f"var:{var}"] = v
                ttk.Entry(self.grid_frame, textvariable=v, width=11).grid(row=r, column=c, padx=1, pady=1)
            self.cell_vars.append(vars_)
        self._select_corner(self.sel_corner if self.sel_corner is not None else None)

    def _select_corner(self, i: int | None) -> None:
        self.sel_corner = i if i is not None and i < len(self.setup.corners) else None

    def _read_corners(self) -> None:
        """Grid widgets -> setup.corners."""
        corners = []
        for vars_ in getattr(self, "cell_vars", []):
            overrides = {k[4:]: v.get().strip() for k, v in vars_.items()
                         if k.startswith("var:") and v.get().strip()}
            corners.append(simenv.Corner(vars_["name"].get().strip() or "corner", bool(vars_["enabled"].get()),
                                      vars_["mos"].get(), vars_["cap"].get(), vars_["res"].get(),
                                      _num(vars_["temp"].get()) if _num(vars_["temp"].get()) is not None else 27.0,
                                      overrides))
        self.setup.corners = corners

    def _sel_index(self, tree: ttk.Treeview) -> int | None:
        sel = tree.selection()
        return int(sel[0]) if sel and sel[0].isdigit() else None

    def _move(self, items: list, tree: ttk.Treeview, step: int, refill) -> None:
        i = self._sel_index(tree)
        if i is None or not 0 <= i + step < len(items):
            return
        items[i], items[i + step] = items[i + step], items[i]
        refill()
        tree.selection_set(str(i + step))

    # --- variables ----------------------------------------------------------------------

    def var_add(self) -> None:
        d = RowDialog(self, "Design variable", [("name", "Name", "text", None),
                                                 ("value", "Value", "text", None)], {})
        if d.result and d.result["name"].strip():
            self._read_corners()
            self.setup.variables[d.result["name"].strip()] = d.result["value"].strip()
            self._fill_vars()
            self._fill_corners()

    def var_edit(self) -> None:
        sel = self.var_tree.selection()
        if not sel:
            return
        k = sel[0]
        d = RowDialog(self, f"Design variable {k}", [("value", "Value", "text", None)],
                      {"value": self.setup.variables[k]})
        if d.result:
            self.setup.variables[k] = d.result["value"].strip()
            self._fill_vars()

    def var_del(self) -> None:
        sel = self.var_tree.selection()
        if sel:
            self._read_corners()
            self.setup.variables.pop(sel[0], None)
            self._fill_vars()
            self._fill_corners()

    def var_scan(self) -> None:
        sch = self.ws.view_path(self.lib, self.cell, "schematic")
        found = simenv.scan_variables(sch.read_text(errors="replace")) if sch.is_file() else {}
        for k, v in found.items():
            self.setup.variables.setdefault(k, v)
        self._fill_vars()
        self._say(f"{len(found)} variables found in the schematic: {', '.join(found) or 'none'}")

    # --- outputs ------------------------------------------------------------------------

    OUT_SPEC = [("name", "Name", "text", None),
                ("expr", "Expression (empty: printed by the testbench)", "text", None),
                ("label", "Label", "text", None),
                ("min", "Lower limit (spec)", "text", None), ("max", "Upper limit (spec)", "text", None),
                ("scale", "Scale (shown = value × scale)", "text", None), ("unit", "Unit", "text", None)]

    def _out_from(self, r: dict) -> simenv.Output:
        return simenv.Output(r["name"].strip().lower(), r["label"].strip(), _num(r["min"]), _num(r["max"]),
                          _num(r["scale"]) or 1.0, r["unit"].strip(), r["expr"].strip())

    def out_add(self) -> None:
        d = RowDialog(self, "Output", self.OUT_SPEC, {"scale": 1})
        if d.result and d.result["name"].strip():
            self.setup.outputs.append(self._out_from(d.result))
            self._fill_outputs()

    def out_edit(self) -> None:
        i = self._sel_index(self.out_tree)
        if i is None:
            return
        o = self.setup.outputs[i]
        d = RowDialog(self, f"Output {o.name}", self.OUT_SPEC,
                      {f.name: getattr(o, f.name) for f in fields(o)})
        if d.result:
            self.setup.outputs[i] = self._out_from(d.result)
            self._fill_outputs()

    def out_del(self) -> None:
        i = self._sel_index(self.out_tree)
        if i is not None:
            del self.setup.outputs[i]
            self._fill_outputs()

    def out_from_last(self) -> None:
        if not self.last or not self.last.results:
            messagebox.showinfo("FOSSLab", "Run the testbench once (Run nominal) first.", parent=self)
            return
        have = {o.name for o in self.setup.outputs}
        names = sorted({k for r in self.last.results for k in r.values} - have)
        for n in names:
            self.setup.outputs.append(simenv.Output(n))
        self._fill_outputs()
        self._say(f"added {len(names)} outputs: {', '.join(names)}")

    # --- corners ------------------------------------------------------------------------

    def cor_add(self) -> None:
        self._read_corners()
        self.setup.corners.append(simenv.Corner(f"corner{len(self.setup.corners) + 1}"))
        self._fill_corners()

    def cor_dup(self) -> None:
        self._read_corners()
        i = self.sel_corner if self.sel_corner is not None else len(self.setup.corners) - 1
        if i < 0:
            return
        c = self.setup.corners[i]
        self.setup.corners.insert(i + 1, simenv.Corner(c.name + "_copy", c.enabled, c.mos, c.cap, c.res,
                                                    c.temp, dict(c.vars)))
        self._fill_corners()

    def cor_del(self) -> None:
        self._read_corners()
        if self.sel_corner is None:
            messagebox.showinfo("FOSSLab", "Click the name of the corner to delete first.", parent=self)
            return
        del self.setup.corners[self.sel_corner]
        self.sel_corner = None
        self._fill_corners()

    def cor_standard(self) -> None:
        d = RowDialog(self, "Standard corner set", [
            ("temps", "Temperatures (°C)", "text", None),
            ("var", "Supply variable", "text", None),
            ("values", "Supply values", "text", None)],
            {"temps": "-40 27 125", "var": "vdd", "values": "1.08 1.2 1.32"})
        if not d.result:
            return
        temps = [float(t) for t in d.result["temps"].split()]
        var = d.result["var"].strip()
        vals = d.result["values"].split() or [""]
        rows = []
        for m in simenv.MOS_SECTIONS:
            for t in temps:
                for v in vals:
                    name = f"{m[4:]}_{t:g}C" + (f"_{v}V" if var and v else "")
                    cap = {"mos_ff": "cap_bcs", "mos_ss": "cap_wcs"}.get(m, "cap_typ")
                    rows.append(simenv.Corner(name, True, m, cap, "res_typ", t, {var: v} if var and v else {}))
        if messagebox.askyesno("FOSSLab", f"Replace the corner table with {len(rows)} corners?", parent=self):
            if var and var not in self.setup.variables:
                self.setup.variables[var] = vals[len(vals) // 2]
                self._fill_vars()
            self.setup.corners = rows
            self._fill_corners()

    # --- running ------------------------------------------------------------------------

    def _read_mc(self) -> bool:
        self._read_corners()
        self.setup.wave = self.wave_var.get().strip()
        self.setup.wave_logx = bool(self.wave_log.get())
        try:
            self.setup.montecarlo = simenv.MonteCarlo(int(self.mc_runs.get()), self.mc_var.get(),
                                                   int(self.mc_seed.get()), int(self.mc_jobs.get()))
            return True
        except ValueError:
            messagebox.showerror("FOSSLab", "Monte Carlo: runs, seed and jobs must be integers.", parent=self)
            return False

    def save(self, quiet: bool = False) -> None:
        if not self._read_mc():
            return
        if self.ws.readonly:
            if not quiet:
                messagebox.showinfo("FOSSLab", "Read-only workspace: the setup is used but not saved.",
                                    parent=self)
            return
        p = self.setup.save(self.ws, self.lib, self.cell)
        self._say(f"setup saved: {p}")

    def run(self, kind: str) -> None:
        if self.busy:
            return
        if not self._read_mc():
            return
        self.save(quiet=True)
        self.busy = True
        self.progress.configure(value=0, maximum=1)
        self._say(f"--- {kind} ---")
        setup = self.setup

        def work():
            echo = lambda s: self.q.put(("log", s))  # noqa: E731
            prog = lambda a, b: self.q.put(("prog", (a, b)))  # noqa: E731
            try:
                if kind == "corners":
                    rs = simenv.run_corners(self.ws, self.lib, self.cell, setup, echo, prog)
                elif kind == "montecarlo":
                    rs = simenv.run_montecarlo(self.ws, self.lib, self.cell, setup, echo, prog)
                else:
                    rs = simenv.run_nominal(self.ws, self.lib, self.cell, setup, echo)
                self.q.put(("done", rs))
            except (flows.FlowError, OSError, ValueError) as e:
                self.q.put(("error", str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _poll(self) -> None:
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self._say(val)
                elif kind == "prog":
                    self.progress.configure(value=val[0], maximum=val[1])
                elif kind == "done":
                    self.busy = False
                    self.show_results(val)
                elif kind == "error":
                    self.busy = False
                    self._say("ERROR: " + val)
                    messagebox.showerror("FOSSLab", val, parent=self)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(150, self._poll)

    def _say(self, s: str) -> None:
        self.log.insert("end", s + "\n")
        self.log.see("end")

    # --- results ------------------------------------------------------------------------

    def show_results(self, rs: simenv.RunSet) -> None:
        self.last = rs
        self.nb.select(len(self.nb.tabs()) - 1)
        t = self.res_tree
        t.delete(*t.get_children())
        outs = rs.outputs or [simenv.Output(n) for n in sorted({k for r in rs.results for k in r.values})]
        failed = sum(1 for r in rs.results if not r.ok)
        if rs.kind == "montecarlo":
            y = rs.yield_()
            self.res_title.configure(text=(
                f"Monte Carlo ({rs.variation}), {len(rs.results)} runs"
                + (f", {failed} failed" if failed else "")
                + (f".  Yield (all specs met): {y * 100:.1f} %" if y is not None else "")))
            cols = ("output", "mean", "std", "min", "max", "spec", "pass")
            heads = ("Output", "Mean", "σ", "Min", "Max", "Spec", "Pass %")
            self._columns(cols, heads)
            for o in outs:
                st = rs.stats(o.name)
                if not st:
                    t.insert("", "end", iid=o.name, values=(o.label or o.name, "no data", "", "", "", "", ""))
                    continue
                xs = rs.column(o.name)
                npass = sum(1 for x in xs if o.passes(x))
                spec = self._spec(o)
                tag = () if spec == "" else (("pass",) if npass == len(xs) else ("fail",))
                t.insert("", "end", iid=o.name, tags=tag, values=(
                    self._label(o), simenv.fmt(o.show(st["mean"])), simenv.fmt(abs(o.show(st["std"]))),
                    simenv.fmt(o.show(st["min"])), simenv.fmt(o.show(st["max"])), spec,
                    f"{100 * npass / len(xs):.1f}" if spec else ""))
            if outs:
                t.selection_set(outs[0].name)
            if (Path(rs.run_dir) / "waves.png").is_file():
                t.insert("", "end", iid="__waves", values=("Waveforms: all runs (click)",))
            self._show_hist()
            return
        else:
            self.res_title.configure(text=f"{'Corners' if rs.kind == 'corners' else 'Nominal run'}: "
                                          f"{len(rs.results)} run(s)" + (f", {failed} failed" if failed else ""))
            cols = ("output", "spec", *[r.name for r in rs.results])
            heads = ("Output", "Spec", *[r.name for r in rs.results])
            self._columns(cols, heads)
            for o in outs:
                vals = [r.values.get(o.name) for r in rs.results]
                cells = []
                worst = True
                for v in vals:
                    p = o.passes(v)
                    worst = worst and (p is not False)
                    cells.append(simenv.fmt(o.show(v)) + (" ✘" if p is False else ""))
                spec = self._spec(o)
                t.insert("", "end", iid=o.name, values=(self._label(o), spec, *cells),
                         tags=(() if not spec else (("pass",) if worst else ("fail",))))
            if outs:
                t.selection_set(outs[0].name)
        if (Path(rs.run_dir) / "waves.png").is_file():
            t.insert("", "end", iid="__waves", values=("Waveforms: all runs (click)",))
        self._show_hist()

    def _columns(self, cols, heads) -> None:
        t = self.res_tree
        t.configure(columns=cols)
        for c, h in zip(cols, heads):
            t.heading(c, text=h)
            t.column(c, width=220 if c == "output" else 80, anchor="w" if c == "output" else "e",
                     stretch=c == "output")

    @staticmethod
    def _label(o: simenv.Output) -> str:
        return (o.label or o.name) + (f" ({o.unit})" if o.unit else "")

    @staticmethod
    def _spec(o: simenv.Output) -> str:
        if o.min is not None and o.max is not None:
            return f"{o.min:g} .. {o.max:g}"
        if o.min is not None:
            return f">= {o.min:g}"
        if o.max is not None:
            return f"<= {o.max:g}"
        return ""

    def _show_hist(self) -> None:
        """The picture of the selected output: histogram (Monte Carlo) or bars (corners)."""
        if not self.last or self.last.kind == "nominal":
            return
        sel = self.res_tree.selection()
        if not sel:
            return
        prefix = "hist" if self.last.kind == "montecarlo" else "bars"
        name = "waves" if sel[0] == "__waves" else f"{prefix}_{sel[0]}"
        png = Path(self.last.run_dir) / f"{name}.png"
        if png.is_file():
            img = tk.PhotoImage(file=str(png))
            self.images = [img]
            self.hist.configure(image=img)

    def open_csv(self) -> None:
        if self.last:
            tools.open_editor(Path(self.last.run_dir) / "results.csv")

    def open_folder(self) -> None:
        if self.last:
            tools.open_terminal(Path(self.last.run_dir))

    def open_schematic(self) -> None:
        tools.open_xschem(self.ws, self.ws.view_path(self.lib, self.cell, "schematic"))
