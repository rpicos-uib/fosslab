"""Tools > Retake tutorial screenshots: run the capture from the Library Manager."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .. import tools
from ..examples import capture
from . import style


class ShotsWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Retake tutorial screenshots")
        self.geometry("900x700")
        style.apply(self)
        self.q: queue.Queue = queue.Queue()
        self.running = False

        f = ttk.Frame(self, padding=10)
        f.pack(fill="x")
        ttk.Label(f, wraplength=860, style="Muted.TLabel", text=(
            "Builds the tutorial's op-amp from scratch in the folder below (never in your workspace), "
            "runs every flow (simulation, DRC, LVS, PEX, corners, Monte Carlo, Verilog-A model), takes "
            "every screenshot from the real programs, and compares the numbers with those the tutorial "
            "quotes. About 10 minutes.")).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        ttk.Label(f, text="Folder:").grid(row=1, column=0, sticky="w")
        self.out = tk.StringVar(value=str(capture.default_out()))
        ttk.Entry(f, textvariable=self.out, width=60).grid(row=1, column=1, sticky="ew", padx=6)
        self.live = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="On my display (shows my desktop; do not touch mouse and keyboard)",
                        variable=self.live).grid(row=2, column=1, sticky="w", pady=4)
        self.start_btn = ttk.Button(f, text="Start", style="Accent.TButton", command=self.start)
        self.start_btn.grid(row=1, column=2)
        f.columnconfigure(1, weight=1)

        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.progress.pack(fill="x", padx=10)
        self.log = tk.Text(self, height=12, font=style.MONO, wrap="none")
        self.log.pack(fill="both", expand=True, padx=10, pady=6)

        self.table = ttk.Treeview(self, columns=("here", "tutorial"), height=8)
        self.table.heading("#0", text="Number")
        self.table.heading("here", text="This machine")
        self.table.heading("tutorial", text="Tutorial")
        self.table.column("#0", width=260)
        self.table.tag_configure("diff", foreground=style.FAIL)
        self.table.pack(fill="x", padx=10)
        b = ttk.Frame(self, padding=10)
        b.pack(fill="x")
        ttk.Button(b, text="Open screenshots folder", command=self.open_folder).pack(side="left")
        ttk.Button(b, text="Close", command=self.destroy).pack(side="right")
        self.after(150, self._poll)

    def start(self) -> None:
        if self.running:
            return
        out = Path(self.out.get()).expanduser()
        if out.resolve() == (Path.home() / "fosslab").resolve():
            messagebox.showerror("FOSSLab", "Choose a folder other than your workspace.", parent=self)
            return
        self.running = True
        self.start_btn.state(["disabled"])
        self.progress.start(12)
        self.log.delete("1.0", "end")
        self.table.delete(*self.table.get_children())
        live = self.live.get()

        def work():
            rc = capture.run(out, live=live, echo=lambda s: self.q.put(("log", s)))
            self.q.put(("done", (rc, out)))

        threading.Thread(target=work, daemon=True).start()

    def _poll(self) -> None:
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self.log.insert("end", val + "\n")
                    self.log.see("end")
                else:
                    self._done(*val)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(150, self._poll)

    def _done(self, rc: int, out: Path) -> None:
        self.running = False
        self.progress.stop()
        self.start_btn.state(["!disabled"])
        if rc != 0:
            messagebox.showerror("FOSSLab", f"The capture failed (code {rc}): see the log.", parent=self)
            return
        for label, here, quoted in capture.compare(out):
            self.table.insert("", "end", text=label, values=(here, quoted),
                              tags=("diff",) if here != quoted else ())
        n = len(list((out / "screenshots").glob("*.png")))
        self.log.insert("end", f"\n{n} screenshots in {out / 'screenshots'}\n"
                               "Copy them to wordpress/fosslab-tutorial/content/img/ and rebuild the plugin.\n")
        self.log.see("end")

    def open_folder(self) -> None:
        d = Path(self.out.get()).expanduser() / "screenshots"
        tools.open_terminal(d if d.is_dir() else Path.home())
