"""A window that runs one flow (sim, DRC, LVS, PEX, Verilog-A), shows its log
live and, at the end, the result with buttons to look at it."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Callable

from .. import flows, tools
from ..workspace import Workspace
from . import style

TITLES = {"sim": "Simulation", "drc": "DRC", "lvs": "LVS", "pex": "Parasitic extraction",
          "va": "Verilog-A compile"}


class FlowWindow(tk.Toplevel):
    def __init__(self, master, ws: Workspace, flow: str, lib: str, cell: str,
                 on_done: Callable[[flows.FlowResult], None] | None = None, **kwargs):
        super().__init__(master)
        self.ws, self.flow, self.lib, self.cell = ws, flow, lib, cell
        self.kwargs = kwargs
        self.on_done = on_done
        self.q: queue.Queue = queue.Queue()
        self.result: flows.FlowResult | None = None
        self.title(f"{TITLES.get(flow, flow)}: {lib}/{cell}")
        self.geometry("900x560")
        style.apply(self)

        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        self.banner = ttk.Label(top, text=f"Running {TITLES.get(flow, flow)} on {lib}/{cell} ...",
                                style="Banner.TLabel")
        self.banner.pack(side="left", fill="x", expand=True)
        self.progress = ttk.Progressbar(top, mode="indeterminate", length=160)
        self.progress.pack(side="right")
        self.progress.start(12)

        body = ttk.Frame(self, padding=(8, 0, 8, 0))
        body.pack(fill="both", expand=True)
        self.text = tk.Text(body, wrap="none", height=20, font=style.MONO)
        ys = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        xs = ttk.Scrollbar(body, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        self.buttons = ttk.Frame(self, padding=8)
        self.buttons.pack(fill="x")
        ttk.Button(self.buttons, text="Close", command=self.destroy).pack(side="right")

        threading.Thread(target=self._work, daemon=True).start()
        self.after(100, self._poll)

    def _work(self) -> None:
        try:
            res = flows.FLOWS[self.flow](self.ws, self.lib, self.cell,
                                         echo=lambda line: self.q.put(("line", line)), **self.kwargs)
        except Exception as e:  # noqa: BLE001 - shown to the user
            res = flows.FlowResult(self.flow, "error", f"{type(e).__name__}: {e}", "")
        self.q.put(("done", res))

    def _poll(self) -> None:
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "line":
                    self.text.insert("end", val + "\n")
                    self.text.see("end")
                else:
                    self._finish(val)
                    return
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(100, self._poll)

    def _finish(self, res: flows.FlowResult) -> None:
        self.result = res
        self.progress.stop()
        self.progress.pack_forget()
        word = {"pass": "PASS", "fail": "FAIL"}.get(res.status, "ERROR")
        self.banner.configure(text=f"{word}: {res.summary}",
                              style={"pass": "Pass.TLabel", "fail": "Fail.TLabel"}.get(res.status,
                                                                                       "Error.TLabel"))
        erc = res.outputs.get("erc") if res.outputs else None
        if erc:
            self.text.insert("end", "\nxschem connectivity notes:\n  " + "\n  ".join(erc) + "\n")
            self.text.see("end")
        self._result_buttons(res)
        if self.on_done:
            self.on_done(res)

    def _button(self, text: str, cmd) -> None:
        ttk.Button(self.buttons, text=text, command=cmd).pack(side="left", padx=(0, 6))

    def _result_buttons(self, res: flows.FlowResult) -> None:
        ws, lib, cell = self.ws, self.lib, self.cell
        out = res.outputs or {}
        gds = ws.view_path(lib, cell, "layout")
        if self.flow == "drc" and out.get("reports") and gds.is_file():
            self._button("Show errors in KLayout",
                         lambda: tools.open_klayout(ws, gds, rdb=Path(out["reports"][0])))
        if self.flow == "lvs" and out.get("lvsdb") and gds.is_file():
            self._button("Open LVS report in KLayout",
                         lambda: tools.open_klayout(ws, gds, l2n=Path(out["lvsdb"][0])))
        if self.flow == "lvs" and Path(out.get("extracted", "/nonexistent")).is_file():
            self._button("Extracted netlist", lambda: tools.open_editor(Path(out["extracted"])))
        if self.flow == "pex" and out.get("netlist"):
            self._button("Extracted netlist", lambda: tools.open_editor(Path(out["netlist"])))
        if self.flow == "sim":
            sch = Path(res.inputs.get("schematic", "")) if res.inputs else None
            if sch and sch.is_file():
                self._button("Open in xschem (graphs)", lambda: tools.open_xschem(ws, sch))
            for raw in out.get("raw", [])[:2]:
                self._button(f"Waveforms: {Path(raw).name}", lambda r=raw: tools.open_waveforms(Path(r)))
        if res.log and Path(res.log).is_file():
            self._button("Full log", lambda: tools.open_editor(Path(res.log)))
        if res.run_dir:
            self._button("Terminal in run folder", lambda: tools.open_terminal(Path(res.run_dir)))
