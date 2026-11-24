"""Design hierarchy: follow schematic instances down to the primitives.

Symbols are resolved the way xschem resolves them: the path written in the
schematic (``lib/cell/cell.sym`` or ``sg13g2_pr/sg13_lv_nmos.sym``) is tried
against each library-path directory in turn. A symbol of type ``subcircuit``
with a schematic next to it (same name, ``.sch``) is a hierarchical block;
everything else is a leaf.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import config, xschemfile
from .workspace import Workspace


def search_path(ws: Workspace) -> list[Path]:
    xs = config.pdk("libs.tech", "xschem")
    devices = config.TOOLS / "xschem" / "share" / "xschem" / "xschem_library"
    return [
        *ws.xschem_library_path(),
        devices / "devices",
        devices,
        xs,
        xs / "sg13g2_pr",
        config.pdk("libs.ref", "sg13g2_stdcell", "sym", "xschem"),
    ]


def resolve_symbol(ref: str, paths: list[Path], relative_to: Path | None = None) -> Path | None:
    ref = ref.strip()
    if not ref.endswith(".sym") and not ref.endswith(".sch"):
        ref += ".sym"
    p = Path(ref)
    if p.is_absolute():
        return p if p.is_file() else None
    if relative_to is not None and (relative_to / p).is_file():
        return relative_to / p
    for d in paths:
        if (d / p).is_file():
            return d / p
    return None


def schematic_for(sym: Path) -> Path | None:
    if sym.suffix == ".sch":
        return sym
    props = xschemfile.symbol_props(sym)
    if props.get("type", "") not in ("subcircuit", "") and "tcleval" not in props.get("type", ""):
        return None
    explicit = props.get("schematic", "")
    if explicit and "tcleval" not in explicit:
        cand = sym.parent / explicit
        if cand.is_file():
            return cand
    cand = sym.with_suffix(".sch")
    if cand.is_file():
        return cand
    # IHP standard cells keep schematics in a sibling sch/ tree.
    alt = Path(str(sym.parent).replace("/sym/", "/sch/")) / (sym.stem + ".sch")
    return alt if alt.is_file() else None


@dataclass
class Node:
    instance: str              # instance name in the parent ("" for the top)
    symbol_ref: str            # as written in the parent schematic
    symbol: Path | None
    schematic: Path | None
    lib: str = ""
    cell: str = ""
    children: list["Node"] = field(default_factory=list)
    recursive: bool = False    # this cell already appears above it (a loop)

    @property
    def is_leaf(self) -> bool:
        return self.schematic is None


def build(ws: Workspace, top_sch: Path, max_depth: int = 30,
          include_pins: bool = False) -> Node:
    paths = search_path(ws)
    top_sch = Path(top_sch)
    loc = ws.locate(top_sch)
    root = Node("", top_sch.name, None, top_sch,
                lib=loc[0].name if loc else "", cell=loc[1] if loc else top_sch.stem)
    _expand(ws, root, paths, [top_sch.resolve()], max_depth, include_pins)
    return root


SKIP = {"ipin.sym", "opin.sym", "iopin.sym", "lab_pin.sym", "lab_wire.sym", "gnd.sym",
        "vdd.sym", "code.sym", "code_shown.sym", "title.sym", "title-2.sym", "title-3.sym",
        "launcher.sym", "noconn.sym", "architecture.sym", "netlist_options.sym",
        "annotate_fet_params.sym", "annotate_bip_params.sym", "ngspice_probe.sym",
        "ngspice_get_value.sym", "ngspice_get_expr.sym", "spice_probe.sym"}


def _expand(ws, node: Node, paths, stack: list[Path], depth: int, include_pins: bool) -> None:
    if depth <= 0 or node.schematic is None:
        return
    for inst in xschemfile.instances(node.schematic):
        base = inst.symbol.rsplit("/", 1)[-1]
        if not include_pins and base in SKIP:
            continue
        sym = resolve_symbol(inst.symbol, paths, node.schematic.parent)
        sch = schematic_for(sym) if sym else None
        child = Node(inst.name, inst.symbol, sym, sch)
        if sym:
            loc = ws.locate(sym)
            if loc:
                child.lib, child.cell = loc[0].name, loc[1]
        if not child.cell:
            child.cell = Path(inst.symbol).stem
            child.lib = Path(inst.symbol).parent.name if "/" in inst.symbol else ""
        if sch is not None:
            key = sch.resolve()
            if key in stack:
                child.recursive = True
            else:
                _expand(ws, child, paths, stack + [key], depth - 1, include_pins)
        node.children.append(child)


def flatten_counts(root: Node) -> dict[str, int]:
    """How many times each lib/cell is used in the whole design."""

    counts: dict[str, int] = {}

    def walk(n: Node, mult: int) -> None:
        for c in n.children:
            key = f"{c.lib}/{c.cell}" if c.lib else c.cell
            counts[key] = counts.get(key, 0) + mult
            walk(c, mult)

    walk(root, 1)
    return counts


def to_text(root: Node) -> str:
    lines = [f"{root.lib}/{root.cell}" if root.lib else root.cell]

    def walk(n: Node, prefix: str) -> None:
        for i, c in enumerate(n.children):
            last = i == len(n.children) - 1
            tag = "" if c.symbol else "  [symbol not found]"
            if c.recursive:
                tag += "  [recursive]"
            elif not c.is_leaf:
                tag += "  (schematic)"
            name = f"{c.lib}/{c.cell}" if c.lib else c.cell
            lines.append(f"{prefix}{'└── ' if last else '├── '}{c.instance}: {name}{tag}")
            walk(c, prefix + ("    " if last else "│   "))

    walk(root, "")
    return "\n".join(lines)
