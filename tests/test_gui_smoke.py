"""Smoke test of the Tk windows on a demo workspace (run on a private Xvfb).

    python3 tests/test_gui_smoke.py DEMO_WS SHOT_DIR
Builds the Library Manager, selects cells, opens the hierarchy browser,
runs a DRC in a flow window, switches the supervisor to a student, and
saves screenshots (xwd) of each step.
"""
import os
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path

from fosslab.gui.app import MainWindow
from fosslab.gui.flow_window import FlowWindow
from fosslab.gui.hierarchy_window import HierarchyWindow
from fosslab.gui.supervisor import RosterWindow, scan_student
from fosslab.workspace import Workspace

demo = Path(sys.argv[1])
shots = Path(sys.argv[2])
shots.mkdir(parents=True, exist_ok=True)

# A fake student "alice" whose workspace is the demo one.
alice_home = shots / "alice_home"
alice_home.mkdir(exist_ok=True)
link = alice_home / "fosslab"
if not link.exists():
    link.symlink_to(demo)
os.environ["FOSSLAB_ROSTER"] = f"alice:{alice_home};bob:{shots / 'bob_home'}"

failures = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name, flush=True)
    if not cond:
        failures.append(name)


def pump(root, seconds=0.5):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)


def shot(root, name):
    pump(root, 0.5)
    subprocess.run(f"xwd -root -silent > {shots / name}.xwd", shell=True)


teacher = Workspace(shots / "teacher_ws")
teacher.init()
root = tk.Tk()
win = MainWindow(root, Workspace(demo), supervisor=True)
pump(root)
libs = {win.libs[i].name for i in win.libs}
check("libraries listed (work + PDK)", {"work", "sg13g2_pr", "sg13g2_stdcell"} <= libs)
win.reveal("work", "inv")
pump(root)
check("reveal selects work/inv", win.current_cell() == "inv")
row = win.cell_tree.item(win.cell_tree.selection()[0], "values")
check("cell row shows views and DRC/LVS/PEX pass", list(row) == ["●", "●", "●", "", "", "✔", "✔", "✔"])
# two Verilog-A views: the VA column counts them
d = win.ws.cell_dir("work", "inv")
for stem in ("inv", "inv_fast"):
    (d / f"{stem}.va").write_text(f"module {stem}(a, y); inout a, y; electrical a, y; endmodule\n")
win.refresh_cells()
pump(root)
row = win.cell_tree.item(win.cell_tree.selection()[0], "values")
check("VA column shows 2 Verilog-A views", row[3] == "2")
# sorting by a heading: ascending, again descending, empty cells last
names = lambda: [win.cell_tree.item(i, "text") for i in win.cell_tree.get_children()]  # noqa: E731
win.cell_sorter.click("#0")
up = names()
win.cell_sorter.click("#0")
check("click a heading: sorted ascending, again descending", up == sorted(up, key=str.lower) and names() == up[::-1])
check("the sorted column shows an arrow", win.cell_tree.heading("#0", "text").endswith("▼"))
win.cell_sorter.click("va")
check("sort by VA: the cell with Verilog-A views first, empty last", names()[0] == "inv")
win.refresh_cells()
check("the order survives a refresh", names()[0] == "inv")
for stem in ("inv", "inv_fast"):
    (d / f"{stem}.va").unlink()
win.refresh_cells()
views = [win.view_rows[i].kind for i in win.view_rows]
check("views include derived netlists", "layout" in views and "pex" in views and "extracted" in views)
shot(root, "1_main")

h = HierarchyWindow(root, win.ws, win.ws.view_path("work", "tb_inv", "schematic"), reveal=win.reveal)
pump(root)
top = h.tree.get_children()
kids = h.tree.get_children(h.tree.get_children(top[0])[0]) if top else ()
check("hierarchy tb_inv > x1 > M1, M2", len(kids) == 2)
shot(root, "2_hierarchy")
h.destroy()

fw = FlowWindow(root, win.ws, "drc", "work", "inv")
t0 = time.time()
while fw.result is None and time.time() - t0 < 120:
    pump(root, 0.2)
check("DRC flow window finished with PASS", fw.result is not None and fw.result.ok)
shot(root, "3_flow_drc")
fw.destroy()

# Supervisor: roster and switching to a student (read only).
check("scan_student alice ok", scan_student("alice", alice_home).state == "ok")
check("scan_student bob has no workspace", scan_student("bob", shots / "bob_home").state == "no workspace")
win.home_ws = teacher
rw = RosterWindow(root, teacher, on_open=win.switch_student)
pump(root, 2)
check("roster lists alice and bob", set(rw.tree.get_children()) == {"alice", "bob"})
shot(root, "4_roster")
rw.destroy()
win.switch_student("alice")
pump(root)
check("switched to alice, read only", win.student == "alice" and win.ws.readonly)
check("student flows write to the supervisor's area",
      str(win.ws.run_root).startswith(str(teacher.root)))
win.reveal("work", "inv")
shot(root, "5_student_readonly")
win.quit()
print("FAILURES:", failures if failures else "none")
sys.exit(1 if failures else 0)
