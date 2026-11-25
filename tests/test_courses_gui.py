"""Courses in the GUI, with fake courses (no root, no real accounts):
supervisor course and student selectors, the new-course wizard, editing a
course's students, the Apply dialog, and a student's choice of course.

    DISPLAY=:N python3 tests/test_courses_gui.py TMPDIR SHOTDIR
(run by tests/run_all.sh inside the image)
"""
import os, sys, time, struct, subprocess, tkinter as tk
from pathlib import Path
T = Path(sys.argv[1]); OUT = Path(sys.argv[2]); OUT.mkdir(parents=True, exist_ok=True)
P = T / "prefix"; (P / "courses").mkdir(parents=True, exist_ok=True)
H = T / "homes"
os.environ["FOSSLAB_PREFIX"] = str(P)
os.environ["XDG_CONFIG_HOME"] = str(T / "xdg")
(P / "courses" / "micro-2026.course").write_text(
    "format 1\nid micro-2026\ntitle Microelectronics 2026\nstate active\nteacher rodrigo\naccess rX\n"
    "example ro\nlibrary opamp_tut\nstudent bob Bob New\nstudent ann Ann Old\n")
(P / "courses" / "micro-2026.passwords").write_text("bob Xk3pQ9wR2m\n")
(P / "courses" / "index").write_text("# id state access title\nmicro-2026 active rX Microelectronics 2026\n"
                                      "default active rX FOSSLab course\n")
for u in ("bob", "ann"):
    ws = H / u / "fosslab-micro-2026"; (ws / "libs" / "work").mkdir(parents=True, exist_ok=True)
    (ws / "fosslab.lib").write_text("DEFINE work libs/work\n")
os.environ["FOSSLAB_ROSTER"] = f"micro-2026/bob:{H/'bob'};micro-2026/ann:{H/'ann'};default/ann:{H/'ann'}"
from fosslab import config, course as cr
from fosslab.gui import style
from fosslab.gui.app import MainWindow
from fosslab.gui.courses import CourseWindow, ApplyDialog
from fosslab.workspace import Workspace
from tkinter import messagebox as _mb
SAID = []
for _n in ("showinfo", "showerror", "showwarning"):
    setattr(_mb, _n, lambda *a, **k: SAID.append(a))
_mb.askyesno = lambda *a, **k: True
fails = 0
def check(what, cond):
    global fails
    print(("PASS " if cond else "FAIL ") + what); fails += not cond
def screen():
    raw = subprocess.run("xwd -root -silent", shell=True, capture_output=True).stdout
    h = struct.unpack(">25I", raw[:100]); off = h[0] + h[19] * 12
    from PIL import Image
    return Image.frombuffer("RGB", (h[4], h[5]), raw[off:off + h[12] * h[5]], "raw", "BGRX", h[12], 1)
def pump(t=0.8):
    end = time.time() + t
    while time.time() < end: root.update(); time.sleep(0.02)
def grab(w, name):
    w.lift(); pump()
    x, y = w.winfo_rootx(), w.winfo_rooty()
    screen().crop((x, y, x + w.winfo_width(), y + w.winfo_height())).save(OUT / f"{name}.png")

check("roster courses", config.roster_courses() == ["default", "micro-2026"])
check("roster of one course", [u for u, _ in config.roster("micro-2026")] == ["ann", "bob"])
check("student workspace path", config.student_workspace("micro-2026", H / "bob") == H / "bob" / "fosslab-micro-2026")
check("legacy course path", config.student_workspace("default", H / "ann") == H / "ann" / "fosslab")

me = Workspace(T / "me" / "fosslab"); me.init()
root = tk.Tk(); style.apply(root); root.geometry("1180x640+0+0")
win = MainWindow(root, me, supervisor=True)
pump()
check("course selector shows my courses", list(win.course_box.cget("values")) == ["default", "micro-2026"])
win.switch_course("micro-2026"); pump()
check("students of the course", list(win.student_box.cget("values"))[1:] == ["ann", "bob"])
win.switch_student("bob"); pump()
check("opens bob's course workspace", win.ws.root == H / "bob" / "fosslab-micro-2026" and win.ws.readonly)
grab(root, "supervisor")
win.switch_student("— my workspace —")

entries = cr.my_courses()
check("my_courses lists the applied course", [e.id for e in entries] == ["micro-2026"] and entries[0].status == "applied")

# wizard: a new course
c = cr.Course(id="", teachers=["rodrigo"], tutorial=config.TUTORIAL_URL)
w = CourseWindow(root, c, wizard=True); w.geometry("860x620+0+0")
w.id_var.set("analog-2027"); w.title_var.set("Analog design 2027")
grab(w, "wizard_1_course")
w._step(1); w._step(1)
w._import("user,name\ncarol,Carol Third\ndave;Dave Fourth\nBad User,x\n")
pump()
grab(w, "wizard_3_students")
check("CSV import (header and bad names skipped)", [u for u, _ in w._students()] == ["carol", "dave"])
w._step(1); w.example_var.set("rw"); w.access_var.set("rwX"); grab(w, "wizard_4_teaching")
w._step(1); pump(); grab(w, "wizard_5_review")
review = w.review.get("1.0", "end")
check("review lists the new course", "new course analog-2027" in review and "2 students" in review)
saved = w.save(quiet=True)
check("draft saved", cr.draft_path("analog-2027").is_file())
d = cr.load(cr.draft_path("analog-2027"))
check("draft round trip", d.example == "rw" and d.access == "rwX" and d.users() == ["carol", "dave"]
      and d.title == "Analog design 2027")
check("draft is private", oct(cr.draft_path("analog-2027").stat().st_mode & 0o777) == "0o600")
check("my_courses: draft not applied", any(e.id == "analog-2027" and e.status == "draft (not applied)"
                                           for e in cr.my_courses()))
w.destroy()

# editing the applied course: changes pending, passwords
a = cr.applied("micro-2026")
e = CourseWindow(root, a, page="Students"); e.geometry("860x620+0+0"); pump()
check("first password shown", e.st.set("bob", "password") == "Xk3pQ9wR2m")
e._fill_students([r for r in e._students() if r[0] != "ann"] + [("erin", "Erin Fifth")])
grab(e, "edit_students")
e.save(quiet=True); e.destroy()
check("changes pending", any(x.id == "micro-2026" and x.status == "changes pending" for x in cr.my_courses()))
ad = ApplyDialog(root, cr.load(cr.draft_path("micro-2026"))); ad.geometry("820x460+0+0")
txt = ad.text.get("1.0", "end")
check("apply lists added and removed students", "add students: erin" in txt and "remove students: ann" in txt)
grab(ad, "apply")
ad.check(); check("check: not applied yet", "Not applied" in ad.status.cget("text"))
ad.destroy(); root.destroy()

# a student with two courses
os.environ["FOSSLAB_COURSES"] = "micro-2026;default"
os.environ.pop("FOSSLAB_WORKSPACE_SET", None); os.environ.pop("FOSSLAB_FROM_TOOL", None)
check("student: first course by default", config.default_workspace() == Path.home() / "fosslab-micro-2026")
config.save_pref("course", "default")
check("student: remembered course", config.default_workspace() == Path.home() / "fosslab")
os.environ["FOSSLAB_WORKSPACE"] = "/x/y"; os.environ["FOSSLAB_WORKSPACE_SET"] = "1"
check("explicit workspace wins", config.default_workspace() == Path("/x/y"))
print("FAILURES:", fails)
sys.exit(1 if fails else 0)
