"""Supervisor > Courses: create, edit, load and save courses, their students,
and the system configuration.

The supervisor runs without root, so it never changes the server itself: a
course is saved as a draft (~/.config/fosslab/courses/<id>.course) and the
Apply dialog gives the one sudo command that makes the server match it
(install/fosslab-course). The same for the system configuration.
"""

from __future__ import annotations

import base64
import os
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Callable

from .. import config, course as cr, tools
from . import style

PAGES = ("Course", "Teachers", "Students", "Teaching", "Review")


def course_command() -> str:
    return str(config.PREFIX / "bin" / "fosslab-course")


class CommandBox(ttk.Frame):
    """A command to copy into a terminal on the server."""

    def __init__(self, master, command: str = ""):
        super().__init__(master)
        self.var = tk.StringVar(value=command)
        e = ttk.Entry(self, textvariable=self.var, font=style.MONO, state="readonly")
        e.pack(side="left", fill="x", expand=True)
        ttk.Button(self, text="Copy", command=self.copy).pack(side="left", padx=(6, 0))

    def set(self, command: str) -> None:
        self.var.set(command)

    def copy(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.var.get())


# --- the course editor / wizard -------------------------------------------------------

class CourseWindow(tk.Toplevel):
    """Edit a course in five pages. As a wizard (a new course) the pages come
    one after the other with Back / Next; otherwise as tabs."""

    def __init__(self, master, c: cr.Course, wizard: bool = False, page: str = "Course",
                 on_saved: Callable[[cr.Course], None] | None = None):
        super().__init__(master)
        self.c = c
        self.wizard = wizard
        self.new = cr.applied(c.id) is None if c.id else True
        self.on_saved = on_saved
        self.title("New course" if wizard else f"Course {c.id}")
        self.geometry("860x620")
        style.apply(self)

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=10, pady=(10, 0))
        self.pages = {}
        for name in PAGES:
            f = ttk.Frame(self.nb, padding=12)
            self.nb.add(f, text=name)
            self.pages[name] = f
        self._page_course()
        self._page_teachers()
        self._page_students()
        self._page_teaching()
        self._page_review()
        self.nb.bind("<<NotebookTabChanged>>", lambda e: self._on_tab())

        bar = ttk.Frame(self, padding=10)
        bar.pack(fill="x")
        if wizard:
            self.back_btn = ttk.Button(bar, text="< Back", command=lambda: self._step(-1))
            self.back_btn.pack(side="left")
            self.next_btn = ttk.Button(bar, text="Next >", style="Accent.TButton", command=lambda: self._step(1))
            self.next_btn.pack(side="right")
        else:
            ttk.Button(bar, text="Save draft and apply...", style="Accent.TButton",
                       command=self.save_and_apply).pack(side="right")
            ttk.Button(bar, text="Save draft", command=self.save).pack(side="right", padx=6)
        ttk.Button(bar, text="Close", command=self.destroy).pack(side="right", padx=6)
        self._fill()
        self.nb.select(PAGES.index(page))
        if wizard:
            self._step(0)

    # --- pages --------------------------------------------------------------------------

    def _intro(self, page: str, text: str) -> None:
        ttk.Label(self.pages[page], text=text, style="Muted.TLabel", wraplength=800).pack(anchor="w", pady=(0, 10))

    def _page_course(self) -> None:
        f = self.pages["Course"]
        self._intro("Course", "A course groups its teachers and students. Each student works in a folder of "
                    "their own for the course (~/fosslab-<id>), which only the course's teachers can see. "
                    "Several courses can run at the same time; a student can be in several.")
        g = ttk.Frame(f)
        g.pack(anchor="w")
        self.id_var, self.title_var, self.state_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        ttk.Label(g, text="Course id").grid(row=0, column=0, sticky="w", pady=4, padx=(0, 10))
        self.id_entry = ttk.Entry(g, textvariable=self.id_var, width=26)
        self.id_entry.grid(row=0, column=1, sticky="w")
        ttk.Label(g, text="e.g. micro-2026: lowercase letters, digits, - and _ (it names the groups and "
                  "folders: cannot change later)", style="Muted.TLabel").grid(row=0, column=2, sticky="w", padx=8)
        ttk.Label(g, text="Title").grid(row=1, column=0, sticky="w", pady=4, padx=(0, 10))
        ttk.Entry(g, textvariable=self.title_var, width=50).grid(row=1, column=1, columnspan=2, sticky="w")
        ttk.Label(g, text="State").grid(row=2, column=0, sticky="w", pady=4, padx=(0, 10))
        ttk.Combobox(g, textvariable=self.state_var, values=cr.STATES, width=12, state="readonly").grid(
            row=2, column=1, sticky="w")
        ttk.Label(g, text="archived: kept, hidden from the students' course list", style="Muted.TLabel").grid(
            row=2, column=2, sticky="w", padx=8)

    def _page_teachers(self) -> None:
        f = self.pages["Teachers"]
        self._intro("Teachers", "User names of the teachers. Only they see this course, its students' "
                    "work and their first passwords, and only they can change it.")
        self.teachers = tk.Listbox(f, height=8, width=30)
        self.teachers.pack(anchor="w")
        b = ttk.Frame(f)
        b.pack(anchor="w", pady=6)
        ttk.Button(b, text="Add...", command=self.add_teacher).pack(side="left")
        ttk.Button(b, text="Remove", command=lambda: [self.teachers.delete(i) for i in
                                                      reversed(self.teachers.curselection())]).pack(side="left", padx=6)

    def _page_students(self) -> None:
        f = self.pages["Students"]
        self._intro("Students", "One row per student: the user name on the server and the full name. A user "
                    "name that does not exist yet becomes a new local account with a random first password "
                    "(shown here once the course is applied; it must be changed at the first login). "
                    "Existing accounts, local or from the university's directory, are only added to the course. "
                    "Removing a student keeps their account and work.")
        fr = ttk.Frame(f)
        fr.pack(fill="both", expand=True)
        self.st = ttk.Treeview(fr, columns=("name", "status", "password"), selectmode="extended")
        for c, t, w in (("#0", "User", 140), ("name", "Full name", 260), ("status", "On the server", 150),
                        ("password", "First password", 130)):
            self.st.heading(c, text=t)
            self.st.column(c, width=w, anchor="w")
        ys = ttk.Scrollbar(fr, orient="vertical", command=self.st.yview)
        self.st.configure(yscrollcommand=ys.set)
        self.st.pack(side="left", fill="both", expand=True)
        ys.pack(side="right", fill="y")
        self.st.bind("<Double-1>", lambda e: self.edit_student())
        b = ttk.Frame(f)
        b.pack(fill="x", pady=6)
        for text, cmd in (("Add...", self.add_student), ("Edit...", self.edit_student),
                          ("Remove", self.remove_students), ("Import CSV...", self.import_csv),
                          ("Paste a list...", self.paste_list)):
            ttk.Button(b, text=text, command=cmd).pack(side="left", padx=(0, 6))
        self.count = ttk.Label(b, style="Muted.TLabel")
        self.count.pack(side="right")

    def _page_teaching(self) -> None:
        f = self.pages["Teaching"]
        self._intro("Teaching", "How the course works.")
        self.access_var, self.example_var = tk.StringVar(), tk.StringVar()
        self.library_var, self.tutorial_var = tk.StringVar(), tk.StringVar()
        lf = ttk.LabelFrame(f, text="Teachers in the students' work", padding=8)
        lf.pack(fill="x", pady=(0, 10))
        for v, text in (("rX", "Read only: see and run their designs, never change them"),
                        ("rwX", "Read and write: you can also fix a student's file in place")):
            ttk.Radiobutton(lf, text=text, value=v, variable=self.access_var).pack(anchor="w", pady=2)
        lf = ttk.LabelFrame(f, text="The tutorial's op-amp as a library for the students", padding=8)
        lf.pack(fill="x", pady=(0, 10))
        for v, text in (("none", "No: the students build everything themselves"),
                        ("ro", "Yes, one shared copy, read only (they can copy cells from it to their own library)"),
                        ("rw", "Yes, a copy of their own in their workspace, which they can change")):
            ttk.Radiobutton(lf, text=text, value=v, variable=self.example_var).pack(anchor="w", pady=2)
        g = ttk.Frame(lf)
        g.pack(anchor="w", pady=(4, 0))
        ttk.Label(g, text="Library name").pack(side="left")
        ttk.Entry(g, textvariable=self.library_var, width=16).pack(side="left", padx=6)
        ttk.Label(g, text="(the exercise's solution is never included)", style="Muted.TLabel").pack(side="left")
        g = ttk.Frame(f)
        g.pack(fill="x")
        ttk.Label(g, text="Tutorial (Help > Tutorial)").pack(side="left")
        ttk.Entry(g, textvariable=self.tutorial_var, width=60).pack(side="left", padx=6)

    def _page_review(self) -> None:
        f = self.pages["Review"]
        self._intro("Review", "What applying this course will do on the server. Nothing changes until a "
                    "teacher with sudo runs the command of the Apply dialog.")
        self.review = tk.Text(f, height=16, wrap="word")
        self.review.pack(fill="both", expand=True)

    # --- filling and reading ------------------------------------------------------------

    def _fill(self) -> None:
        c = self.c
        self.id_var.set(c.id)
        if not self.new:
            self.id_entry.state(["disabled"])
        self.title_var.set(c.title)
        self.state_var.set(c.state)
        self.teachers.delete(0, "end")
        for t in c.teachers:
            self.teachers.insert("end", t)
        self._fill_students(c.students)
        self.access_var.set(c.access)
        self.example_var.set(c.example)
        self.library_var.set(c.library)
        self.tutorial_var.set(c.tutorial)

    def _fill_students(self, students: list[tuple[str, str]]) -> None:
        old = cr.applied(self.id_var.get().strip()) if self.id_var.get().strip() else None
        on_server = set(old.users()) if old else set()
        pw = cr.passwords(self.id_var.get().strip()) if old else {}
        self.st.delete(*self.st.get_children())
        for u, n in students:
            status = "in the course" if u in on_server else "added (apply to create)"
            self.st.insert("", "end", iid=u, text=u, values=(n, status, pw.get(u, "")))
        self.count.configure(text=f"{len(students)} students")

    def _students(self) -> list[tuple[str, str]]:
        return [(i, self.st.set(i, "name")) for i in self.st.get_children()]

    def read(self) -> cr.Course:
        return cr.Course(id=self.id_var.get().strip(), title=self.title_var.get().strip(),
                         state=self.state_var.get() or "active",
                         teachers=[self.teachers.get(i) for i in range(self.teachers.size())],
                         access=self.access_var.get(), example=self.example_var.get(),
                         library=self.library_var.get().strip() or "opamp_tut",
                         tutorial=self.tutorial_var.get().strip(), students=self._students())

    # --- actions ------------------------------------------------------------------------

    def add_teacher(self) -> None:
        u = simpledialog.askstring("Add teacher", "User name:", parent=self)
        if u and u.strip():
            self.teachers.insert("end", u.strip().lower())

    def _merge(self, rows: list[tuple[str, str]]) -> None:
        cur = dict(self._students())
        for u, n in rows:
            cur[u] = n or cur.get(u, "")
        self._fill_students(sorted(cur.items()))

    def add_student(self) -> None:
        d = StudentDialog(self, "", "")
        if d.result:
            self._merge([d.result])

    def edit_student(self) -> None:
        sel = self.st.selection()
        if not sel:
            return
        d = StudentDialog(self, sel[0], self.st.set(sel[0], "name"), user_fixed=True)
        if d.result:
            self._merge([d.result])

    def remove_students(self) -> None:
        sel = self.st.selection()
        if sel and messagebox.askyesno("Remove students", f"Remove {len(sel)} student(s) from the course?\n"
                                       "Their accounts and work are kept.", parent=self):
            keep = [r for r in self._students() if r[0] not in sel]
            self._fill_students(keep)

    def import_csv(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="Students (CSV)",
                                          filetypes=[("CSV or text", "*.csv *.txt"), ("All files", "*")])
        if path:
            self._import(Path(path).read_text(errors="replace"))

    def paste_list(self) -> None:
        d = PasteDialog(self)
        if d.result:
            self._import(d.result)

    def _import(self, text: str) -> None:
        rows = cr.read_students_csv(text)
        bad = [u for u, _ in rows if not cr.USER_RE.match(u)]
        good = [r for r in rows if r[0] not in bad]
        self._merge(good)
        msg = f"{len(good)} students read."
        if bad:
            msg += f"\nNot valid user names (skipped): {', '.join(bad[:10])}{' ...' if len(bad) > 10 else ''}"
        messagebox.showinfo("Students", msg, parent=self)

    def _on_tab(self) -> None:
        if self.nb.index("current") == PAGES.index("Review"):
            self._fill_review()

    def _fill_review(self) -> None:
        c = self.read()
        self.review.configure(state="normal")
        self.review.delete("1.0", "end")
        problems = c.problems()
        if problems:
            self.review.insert("end", "To fix first:\n" + "".join(f"  - {p}\n" for p in problems) + "\n")
        self.review.insert("end", "Applying it will:\n" + "".join(
            f"  - {x}\n" for x in cr.changes(cr.applied(c.id) if c.id else None, c)))
        self.review.insert("end", f"\nStudents' workspaces: ~/{config.WS_NAME}-{c.id or '<id>'}"
                           if c.id != cr.LEGACY_ID else f"\nStudents' workspaces: ~/{config.WS_NAME}")
        self.review.configure(state="disabled")

    def _step(self, d: int) -> None:
        i = self.nb.index("current") + d
        if d > 0 and self.nb.index("current") == PAGES.index("Course"):
            c = self.read()
            if not cr.ID_RE.match(c.id):
                messagebox.showerror("Course", c.problems()[0], parent=self)
                return
            if self.new and (cr.applied(c.id) or cr.draft_path(c.id).exists()):
                if not messagebox.askyesno("Course", f"A course or draft '{c.id}' exists. Replace the draft?",
                                           parent=self):
                    return
        if i >= len(PAGES):
            self.save_and_apply()
            return
        i = max(0, i)
        for n in range(len(PAGES)):
            self.nb.tab(n, state="normal" if n == i else "disabled")
        self.nb.select(i)
        self.back_btn.state(["disabled"] if i == 0 else ["!disabled"])
        self.next_btn.configure(text="Save and apply..." if i == len(PAGES) - 1 else "Next >")

    def save(self, quiet: bool = False) -> cr.Course | None:
        c = self.read()
        problems = c.problems()
        if problems:
            messagebox.showerror("Course", "Please fix:\n- " + "\n- ".join(problems), parent=self)
            return None
        p = cr.save_draft(c)
        self.c, self.new = c, False
        self.id_entry.state(["disabled"])
        if not quiet:
            messagebox.showinfo("Course", f"Draft saved: {p}\nApply it to change the server.", parent=self)
        if self.on_saved:
            self.on_saved(c)
        return c

    def save_and_apply(self) -> None:
        c = self.save(quiet=True)
        if c:
            if self.wizard:
                self.destroy()
            ApplyDialog(self.master, c)


class StudentDialog(tk.Toplevel):
    def __init__(self, master, user: str, name: str, user_fixed: bool = False):
        super().__init__(master)
        self.title("Student")
        self.transient(master)
        self.result = None
        f = ttk.Frame(self, padding=12)
        f.pack()
        self.u, self.n = tk.StringVar(value=user), tk.StringVar(value=name)
        ttk.Label(f, text="User name").grid(row=0, column=0, sticky="w", pady=4, padx=(0, 8))
        e = ttk.Entry(f, textvariable=self.u, width=20)
        e.grid(row=0, column=1, sticky="w")
        if user_fixed:
            e.state(["disabled"])
        ttk.Label(f, text="Full name").grid(row=1, column=0, sticky="w", pady=4, padx=(0, 8))
        ttk.Entry(f, textvariable=self.n, width=36).grid(row=1, column=1, sticky="w")
        b = ttk.Frame(self, padding=(12, 0, 12, 12))
        b.pack(fill="x")
        ttk.Button(b, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(b, text="OK", style="Accent.TButton", command=self._ok).pack(side="right", padx=6)
        self.bind("<Return>", lambda e: self._ok())
        self.grab_set()
        self.wait_window()

    def _ok(self) -> None:
        u = self.u.get().strip().lower()
        if not cr.USER_RE.match(u):
            messagebox.showerror("Student", f"'{u}' is not a valid user name.", parent=self)
            return
        self.result = (u, self.n.get().strip())
        self.destroy()


class PasteDialog(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Paste a list of students")
        self.transient(master)
        self.result = None
        ttk.Label(self, padding=10, style="Muted.TLabel", text=(
            "One student per line: user name, then (optional) the full name, separated by a comma, "
            "a semicolon or a tab, as copied from a spreadsheet.")).pack(anchor="w")
        self.text = tk.Text(self, width=70, height=16)
        self.text.pack(fill="both", expand=True, padx=10)
        b = ttk.Frame(self, padding=10)
        b.pack(fill="x")
        ttk.Button(b, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(b, text="Add", style="Accent.TButton", command=self._ok).pack(side="right", padx=6)
        self.grab_set()
        self.wait_window()

    def _ok(self) -> None:
        self.result = self.text.get("1.0", "end")
        self.destroy()


# --- applying ---------------------------------------------------------------------------

class ApplyDialog(tk.Toplevel):
    """What applying will change, the sudo command, and a check that it was done."""

    def __init__(self, master, c: cr.Course):
        super().__init__(master)
        self.c = c
        self.title(f"Apply course {c.id}")
        self.geometry("820x460")
        style.apply(self)
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=f"Course {c.id}: {c.title}", style="Banner.TLabel").pack(anchor="w")
        ttk.Label(f, style="Muted.TLabel", wraplength=780, text=(
            "FOSSLab does not run as root, so a teacher of the course with sudo rights applies it: "
            "copy the command into a terminal on the server (as yourself, not inside FOSSLab's terminal), "
            "then press Check.")).pack(anchor="w", pady=(4, 8))
        self.text = tk.Text(f, height=10, wrap="word")
        self.text.pack(fill="both", expand=True)
        for x in cr.changes(cr.applied(c.id), c):
            self.text.insert("end", f"- {x}\n")
        self.text.configure(state="disabled")
        ttk.Label(f, text="Command:", style="Head.TLabel").pack(anchor="w", pady=(10, 2))
        CommandBox(f, f"sudo {course_command()} apply {cr.draft_path(c.id)}").pack(fill="x")
        b = ttk.Frame(f)
        b.pack(fill="x", pady=(10, 0))
        self.status = ttk.Label(b, text="")
        self.status.pack(side="left")
        ttk.Button(b, text="Close", command=self.destroy).pack(side="right")
        ttk.Button(b, text="Check", style="Accent.TButton", command=self.check).pack(side="right", padx=6)

    def check(self) -> None:
        a = cr.applied(self.c.id)
        if a is not None and a.text() == self.c.text():
            self.status.configure(text="Applied. Restart the supervisor to see the new students.",
                                  style="Pass.TLabel")
        else:
            self.status.configure(text="Not applied yet." if a is None or a.text() != self.c.text() else "",
                                  style="Fail.TLabel")


class SystemConfigDialog(tk.Toplevel):
    """Courses > Edit system configuration: a draft of /etc/fosslab.conf in your home."""

    def __init__(self, master):
        super().__init__(master)
        self.title("System configuration")
        self.geometry("820x330")
        style.apply(self)
        self.draft = cr.draft_dir().parent / "fosslab.conf"
        current = _current_conf()
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="System configuration (/etc/fosslab.conf)", style="Banner.TLabel").pack(anchor="w")
        ttk.Label(f, style="Muted.TLabel", wraplength=780, text=(
            "Install location, tool image, the folders the tools see, the staff group... (the course "
            "settings are in each course). You edit a copy in your home; the command installs it, keeping "
            "the old file as /etc/fosslab.conf.<date>. Settings marked (install) also need their install "
            "step.")).pack(anchor="w", pady=(4, 10))
        if current is None:
            ttk.Label(f, text="The current configuration is not available here (FOSSLab was not started "
                      "with fosslab-supervisor).", style="Fail.TLabel").pack(anchor="w")
            return
        if not self.draft.exists() or messagebox.askyesno(
                "System configuration", f"There is a draft from before:\n{self.draft}\n\n"
                "Start again from the current configuration? (No: continue the draft)", parent=master):
            self.draft.parent.mkdir(parents=True, exist_ok=True)
            self.draft.write_text(current)
        ttk.Label(f, text=f"Draft: {self.draft}").pack(anchor="w")
        b = ttk.Frame(f)
        b.pack(anchor="w", pady=8)
        ttk.Button(b, text="Edit the draft", style="Accent.TButton",
                   command=lambda: tools.open_editor(self.draft)).pack(side="left")
        ttk.Button(b, text="Start again from the current one",
                   command=lambda: self.draft.write_text(current)).pack(side="left", padx=6)
        ttk.Label(f, text="When you have saved it, install it with:", style="Head.TLabel").pack(anchor="w", pady=(8, 2))
        CommandBox(f, f"sudo {course_command()} system-config {self.draft}").pack(fill="x")
        ttk.Button(f, text="Close", command=self.destroy).pack(anchor="e", pady=10)
        tools.open_editor(self.draft)


def _current_conf() -> str | None:
    t = os.environ.get("FOSSLAB_CONF_TEXT")
    if not t:
        return None
    try:
        return base64.b64decode(t).decode("utf-8", "replace")
    except ValueError:
        return None


# --- the Courses menu --------------------------------------------------------------------

class CoursesMenu:
    """The supervisor's Courses menu; ``win`` is the MainWindow."""

    def __init__(self, win, menubar: tk.Menu):
        self.win = win
        m = tk.Menu(menubar)
        menubar.add_cascade(label="Courses", menu=m)
        m.add_command(label="New course (wizard)...", command=self.new)
        m.add_command(label="Edit course...", command=lambda: self.edit())
        m.add_command(label="Students...", command=lambda: self.edit(page="Students"))
        m.add_command(label="Apply changes...", command=self.apply)
        m.add_separator()
        m.add_command(label="Duplicate as...", command=self.duplicate)
        m.add_command(label="Load from file...", command=self.load)
        m.add_command(label="Save to file...", command=self.save_file)
        m.add_command(label="Archive...", command=self.archive)
        m.add_separator()
        m.add_command(label="Edit system configuration...", command=lambda: SystemConfigDialog(win.root))

    def _pick(self, title: str) -> cr.Course | None:
        entries = cr.my_courses()
        if not entries:
            messagebox.showinfo("Courses", "You have no course yet: Courses > New course.", parent=self.win.root)
            return None
        cur = getattr(self.win, "course", "")
        d = PickCourseDialog(self.win.root, title, entries, cur)
        return d.result

    def new(self) -> None:
        me = os.environ.get("USER") or Path.home().name
        c = cr.Course(id="", title="", teachers=[me], tutorial=config.TUTORIAL_URL)
        CourseWindow(self.win.root, c, wizard=True)

    def edit(self, page: str = "Course") -> None:
        c = self._pick("Edit course")
        if c:
            CourseWindow(self.win.root, c, page=page)

    def apply(self) -> None:
        c = self._pick("Apply course")
        if c:
            ApplyDialog(self.win.root, c)

    def duplicate(self) -> None:
        c = self._pick("Duplicate course")
        if not c:
            return
        new_id = simpledialog.askstring("Duplicate", f"Id of the new course (from {c.id}):", parent=self.win.root)
        if not new_id:
            return
        keep = messagebox.askyesno("Duplicate", "Keep the students? (No: the same course for a new group, "
                                   "e.g. next year)", parent=self.win.root)
        n = replace(c, id=new_id.strip(), state="active", students=list(c.students) if keep else [],
                    title=c.title)
        CourseWindow(self.win.root, n, wizard=True)

    def load(self) -> None:
        path = filedialog.askopenfilename(parent=self.win.root, title="Load a course",
                                          filetypes=[("FOSSLab course", "*.course"), ("All files", "*")])
        if not path:
            return
        try:
            c = cr.load(Path(path))
        except (OSError, ValueError) as e:
            messagebox.showerror("Courses", str(e), parent=self.win.root)
            return
        CourseWindow(self.win.root, c, wizard=cr.applied(c.id) is None)

    def save_file(self) -> None:
        c = self._pick("Save course to a file")
        if not c:
            return
        path = filedialog.asksaveasfilename(parent=self.win.root, defaultextension=".course",
                                            initialfile=f"{c.id}.course")
        if path:
            Path(path).write_text(c.text())
            os.chmod(path, 0o600)

    def archive(self) -> None:
        c = self._pick("Archive course")
        if not c:
            return
        d = tk.Toplevel(self.win.root)
        d.title(f"Archive {c.id}")
        style.apply(d)
        f = ttk.Frame(d, padding=12)
        f.pack(fill="both", expand=True)
        ttk.Label(f, wraplength=640, text=(
            f"Archiving {c.id} hides it from its students' course list. Nothing is deleted: groups, "
            "accounts and work stay, and applying the course again reactivates it. In a terminal on the "
            "server:")).pack(anchor="w", pady=(0, 8))
        CommandBox(f, f"sudo {course_command()} archive {c.id}").pack(fill="x")
        ttk.Button(f, text="Close", command=d.destroy).pack(anchor="e", pady=(10, 0))


class PickCourseDialog(tk.Toplevel):
    def __init__(self, master, title: str, entries: list[cr.Entry], current: str = ""):
        super().__init__(master)
        self.title(title)
        self.transient(master)
        self.result: cr.Course | None = None
        self.entries = entries
        t = ttk.Treeview(self, columns=("title", "status", "students"), height=min(12, len(entries) + 1))
        for c, h, w in (("#0", "Course", 150), ("title", "Title", 280), ("status", "Status", 170),
                        ("students", "Students", 80)):
            t.heading(c, text=h)
            t.column(c, width=w)
        for e in entries:
            t.insert("", "end", iid=e.id, text=e.id, values=(e.title, e.status, len(e.course.students)))
        if current and current in [e.id for e in entries]:
            t.selection_set(current)
        elif entries:
            t.selection_set(entries[0].id)
        t.pack(fill="both", expand=True, padx=10, pady=10)
        t.bind("<Double-1>", lambda e: self._ok(t))
        b = ttk.Frame(self, padding=(10, 0, 10, 10))
        b.pack(fill="x")
        ttk.Button(b, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(b, text="OK", style="Accent.TButton", command=lambda: self._ok(t)).pack(side="right", padx=6)
        self.grab_set()
        self.wait_window()

    def _ok(self, t) -> None:
        sel = t.selection()
        if sel:
            self.result = next(e.course for e in self.entries if e.id == sel[0])
        self.destroy()
