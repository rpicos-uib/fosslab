"""Which view of each cell a simulation uses: the testbench's hierarchy
configuration.

A cell keeps all its views together (libs/<lib>/<cell>/): schematic,
symbol, layout, Verilog-A model(s)... The testbench always instantiates the
cell's one symbol; what is simulated *inside* that symbol is chosen per
testbench, in the Simulation Environment (tab "Views"), and saved in its
setup:

    "views": {"opamp_tut/opamp": {"view": "veriloga",
                                  "params": {"A0dB": "agauss(A0dB_mean, A0dB_sd, 1)"}}}

How: xschem netlists the testbench as usual (every cell from its schematic);
then the ``.subckt <cell>`` it wrote is replaced by a wrapper with the same
pins that contains the chosen view instead:

    schematic          nothing to do
    extracted          the PEX netlist (post-layout simulation)
    veriloga[:<name>]  the Verilog-A model <cell>.va (or <name>.va), compiled
                       with OpenVAF and loaded into ngspice (pre_osdi); its
                       parameters can be any expression of the design
                       variables, e.g. agauss() for Monte Carlo

Pins are connected by name, so a view's pins may come in any order.
New kinds of view (digital: Verilog through ngspice's d_cosim, ...) plug in
here: a ``choices`` entry and a ``_substitute_*`` function.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .workspace import Workspace

Echo = Callable[[str], None]

SCHEMATIC = "schematic"
EXTRACTED = "extracted"
VERILOGA = "veriloga"


@dataclass
class Binding:
    view: str = SCHEMATIC
    params: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_json(cls, d) -> "Binding":
        if isinstance(d, str):
            return cls(d)
        return cls(str(d.get("view", SCHEMATIC)), {k: str(v) for k, v in (d.get("params") or {}).items()})

    def to_json(self) -> dict:
        return {"view": self.view, "params": {k: v for k, v in self.params.items() if str(v).strip()}}


def key(lib: str, cell: str) -> str:
    return f"{lib}/{cell}"


# --- what each cell offers -------------------------------------------------------------

def pex_netlist(ws: Workspace, lib: str, cell: str) -> Path:
    return ws.run_dir(lib, cell, "pex") / f"{cell}_pex.spice"


def va_files(ws: Workspace, lib: str, cell: str) -> list[Path]:
    """The cell's Verilog-A views: <cell>.va first, then any other .va in its folder."""

    d = ws.cell_dir(lib, cell)
    if not d.is_dir() or ws.library(lib).flat:
        return []
    files = sorted(d.glob("*.va"), key=lambda p: (p.stem != cell, p.stem))
    return [p for p in files if p.is_file()]


def va_view_name(cell: str, path: Path) -> str:
    return VERILOGA if path.stem == cell else f"{VERILOGA}:{path.stem}"


def choices(ws: Workspace, lib: str, cell: str) -> list[tuple[str, str]]:
    """(view, label) of every way to simulate this cell."""

    out = [(SCHEMATIC, "Schematic (transistors)")]
    if pex_netlist(ws, lib, cell).is_file():
        out.append((EXTRACTED, "Extracted (post-layout, from PEX)"))
    for p in va_files(ws, lib, cell):
        out.append((va_view_name(cell, p), f"Verilog-A model ({p.name})"))
    return out


def va_path(ws: Workspace, lib: str, cell: str, view: str) -> Path:
    stem = view.split(":", 1)[1] if ":" in view else cell
    return ws.cell_dir(lib, cell) / f"{stem}.va"


@dataclass
class VaModule:
    name: str
    ports: list[str]
    params: dict[str, str]          # name -> default, as written
    comments: dict[str, str]        # name -> the comment after it


def read_va(path: Path) -> VaModule:
    text = path.read_text(errors="replace")
    code = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    m = re.search(r"^\s*module\s+(\w+)\s*\(([^)]*)\)", code, re.M)
    if not m:
        raise ValueError(f"{path.name}: no 'module name(pins)' found")
    ports = [p.strip() for p in m.group(2).replace("\n", " ").split(",") if p.strip()]
    params, comments = {}, {}
    for pm in re.finditer(r"^\s*parameter\s+(?:real|integer|string)?\s*(\w+)\s*=\s*([^;]+?)\s*"
                          r"(?:from\s+[\[(][^;]*)?;[ \t]*(?://[ \t]*(.*))?$", code, re.M):
        params[pm.group(1)] = pm.group(2).strip()
        comments[pm.group(1)] = (pm.group(3) or "").strip()
    return VaModule(m.group(1), ports, params, comments)


def candidates(ws: Workspace, tb_schematic: Path) -> list[tuple[str, str]]:
    """(lib, cell) of every cell below the testbench that has more than one view to simulate."""

    from . import hierarchy

    out: list[tuple[str, str]] = []
    try:
        root = hierarchy.build(ws, tb_schematic)
    except (OSError, ValueError):
        return out

    def walk(n) -> None:
        for c in n.children:
            if c.lib and c.cell and (c.lib, c.cell) not in out:
                try:
                    lib = ws.library(c.lib)
                except KeyError:
                    lib = None
                if lib is not None and not lib.flat and len(choices(ws, c.lib, c.cell)) > 1:
                    out.append((c.lib, c.cell))
            walk(c)
    walk(root)
    return out


# --- netlist substitution ----------------------------------------------------------------

def _find_subckt(text: str, cell: str):
    from .flows import FlowError

    m = re.compile(r"^\.subckt\s+" + re.escape(cell) + r"\b([^\n]*)\n.*?^\.ends\b[^\n]*\n",
                   re.M | re.S | re.I).search(text)
    if not m:
        raise FlowError(f"{cell} is not a subcircuit of this netlist")
    return m


def _ports(header: str) -> list[str]:
    return [p for p in header.split() if "=" not in p]


def _before_control(text: str, lines: str) -> str:
    m = re.search(r"^\s*\.control\b", text, re.M | re.I)
    if m:
        return text[:m.start()] + lines + text[m.start():]
    m = re.search(r"^\s*\.end\s*$", text, re.M | re.I)
    return (text[:m.start()] + lines + text[m.start():]) if m else text + lines


def compile_va(ws: Workspace, lib: str, cell: str, view: str, echo: Echo | None = None) -> Path:
    """The compiled model (.osdi) of a Verilog-A view, compiled again only when the source is newer."""

    from . import flows

    src = va_path(ws, lib, cell, view)
    osdi = flows.osdi_path(ws, lib, cell, src.stem)
    if osdi.is_file() and osdi.stat().st_mtime >= src.stat().st_mtime:
        return osdi
    res = flows.compile_va(ws, lib, cell, echo=echo, stem=src.stem)
    if not res.ok:
        raise flows.FlowError(f"{src.name}: {res.summary} ({res.log})")
    return osdi


def _substitute_va(text: str, ws: Workspace, lib: str, cell: str, b: Binding, echo) -> str:
    from .flows import FlowError

    src = va_path(ws, lib, cell, b.view)
    if not src.is_file():
        raise FlowError(f"{lib}/{cell} has no Verilog-A view {src.name}")
    mod = read_va(src)
    m = _find_subckt(text, cell)
    sch_ports = _ports(m.group(1))
    by_name = {p.lower(): p for p in sch_ports}
    missing = [p for p in mod.ports if p.lower() not in by_name]
    if missing:
        raise FlowError(f"pins {', '.join(missing)} of {src.name} are not pins of the symbol of {cell}")
    unknown = [p for p in b.params if p not in mod.params]
    if unknown:
        raise FlowError(f"{src.name} has no parameter {', '.join(unknown)}")
    osdi = compile_va(ws, lib, cell, b.view, echo)
    model = f"{cell}__{src.stem}"
    wrapper = (f"* {cell}: Verilog-A view ({src})\n"
               f".subckt {cell} {' '.join(sch_ports)}\n"
               f"N{src.stem} {' '.join(by_name[p.lower()] for p in mod.ports)} {model}\n"
               f".ends {cell}\n")
    text = text[:m.start()] + wrapper + text[m.end():]
    given = {p: v.strip() for p, v in b.params.items() if v.strip()}
    lines = f"* parameters of {src.name} (Simulation Environment, tab Views)\n"
    for p, v in given.items():
        lines += f".param {model}__{p}={v}\n"
    lines += f".model {model} {mod.name}" + "".join(f" {p}={{{model}__{p}}}" for p in given) + "\n"
    text = _before_control(text, lines)
    if not re.search(r"^\s*\.control\b", text, re.M | re.I):
        raise FlowError("the testbench has no .control block to load the Verilog-A model into")
    load = f"pre_osdi {osdi}\n"
    if load not in text:
        text = re.sub(r"^(\s*\.control[^\n]*\n)", lambda mm: mm.group(1) + load, text, count=1,
                      flags=re.M | re.I)
    return text


def apply(ws: Workspace, text: str, bindings: dict[str, Binding], workdir: Path,
          echo: Echo | None = None) -> str:
    """The testbench netlist with each cell simulated from the view chosen for it."""

    from . import flows

    pex = {}
    for k, b in bindings.items():
        if b.view == SCHEMATIC or "/" not in k:
            continue
        lib, cell = k.split("/", 1)
        if b.view == EXTRACTED:
            p = pex_netlist(ws, lib, cell)
            if not p.is_file():
                raise flows.FlowError(f"no extracted view for {cell}: run PEX on it first")
            pex[cell] = p
        elif b.view == VERILOGA or b.view.startswith(VERILOGA + ":"):
            text = _substitute_va(text, ws, lib, cell, b, echo)
        else:
            raise flows.FlowError(f"{k}: unknown view '{b.view}'")
    if pex:
        text = flows.substitute_extracted(text, pex, workdir)
    return text


def summary(bindings: dict[str, Binding]) -> str:
    used = [f"{k.split('/', 1)[1]}: {b.view}" for k, b in bindings.items() if b.view != SCHEMATIC]
    return ", ".join(used)
