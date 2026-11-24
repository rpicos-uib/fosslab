"""Batch flows: netlist, simulate, DRC, LVS, PEX, compile Verilog-A.

Each flow runs in its own folder (sim/<lib>/<cell>/ or
verif/<lib>/<cell>/<flow>/), keeps the full log there and writes a
status.json that the Library Manager and the supervisor read:

    {"flow": "lvs", "status": "pass" | "fail" | "error",
     "summary": "...", "time": 1700000000, "log": "...", "inputs": {...}}
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from . import config, tools
from .workspace import Workspace

Echo = Callable[[str], None]


@dataclass
class FlowResult:
    flow: str
    status: str                 # pass | fail | error
    summary: str
    run_dir: str
    log: str = ""
    time: float = field(default_factory=time.time)
    inputs: dict = field(default_factory=dict)
    outputs: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "pass"

    def save(self) -> "FlowResult":
        Path(self.run_dir).mkdir(parents=True, exist_ok=True)
        (Path(self.run_dir) / "status.json").write_text(json.dumps(asdict(self), indent=2))
        return self


class FlowError(Exception):
    pass


def _print(line: str) -> None:
    print(line, flush=True)


def run(argv: list[str], cwd: Path, log: Path, echo: Echo | None = None,
        env: dict[str, str] | None = None, timeout: float | None = None) -> int:
    """Run a command, tee its output to ``log`` and to ``echo`` line by line."""

    echo = echo or _print
    cwd.mkdir(parents=True, exist_ok=True)
    full_env = dict(os.environ)
    full_env["FOSSLAB_BATCH"] = "1"
    if env:
        full_env.update(env)
    with open(log, "a") as f:
        f.write(f"$ cd {cwd}\n$ {' '.join(argv)}\n")
        echo(f"$ {' '.join(argv)}")
        proc = subprocess.Popen(argv, cwd=str(cwd), env=full_env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True,
                                errors="replace")
        start = time.time()
        assert proc.stdout is not None
        for line in proc.stdout:
            f.write(line)
            echo(line.rstrip("\n"))
            if timeout and time.time() - start > timeout:
                proc.kill()
                echo("fosslab: timeout, process killed")
                break
        return proc.wait()


def _fresh(d: Path) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    for name in ("status.json",):
        (d / name).unlink(missing_ok=True)
    return d


# --- netlisting ---------------------------------------------------------------

def netlist(ws: Workspace, lib: str, cell: str, out_dir: Path | None = None,
            lvs: bool = False, schematic: Path | None = None,
            echo: Echo | None = None) -> Path:
    """Netlist a schematic with xschem in batch mode. Returns the netlist path."""

    sch = schematic or ws.view_path(lib, cell, "schematic")
    if not sch.is_file():
        raise FlowError(f"{lib}/{cell} has no schematic")
    rc, env = tools.xschem_setup(ws)
    out_dir = out_dir or ws.sim_dir(lib, cell)
    out_dir.mkdir(parents=True, exist_ok=True)
    argv = ["xschem", "--rcfile", str(rc), "-q", "-x"]
    if lvs:
        argv += ["--tcl", "set lvs_netlist 1; set top_subckt 1"]
    argv += ["-n", "-s", "-o", str(out_dir), str(sch)]
    log = out_dir / ("netlist_lvs.log" if lvs else "netlist.log")
    log.unlink(missing_ok=True)
    produced = out_dir / f"{sch.stem}.spice"
    produced.unlink(missing_ok=True)
    # xschem's exit code is not 0 whenever its connectivity check complains
    # (e.g. "undriven node" for a net driven from a code block, normal in a
    # testbench), so success means: a netlist was written.
    run(argv, out_dir, log, echo, env=env, timeout=300)
    if not produced.is_file():
        raise FlowError(f"xschem could not netlist {sch.name} (see {log})")
    return produced


def erc_messages(log: Path) -> list[str]:
    """xschem's connectivity warnings from a netlist log."""

    if not log.is_file():
        return []
    return [ln.strip() for ln in log.read_text(errors="replace").splitlines()
            if ln.startswith(("Warning:", "Error:"))]


def _ports(header: str) -> list[str]:
    return [p for p in header.split() if "=" not in p]


def substitute_extracted(netlist_text: str, replacements: dict[str, Path], workdir: Path) -> str:
    """Hierarchy configuration: simulate each cell in ``replacements`` from its
    extracted (PEX) netlist instead of its schematic.

    The extractor orders the subcircuit pins its own way, so the cell is
    replaced by a wrapper with the schematic's pin order that connects the
    extracted subcircuit pin by pin, by name."""

    out = netlist_text
    for cell, pex in replacements.items():
        m = re.compile(r"^\.subckt\s+" + re.escape(cell) + r"\b([^\n]*)\n.*?^\.ends\b[^\n]*\n",
                       re.M | re.S | re.I).search(out)
        if not m:
            raise FlowError(f"{cell} is not a subcircuit of this netlist")
        sch_ports = _ports(m.group(1))
        pex_text = pex.read_text(errors="replace")
        pm = re.search(r"^\.subckt\s+" + re.escape(cell) + r"\b([^\n]*)", pex_text, re.M | re.I)
        if not pm:
            raise FlowError(f"{pex.name} has no subcircuit {cell}")
        pex_ports = _ports(pm.group(1))
        missing = [p for p in sch_ports if p.lower() not in {q.lower() for q in pex_ports}]
        if missing:
            raise FlowError(f"pins {', '.join(missing)} of {cell} have no label in the layout, "
                            "so the extracted netlist cannot be connected")
        renamed = workdir / f"{cell}__pex.spice"
        renamed.write_text(re.sub(r"^(\.subckt\s+)" + re.escape(cell) + r"\b",
                                  lambda mm: mm.group(1) + f"{cell}__pex", pex_text,
                                  flags=re.M | re.I))
        wrapper = (f"* {cell}: extracted view ({pex})\n"
                   f".subckt {cell} {' '.join(sch_ports)}\n"
                   f"Xpex {' '.join(pex_ports)} {cell}__pex\n"
                   f".ends {cell}\n"
                   f".include {renamed}\n")
        out = out[:m.start()] + wrapper + out[m.end():]
    return out


# --- simulation -----------------------------------------------------------------

def simulate(ws: Workspace, lib: str, cell: str, schematic: Path | None = None,
             use_extracted: list[str] | None = None, echo: Echo | None = None) -> FlowResult:
    sch = schematic or ws.view_path(lib, cell, "schematic")
    d = _fresh(ws.sim_dir(lib, cell))
    log = d / "ngspice.log"
    log.unlink(missing_ok=True)
    res = FlowResult("sim", "error", "", str(d), str(log), inputs={"schematic": str(sch)})
    try:
        net = netlist(ws, lib, cell, d, schematic=sch, echo=echo)
    except FlowError as e:
        res.summary = str(e)
        return res.save()
    if use_extracted:
        repl = {}
        for c in use_extracted:
            p = ws.run_dir(lib, c, "pex") / f"{c}_pex.spice"
            if not p.is_file():
                res.summary = f"no extracted view for {c}: run PEX on it first"
                return res.save()
            repl[c] = p
        try:
            net.write_text(substitute_extracted(net.read_text(), repl, d))
        except FlowError as e:
            res.summary = str(e)
            return res.save()
        res.inputs["extracted"] = {c: str(p) for c, p in repl.items()}
    before = {p: p.stat().st_mtime for p in d.glob("*.raw")}
    # IHP testbenches may .include <cell>.save (created by the IHP menu)
    (d / f"{net.stem}.save").touch(exist_ok=True)
    code = run(["ngspice", "-b", net.name], d, log, echo, timeout=3600)
    text = log.read_text(errors="replace")
    errors = [ln for ln in text.splitlines()
              if re.match(r"^\s*(Error|ERROR)\b", ln) or "simulation interrupted" in ln.lower()]
    raws = [p for p in d.glob("*.raw") if before.get(p) != p.stat().st_mtime]
    res.outputs = {"raw": [str(p) for p in raws], "netlist": str(net),
                   "erc": erc_messages(d / "netlist.log")}
    if code != 0 or errors:
        res.status = "fail"
        res.summary = errors[0].strip() if errors else f"ngspice exit code {code}"
    else:
        res.status = "pass"
        res.summary = "simulation finished" + (f", {len(raws)} .raw file(s)" if raws else "")
    return res.save()


# --- DRC --------------------------------------------------------------------------

def _layout_for(ws: Workspace, lib: str, cell: str) -> Path:
    gds = ws.view_path(lib, cell, "layout")
    if not gds.is_file():
        raise FlowError(f"{lib}/{cell} has no layout ({gds.name})")
    return gds


def lyrdb_counts(path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return counts
    for item in root.iter("item"):
        cat = (item.findtext("category") or "?").strip().strip("'")
        counts[cat] = counts.get(cat, 0) + 1
    return counts


def drc(ws: Workspace, lib: str, cell: str, density: bool = False, antenna: bool = False,
        echo: Echo | None = None) -> FlowResult:
    d = ws.run_dir(lib, cell, "drc")
    if d.is_dir():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    log = d / "drc.log"
    res = FlowResult("drc", "error", "", str(d), str(log))
    try:
        gds = _layout_for(ws, lib, cell)
    except FlowError as e:
        res.summary = str(e)
        return res.save()
    res.inputs = {"layout": str(gds)}
    argv = [sys.executable, str(config.IHP_RUN_DRC), f"--path={gds}", f"--topcell={cell}",
            f"--run_dir={d}"]
    if not density:
        argv.append("--no_density")
    if antenna:
        argv.append("--antenna")
    code = run(argv, d, log, echo, timeout=3600)
    dbs = sorted(d.glob("*.lyrdb"))
    if not dbs:
        res.summary = f"DRC did not produce a report (exit code {code})"
        return res.save()
    counts: dict[str, int] = {}
    for db in dbs:
        for k, v in lyrdb_counts(db).items():
            counts[k] = counts.get(k, 0) + v
    total = sum(counts.values())
    res.outputs = {"reports": [str(p) for p in dbs], "violations": counts}
    if total == 0:
        res.status, res.summary = "pass", "DRC clean: 0 violations"
    else:
        top = ", ".join(f"{k}: {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])[:5])
        res.status, res.summary = "fail", f"{total} DRC violations ({top})"
    return res.save()


# --- LVS --------------------------------------------------------------------------

def lvs(ws: Workspace, lib: str, cell: str, echo: Echo | None = None) -> FlowResult:
    d = ws.run_dir(lib, cell, "lvs")
    if d.is_dir():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    log = d / "lvs.log"
    res = FlowResult("lvs", "error", "", str(d), str(log))
    try:
        gds = _layout_for(ws, lib, cell)
        net = netlist(ws, lib, cell, d, lvs=True, echo=echo)
    except FlowError as e:
        res.summary = str(e)
        return res.save()
    cdl = d / f"{cell}.cdl"
    net.rename(cdl)
    res.inputs = {"layout": str(gds), "schematic_netlist": str(cdl)}
    # Substrate/well taps (ptap1, ntap1) are not drawn in schematics: they only
    # connect the bulk, so they are not extracted as devices.
    argv = [sys.executable, str(config.IHP_RUN_LVS), f"--layout={gds}", f"--netlist={cdl}",
            f"--topcell={cell}", f"--run_dir={d}", "--disable_tap_extraction"]
    code = run(argv, d, log, echo, timeout=3600)
    text = "\n".join(p.read_text(errors="replace") for p in d.glob("*.log"))
    extracted = d / f"{gds.stem}_extracted.cir"
    if extracted.is_file() and gds.stem != cell:
        extracted.rename(d / f"{cell}_extracted.cir")
    lvsdb = sorted(d.glob("*.lvsdb"))
    res.outputs = {"lvsdb": [str(p) for p in lvsdb],
                   "extracted": str(d / f"{cell}_extracted.cir")}
    if "Netlists match" in text or "PASS (netlists match)" in text:
        res.status, res.summary = "pass", "LVS clean: netlists match"
    elif re.search(r"[Nn]etlists don'?t match|do not match|FAIL", text):
        res.status, res.summary = "fail", "LVS: netlists don't match (open the report in KLayout)"
    else:
        res.summary = f"LVS did not finish (exit code {code}), see the log"
    return res.save()


# --- PEX (Magic) --------------------------------------------------------------------

def pex(ws: Workspace, lib: str, cell: str, cthresh: float = 0.0,
        echo: Echo | None = None) -> FlowResult:
    d = ws.run_dir(lib, cell, "pex")
    if d.is_dir():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    log = d / "magic.log"
    res = FlowResult("pex", "error", "", str(d), str(log))
    try:
        gds = _layout_for(ws, lib, cell)
    except FlowError as e:
        res.summary = str(e)
        return res.save()
    out = d / f"{cell}_pex.spice"
    script = d / "pex.tcl"
    script.write_text("\n".join([
        "crashbackups stop",
        "drc off",
        f"gds read {{{gds}}}",
        f"load {cell}",
        "select top cell",
        f"extract path {{{d}}}",
        "extract all",
        "ext2spice lvs",
        f"ext2spice cthresh {cthresh}",
        f"ext2spice -p {{{d}}} -o {{{out}}}",
        "quit -noprompt",
    ]) + "\n")
    code = run(["magic", "-dnull", "-noconsole", "-rcfile", str(config.IHP_MAGICRC), str(script)],
               d, log, echo, timeout=3600)
    res.inputs = {"layout": str(gds)}
    if out.is_file():
        text = out.read_text(errors="replace")
        ncap = len(re.findall(r"^C\d+", text, re.M))
        ndev = len(re.findall(r"^[XM]\S*", text, re.M))
        res.status = "pass"
        res.summary = f"extracted {ndev} devices and {ncap} parasitic capacitors"
        res.outputs = {"netlist": str(out)}
    else:
        res.summary = f"Magic did not write a netlist (exit code {code}), see the log"
    return res.save()


# --- Verilog-A ------------------------------------------------------------------------

def compile_va(ws: Workspace, lib: str, cell: str, echo: Echo | None = None) -> FlowResult:
    va = ws.view_path(lib, cell, "veriloga")
    d = va.parent
    log = ws.run_root / "verif" / lib / cell / "openvaf.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.unlink(missing_ok=True)
    res = FlowResult("va", "error", "", str(log.parent), str(log))
    if not va.is_file():
        res.summary = f"{lib}/{cell} has no Verilog-A view"
        return res
    osdi = d / f"{cell}.osdi"
    code = run(["openvaf", str(va), "-o", str(osdi)], d, log, echo, timeout=600)
    if code == 0 and osdi.is_file():
        res.status, res.summary = "pass", f"compiled to {osdi.name}"
        res.outputs = {"osdi": str(osdi)}
    else:
        res.status, res.summary = "fail", "OpenVAF reported errors, see the log"
    return res


FLOWS = {"sim": simulate, "drc": drc, "lvs": lvs, "pex": pex, "va": compile_va}
