"""Courses: who teaches, who studies, and how, one plain-text file per course.

    # FOSSLab course
    id       micro-2026
    title    Microelectronics 2026
    state    active                 # active | archived
    teacher  rodrigo
    access   rX                     # what teachers may do in the students' work: rX | rwX
    example  ro                     # the tutorial's op-amp: none | ro (shared) | rw (own copy)
    library  opamp_tut              # its library name
    tutorial https://memristors.uib.es/index.php/education/fosslab/
    student  bob    Bob Smith
    student  carol  Carol Jones

On the server (install/fosslab-course, run as root with sudo):

    $PREFIX/courses/<id>.course      the applied course (root:fl-<id>-t, 640)
    $PREFIX/courses/<id>.passwords   first passwords of new local accounts (same)
    $PREFIX/courses/index            id, state, access, title of every course (public)
    $PREFIX/shared/<id>/             the course's shared example library (ro)
    groups fl-<id> (students), fl-<id>-t (its teachers)
    ~student/fosslab-<id>/           the student's workspace for the course
                                     (course "default", migrated from the
                                     single-course setup: ~/fosslab)

Teachers edit drafts in ~/.config/fosslab/courses/<id>.course and apply
them with  sudo $PREFIX/bin/fosslab-course apply <draft>.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import config

ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,23}$")       # fl-<id>-t must fit in 32 characters
USER_RE = re.compile(r"^[a-z_][a-z0-9_.-]{0,31}$")
ACCESS = {"rX": "read only", "rwX": "read and write"}
EXAMPLE = {"none": "no example library", "ro": "one shared copy, read only",
           "rw": "a copy of their own, read-write"}
STATES = ("active", "archived")
LEGACY_ID = "default"
FORMAT = 1           # course file format (install/fosslab-course knows the same number)


@dataclass
class Course:
    id: str
    title: str = ""
    state: str = "active"
    teachers: list[str] = field(default_factory=list)
    access: str = "rX"
    example: str = "none"
    library: str = "opamp_tut"
    tutorial: str = ""
    students: list[tuple[str, str]] = field(default_factory=list)   # (user, full name)

    # --- names on the server ---------------------------------------------------------

    @property
    def student_group(self) -> str:
        return f"fl-{self.id}"

    @property
    def teacher_group(self) -> str:
        return f"fl-{self.id}-t"

    def workspace(self, home: Path) -> Path:
        return workspace_of(self.id, home)

    def users(self) -> list[str]:
        return [u for u, _ in self.students]

    # --- text ----------------------------------------------------------------------------

    @classmethod
    def parse(cls, text: str, name: str = "") -> "Course":
        c = cls(id="")
        for n, raw in enumerate(text.splitlines(), 1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            key, _, rest = line.partition(" ")
            key, rest = key.lower(), rest.strip()
            if key == "format":
                if not rest.isdigit() or int(rest) > FORMAT:
                    raise ValueError(f"{name or 'course'}: format {rest} is newer than this FOSSLab ({FORMAT})")
            elif key == "id":
                c.id = rest
            elif key == "title":
                c.title = rest
            elif key == "state":
                c.state = rest
            elif key == "teacher":
                c.teachers += rest.split()
            elif key == "access":
                c.access = rest
            elif key == "example":
                c.example = rest
            elif key == "library":
                c.library = rest
            elif key == "tutorial":
                c.tutorial = rest
            elif key == "student":
                user, _, full = rest.partition(" ")
                c.students.append((user, full.strip()))
            else:
                raise ValueError(f"{name or 'course'} line {n}: unknown keyword '{key}'")
        if not c.id and name:
            c.id = Path(name).stem
        return c

    def text(self) -> str:
        out = ["# FOSSLab course (Supervisor > Courses, or edit by hand; apply with",
               "#   sudo fosslab-course apply <this file>)",
               f"format   {FORMAT}",
               f"id       {self.id}",
               f"title    {self.title}",
               f"state    {self.state}"]
        out += [f"teacher  {t}" for t in self.teachers]
        out += [f"access   {self.access:<22s} # teachers in the students' work: rX read, rwX read+write",
                f"example  {self.example:<22s} # tutorial op-amp: none | ro (shared) | rw (own copy)",
                f"library  {self.library}"]
        if self.tutorial:
            out.append(f"tutorial {self.tutorial}")
        out += [f"student  {u:<14s} {n}".rstrip() for u, n in self.students]
        return "\n".join(out) + "\n"

    def problems(self) -> list[str]:
        p = []
        if not ID_RE.match(self.id or ""):
            p.append(f"course id '{self.id}': lowercase letters, digits, _ and -, starting with a letter, "
                     "at most 24 characters")
        if self.state not in STATES:
            p.append(f"state '{self.state}': use {' or '.join(STATES)}")
        if self.access not in ACCESS:
            p.append(f"access '{self.access}': use rX or rwX")
        if self.example not in EXAMPLE:
            p.append(f"example '{self.example}': use none, ro or rw")
        if self.example != "none" and not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", self.library or ""):
            p.append(f"library name '{self.library}'")
        if not self.teachers:
            p.append("a course needs at least one teacher")
        for u in self.teachers + self.users():
            if not USER_RE.match(u):
                p.append(f"'{u}' is not a valid user name")
        dup = {u for u in self.users() if self.users().count(u) > 1}
        if dup:
            p.append(f"listed twice: {', '.join(sorted(dup))}")
        return p


def workspace_of(course_id: str, home: Path) -> Path:
    if course_id == LEGACY_ID:
        return home / config.WS_NAME
    return home / f"{config.WS_NAME}-{course_id}"


# --- where courses live ----------------------------------------------------------------

def applied_dir() -> Path:
    return config.PREFIX / "courses"


def draft_dir() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "fosslab" / "courses"


def draft_path(course_id: str) -> Path:
    return draft_dir() / f"{course_id}.course"


def load(path: Path) -> Course:
    return Course.parse(Path(path).read_text(errors="replace"), Path(path).name)


def applied(course_id: str) -> Course | None:
    p = applied_dir() / f"{course_id}.course"
    try:
        return load(p)
    except (OSError, ValueError):
        return None


def save_draft(c: Course) -> Path:
    p = draft_path(c.id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(c.text())
    os.chmod(p, 0o600)            # student names: private
    return p


@dataclass
class Entry:
    id: str
    title: str
    status: str            # applied | changes pending | draft (not applied) | archived
    course: Course


def my_courses() -> list[Entry]:
    """The courses this teacher can see: applied ones (readable only by their
    teachers) and own drafts."""

    out: dict[str, Entry] = {}
    d = applied_dir()
    for p in sorted(d.glob("*.course")) if d.is_dir() else []:
        try:
            c = load(p)
        except (OSError, ValueError):
            continue                # not one of my courses
        out[c.id] = Entry(c.id, c.title, "archived" if c.state == "archived" else "applied", c)
    dd = draft_dir()
    for p in sorted(dd.glob("*.course")) if dd.is_dir() else []:
        try:
            c = load(p)
        except (OSError, ValueError):
            continue
        if c.id in out:
            if c.text() != out[c.id].course.text():
                out[c.id] = Entry(c.id, c.title, "changes pending", c)
        else:
            out[c.id] = Entry(c.id, c.title, "draft (not applied)", c)
    return sorted(out.values(), key=lambda e: (e.status == "archived", e.id))


def public_index() -> list[dict]:
    """$PREFIX/courses/index: what anybody may know of each course."""

    out = []
    try:
        lines = (applied_dir() / "index").read_text().splitlines()
    except OSError:
        return out
    for ln in lines:
        parts = ln.split(None, 3)
        if len(parts) >= 3 and not ln.startswith("#"):
            out.append({"id": parts[0], "state": parts[1], "access": parts[2],
                        "title": parts[3] if len(parts) > 3 else parts[0]})
    return out


def passwords(course_id: str) -> dict[str, str]:
    """First passwords of the accounts the course created (teachers only)."""

    out = {}
    try:
        for ln in (applied_dir() / f"{course_id}.passwords").read_text().splitlines():
            parts = ln.split()
            if len(parts) >= 2:
                out[parts[0]] = parts[1]
    except OSError:
        pass
    return out


def changes(old: Course | None, new: Course) -> list[str]:
    """What applying ``new`` would do, in words."""

    if old is None:
        return [f"new course {new.id}: groups {new.student_group} and {new.teacher_group}",
                f"teachers: {', '.join(new.teachers)}",
                f"{len(new.students)} students (accounts that do not exist yet are created)",
                f"teachers' access: {ACCESS.get(new.access, new.access)}",
                f"example library: {EXAMPLE.get(new.example, new.example)}"]
    out = []
    for attr, label in (("title", "title"), ("state", "state"), ("access", "teachers' access"),
                        ("example", "example library"), ("library", "library name"),
                        ("tutorial", "tutorial")):
        a, b = getattr(old, attr), getattr(new, attr)
        if a != b:
            out.append(f"{label}: {a or '-'} -> {b or '-'}")
    for who, a, b in (("teacher", old.teachers, new.teachers), ("student", old.users(), new.users())):
        add = [u for u in b if u not in a]
        rem = [u for u in a if u not in b]
        if add:
            out.append(f"add {who}s: {', '.join(add)}")
        if rem:
            out.append(f"remove {who}s: {', '.join(rem)} (their accounts and work are kept)")
    names_old, names_new = dict(old.students), dict(new.students)
    renamed = [u for u in names_new if u in names_old and names_old[u] != names_new[u]]
    if renamed:
        out.append(f"names changed: {', '.join(renamed)}")
    return out or ["no change"]


def read_students_csv(text: str) -> list[tuple[str, str]]:
    """user[,Full Name[,...]] per line (also ; or tab separated); # comments."""

    out = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("﻿")
        if not line or line.startswith("#"):
            continue
        parts = [x.strip() for x in re.split(r"[,;\t]", line)]
        user = parts[0].lower()
        if user in ("user", "username", "login", "usuario"):
            continue                 # a header row
        out.append((user, parts[1] if len(parts) > 1 else ""))
    return out
