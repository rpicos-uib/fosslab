"""Retake the tutorial's screenshots and numbers, from the tool.

    fosslab shots [--out ~/fosslab-shots] [--live]

or Tools > Retake tutorial screenshots in the Library Manager. Builds the
reference op-amp from scratch in OUT (never your workspace), runs every
flow, takes every screenshot from the real programs (OUT/screenshots/),
and compares the numbers with the values the tutorial's chapters quote.

By default everything happens on a private virtual display, so you can keep
working. With ``live`` the windows open on your own display (e.g. your X2Go
session) and the pictures show your desktop: do not touch the mouse or the
keyboard until it ends (about 10 minutes).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

Echo = Callable[[str], None]


def default_out() -> Path:
    return Path.home() / "fosslab-shots"


def _free_display() -> int:
    for n in range(70, 100):
        if not Path(f"/tmp/.X11-unix/X{n}").exists() and not Path(f"/tmp/.X{n}-lock").exists():
            return n
    raise RuntimeError("no free X display number between :70 and :99")


def run(out: Path, live: bool = False, echo: Echo = print) -> int:
    """Run the capture; returns its exit code. Screenshots in out/screenshots."""

    out = Path(out).expanduser()
    if out.resolve() == (Path.home() / "fosslab").resolve():
        echo("refusing to use your workspace ~/fosslab: choose another folder")
        return 2
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.setdefault("FOSSLAB_UI", "new")    # the tutorial shows the new interface
    xvfb = None
    if not live:
        n = _free_display()
        xvfb = subprocess.Popen(["Xvfb", f":{n}", "-screen", "0", "1600x1000x24", "-nolisten", "tcp"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
        env["DISPLAY"] = f":{n}"
        echo(f"private display :{n}")
    elif not env.get("DISPLAY"):
        echo("live mode needs a display")
        return 2
    try:
        p = subprocess.Popen([sys.executable, "-u", "-m", "fosslab.examples.shots", str(out / "work"),
                              str(out / "screenshots")], env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, errors="replace")
        assert p.stdout is not None
        with open(out / "shots.log", "w") as log:
            for line in p.stdout:
                log.write(line)
                echo(line.rstrip("\n"))
        return p.wait()
    finally:
        if xvfb is not None:
            xvfb.terminate()


# The values the chapters quote: (label, how to read it from results.json, as in the tutorial)
QUOTED = [
    ("DRC", lambda d: d["drc"], "DRC clean: 0 violations"),
    ("LVS", lambda d: d["lvs"], "LVS clean: netlists match"),
    ("A0 (dB)", lambda d: f"{d['tb_opamp_ac']['a0']:.2f}", "57.61"),
    ("UGF (MHz)", lambda d: f"{d['tb_opamp_ac']['ugf'] / 1e6:.2f}", "16.17"),
    ("PM (deg)", lambda d: f"{d['tb_opamp_ac']['pm']:.2f}", "60.38"),
    ("Offset (mV)", lambda d: f"{d['tb_opamp_ac']['vos'] * 1e3:.2f}", "1.73"),
    ("Power (uW)", lambda d: f"{d['tb_opamp_ac']['pdiss'] * 1e6:.1f}", "90.8"),
    ("SR+ / SR- (V/us)", lambda d: f"{d['tb_opamp_tran']['srp'] / 1e6:.1f} / {d['tb_opamp_tran']['srn'] / 1e6:.1f}",
     "10.6 / 10.3"),
    ("Post-layout UGF (MHz)", lambda d: f"{d['postlayout']['tb_opamp_ac']['ugf'] / 1e6:.2f}", "15.71"),
    ("Post-layout PM (deg)", lambda d: f"{d['postlayout']['tb_opamp_ac']['pm']:.2f}", "58.56"),
    ("MC offset mean / sigma (mV)",
     lambda d: f"{d['mc']['vos']['mean'] * 1e3:.2f} / {d['mc']['vos']['std'] * 1e3:.2f}", "1.72 / 2.14"),
    ("MC yield (%)", lambda d: f"{d['mc_yield'] * 100:.1f}", "94.5"),
    ("Model MC offset mean / sigma (mV)",
     lambda d: f"{d['va_mc']['vos']['mean'] * 1e3:.2f} / {d['va_mc']['vos']['std'] * 1e3:.2f}", "1.58 / 2.04"),
]


def compare(out: Path) -> list[tuple[str, str, str]]:
    """(what, this machine, tutorial) for every number the chapters quote."""

    d = json.loads((Path(out).expanduser() / "work" / "results.json").read_text())
    rows = []
    for label, get, quoted in QUOTED:
        try:
            here = get(d)
        except (KeyError, TypeError):
            here = "?"
        rows.append((label, str(here), quoted))
    return rows
