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


def default_workspace() -> Path:
    env = os.environ.get("FOSSLAB_WORKSPACE")
    if env:
        return Path(env).expanduser()
    return Path.home() / WS_NAME


def editor() -> str:
    return os.environ.get("FOSSLAB_EDITOR") or os.environ.get("EDITOR") or "gedit"


def roster() -> list[tuple[str, Path]]:
    """Students as (user, home), passed in by the host wrapper."""

    out = []
    for item in os.environ.get("FOSSLAB_ROSTER", "").split(";"):
        if ":" in item:
            user, home = item.split(":", 1)
            out.append((user, Path(home)))
    return sorted(out)


# PDK paths used by the flows.
def pdk(*parts: str) -> Path:
    return PDK_PATH.joinpath(*parts)


IHP_XSCHEMRC = pdk("libs.tech", "xschem", "xschemrc")
IHP_MAGICRC = pdk("libs.tech", "magic", f"{PDK}.magicrc")
IHP_RUN_DRC = pdk("libs.tech", "klayout", "tech", "drc", "run_drc.py")
IHP_RUN_LVS = pdk("libs.tech", "klayout", "tech", "lvs", "run_lvs.py")
