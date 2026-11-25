"""Paths and settings, all from the environment set by runtime/container-env.sh."""

from __future__ import annotations

import os
from pathlib import Path

PREFIX = Path(os.environ.get("FOSSLAB_PREFIX", Path(__file__).resolve().parents[2]))
TOOLS = Path(os.environ.get("TOOLS", "/foss/tools"))
PDK_ROOT = Path(os.environ.get("PDK_ROOT", "/foss/pdks"))
PDK = os.environ.get("PDK", "ihp-sg13g2")
PDK_PATH = PDK_ROOT / PDK

INTEGRATIONS = Path(__file__).resolve().parent / "integrations"

TUTORIAL_URL = os.environ.get("FOSSLAB_TUTORIAL_URL") or "https://memristors.uib.es/index.php/education/fosslab/"
STUDENT_GROUP = os.environ.get("FOSSLAB_STUDENT_GROUP", "fosslab")
WS_NAME = os.environ.get("FOSSLAB_WS_NAME", "fosslab")

KLAYOUT_TECH = "sg13g2"


def prefs() -> dict:
    """Per-user preferences of the GUI (~/.config/fosslab/gui.json)."""

    import json
    try:
        return json.loads(_prefs_path().read_text())
    except (OSError, ValueError):
        return {}


def save_pref(key: str, value) -> None:
    import json
    d = prefs()
    d[key] = value
    try:
        _prefs_path().parent.mkdir(parents=True, exist_ok=True)
        _prefs_path().write_text(json.dumps(d, indent=1) + "\n")
    except OSError:
        pass


def _prefs_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "fosslab" / "gui.json"


def courses() -> list[str]:
    """The active courses the user studies (from their groups fl-<id>, set by the host wrapper)."""

    return [c for c in os.environ.get("FOSSLAB_COURSES", "").split(";") if c]


def current_course() -> str | None:
    cs = courses()
    if not cs:
        return None
    last = prefs().get("course")
    return last if last in cs else cs[0]


def default_workspace() -> Path:
    """A workspace given explicitly (-w, or by the program that started us)
    wins; then the student's current course; then ~/fosslab."""

    env = os.environ.get("FOSSLAB_WORKSPACE")
    explicit = os.environ.get("FOSSLAB_WORKSPACE_SET") == "1" or os.environ.get("FOSSLAB_FROM_TOOL") == "1"
    if env and explicit:
        return Path(env).expanduser()
    c = current_course()
    if c:
        from .course import workspace_of
        return workspace_of(c, Path.home())
    if env:
        return Path(env).expanduser()
    return Path.home() / WS_NAME


def editor() -> str:
    return os.environ.get("FOSSLAB_EDITOR") or os.environ.get("EDITOR") or "gedit"


def roster_entries() -> list[tuple[str, str, Path]]:
    """(course, user, home) of the supervisor's students, passed in by the host
    wrapper as "course/user:home;..." (course "" in the single-course setup)."""

    out = []
    for item in os.environ.get("FOSSLAB_ROSTER", "").split(";"):
        if ":" in item:
            who, home = item.split(":", 1)
            c, _, user = who.rpartition("/")
            out.append((c, user, Path(home)))
    return sorted(out)


def roster(course: str | None = None) -> list[tuple[str, Path]]:
    """Students as (user, home): of one course, or of all the supervisor's courses."""

    seen: dict[str, Path] = {}
    for c, user, home in roster_entries():
        if course is None or c == course:
            seen.setdefault(user, home)
    return sorted(seen.items())


def roster_courses() -> list[str]:
    return sorted({c for c, _, _ in roster_entries() if c})


def student_workspace(course: str, home: Path) -> Path:
    if not course:
        return home / WS_NAME          # single-course setup
    from .course import workspace_of
    return workspace_of(course, home)


# PDK paths used by the flows.
def pdk(*parts: str) -> Path:
    return PDK_PATH.joinpath(*parts)


IHP_XSCHEMRC = pdk("libs.tech", "xschem", "xschemrc")
IHP_MAGICRC = pdk("libs.tech", "magic", f"{PDK}.magicrc")
IHP_RUN_DRC = pdk("libs.tech", "klayout", "tech", "drc", "run_drc.py")
IHP_RUN_LVS = pdk("libs.tech", "klayout", "tech", "lvs", "run_lvs.py")
