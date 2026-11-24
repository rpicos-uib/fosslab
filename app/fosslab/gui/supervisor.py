"""Roster: every student at a glance, with private notes per student.

Reads the students' workspaces through the group ACLs set at install
(read-only); writes only to the supervisor's own workspace
(<ws>/.fosslab/supervisor/notes/<user>.txt).
"""

from __future__ import annotations

import csv
import os
import queue
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from .. import config
from ..workspace import Workspace, fmt_time
from . import style


@dataclass
class StudentRow:
    user: str
    state: str
    libs: int = 0
    cells: int = 0
    last: float = 0.0
    sim: str = ""
    drc: str = ""
    lvs: str = ""
    pex: str = ""


def scan_student(user: str, home: Path) -> StudentRow:
    ws = Workspace(home / config.WS_NAME, readonly=True)
    if not ws.root.exists():
        return StudentRow(user, "no workspace")
    if not os.access(ws.root, os.R_OK | os.X_OK):
        return StudentRow(user, "no access")
    if not ws.lib_file.is_file():
        return StudentRow(user, "empty")
    row = StudentRow(user, "ok")
    counts = {f: [0, 0] for f in ("sim", "drc", "lvs", "pex")}   # [pass, total]
    try:
        libs = ws.own_libraries()
        row.libs = len(libs)
        for lib in libs:
            for cell in ws.cells(lib):
                row.cells += 1
                for flow, r in ws.status(lib.name, cell).results.items():
                    if flow in counts:
                        counts[flow][1] += 1
                        counts[flow][0] += r.get("status") == "pass"
        row.last = ws.last_modified()
    except OSError:
        row.state = "partial access"
    for f, (ok, total) in counts.items():
        setattr(row, f, f"{ok}/{total}" if total else "")
    return row


class RosterWindow(tk.Toplevel):
    COLS = (("state", "Workspace", 110), ("libs", "Libs", 50), ("cells", "Cells", 55),
            ("last", "Last change", 130), ("sim", "Sim ok", 65), ("drc", "DRC ok", 65),
            ("lvs", "LVS ok", 65), ("pex", "PEX ok", 65), ("note", "Notes", 260))

    def __init__(self, master, my_ws: Workspace, on_open: Callable[[str], None]):
        super().__init__(master)
        self.my_ws, self.on_open = my_ws, on_open
        self.notes_dir = my_ws.root / ".fosslab" / "supervisor" / "notes"
        self.rows: list[StudentRow] = []
        self.title("FOSSLab roster")
        self.geometry("1100x520")
        style.apply(self)

        bar = ttk.Frame(self, padding=8)
        bar.pack(fill="x")
        ttk.Label(bar, text=f"Students in group '{config.STUDENT_GROUP}'", style="Head.TLabel").pack(side="left")
        ttk.Button(bar, text="Export CSV...", command=self.export).pack(side="right")
        ttk.Button(bar, text="Refresh", command=self.refresh).pack(side="right", padx=6)

        frame = ttk.Frame(self, padding=(8, 0, 8, 0))
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, columns=[c for c, _, _ in self.COLS], selectmode="browse")
        self.tree.heading("#0", text="Student")
        self.tree.column("#0", width=120)
        for c, t, w in self.COLS:
            self.tree.heading(c, text=t, command=lambda c=c: self.sort(c))
            self.tree.column(c, width=w, anchor="w" if c in ("note", "state", "last") else "center")
        ys = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ys.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ys.pack(side="right", fill="y")
        self.tree.tag_configure("bad", foreground=style.FAIL)
        self.tree.tag_configure("idle", foreground=style.MUTED)
        self.tree.bind("<Double-1>", lambda e: self.open_selected())

        nb = ttk.Frame(self, padding=8)
        nb.pack(fill="x")
        ttk.Button(nb, text="Open workspace", style="Accent.TButton",
                   command=self.open_selected).pack(side="left")
        ttk.Label(nb, text="Notes on the selected student (only you see them):",
                  style="Muted.TLabel").pack(side="left", padx=12)
        ttk.Button(nb, text="Save notes", command=self.save_note).pack(side="right")
        self.note = tk.Text(self, height=5, wrap="word")
        self.note.pack(fill="x", padx=8, pady=(0, 8))
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.load_note())
        self.refresh()

    def _note_path(self, user: str) -> Path:
        return self.notes_dir / f"{user}.txt"

    def refresh(self) -> None:
        roster = config.roster()
        if not roster:
            messagebox.showinfo("FOSSLab", f"No students found in group '{config.STUDENT_GROUP}'.\n"
                                "Start the supervisor with the fosslab-supervisor command.", parent=self)
        self.tree.delete(*self.tree.get_children())
        self.tree.insert("", "end", iid="__loading", text="scanning...")

        # Tk may only be touched from its own thread: the scan reports
        # through a queue that _poll() reads.
        results: queue.Queue = queue.Queue()
        threading.Thread(target=lambda: results.put([scan_student(u, h) for u, h in roster]),
                         daemon=True).start()
        self._poll(results)

    def _poll(self, results: queue.Queue) -> None:
        try:
            rows = results.get_nowait()
        except queue.Empty:
            if self.winfo_exists():
                self.after(100, self._poll, results)
            return
        self._show(rows)

    def _show(self, rows: list[StudentRow]) -> None:
        self.rows = rows
        self.tree.delete(*self.tree.get_children())
        for r in rows:
            note = ""
            p = self._note_path(r.user)
            if p.is_file():
                note = p.read_text(errors="replace").strip().splitlines()[0:1]
                note = note[0] if note else ""
            tag = "bad" if r.state in ("no access", "partial access") else ("idle" if r.state != "ok" else "")
            self.tree.insert("", "end", iid=r.user, text=r.user, tags=(tag,) if tag else (),
                             values=(r.state, r.libs or "", r.cells or "", fmt_time(r.last),
                                     r.sim, r.drc, r.lvs, r.pex, note))

    def sort(self, col: str) -> None:
        items = [(self.tree.set(i, col), i) for i in self.tree.get_children()]
        items.sort(reverse=col in ("last", "cells", "libs"))
        for n, (_, i) in enumerate(items):
            self.tree.move(i, "", n)

    def selected(self) -> str | None:
        sel = self.tree.selection()
        return sel[0] if sel and sel[0] != "__loading" else None

    def open_selected(self) -> None:
        user = self.selected()
        if user:
            self.on_open(user)

    def load_note(self) -> None:
        self.note.delete("1.0", "end")
        user = self.selected()
        if user and self._note_path(user).is_file():
            self.note.insert("1.0", self._note_path(user).read_text(errors="replace"))

    def save_note(self) -> None:
        user = self.selected()
        if not user:
            return
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        self._note_path(user).write_text(self.note.get("1.0", "end").rstrip() + "\n")
        first = self.note.get("1.0", "2.0").strip()
        self.tree.set(user, "note", first)

    def export(self) -> None:
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".csv",
                                            initialfile="fosslab_roster.csv")
        if not path:
            return
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["user", "workspace", "libraries", "cells", "last_change",
                        "sim_ok", "drc_ok", "lvs_ok", "pex_ok"])
            for r in self.rows:
                w.writerow([r.user, r.state, r.libs, r.cells, fmt_time(r.last),
                            r.sim, r.drc, r.lvs, r.pex])
