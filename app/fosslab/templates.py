"""Create new view files: File > New > Cell view."""

from __future__ import annotations

import time
from pathlib import Path

from . import xschemfile
from .workspace import Workspace


def create_view(ws: Workspace, lib: str, cell: str, kind: str) -> Path:
    library = ws.library(lib)
    if library.readonly:
        raise PermissionError(f"library '{lib}' is read only")
    path = ws.view_path(library, cell, kind)
    if path.exists():
        raise FileExistsError(f"{path} already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    sch = ws.view_path(library, cell, "schematic")
    pins = xschemfile.schematic_pins(sch) if sch.is_file() else []

    if kind == "schematic":
        path.write_text(xschemfile.empty_schematic())
    elif kind == "symbol":
        path.write_text(xschemfile.symbol_from_pins(cell, pins))
    elif kind == "layout":
        new_gds(path, cell)
    elif kind == "magic":
        path.write_text(f"magic\ntech ihp-sg13g2\ntimestamp {int(time.time())}\n<< end >>\n")
    elif kind == "veriloga":
        path.write_text(veriloga_template(cell, pins))
    elif kind == "verilog":
        path.write_text(verilog_template(cell, pins))
    elif kind == "spice":
        names = " ".join(p.name for p in pins) or "IN OUT VDD VSS"
        path.write_text(f"* {cell}: hand-written subcircuit\n.subckt {cell} {names}\n\n.ends {cell}\n")
    elif kind == "notes":
        path.write_text(f"# {lib}/{cell}\n\nDesign notes.\n")
    else:
        raise ValueError(f"cannot create a '{kind}' view")
    return path


def update_symbol(ws: Workspace, lib: str, cell: str) -> Path:
    """(Re)generate the symbol from the schematic's pins."""

    sch = ws.view_path(lib, cell, "schematic")
    if not sch.is_file():
        raise FileNotFoundError(f"{lib}/{cell} has no schematic")
    pins = xschemfile.schematic_pins(sch)
    if not pins:
        raise ValueError("the schematic has no pins (ipin/opin/iopin): nothing to put on a symbol")
    sym = ws.view_path(lib, cell, "symbol")
    if sym.exists():
        sym.with_suffix(".sym.bak").write_text(sym.read_text())
    sym.write_text(xschemfile.symbol_from_pins(cell, pins))
    return sym


# --- testbenches ------------------------------------------------------------

MODELS_BLOCK = ".lib cornerMOSlv.lib mos_tt\n"


def create_testbench(ws: Workspace, lib: str, dut_cell: str, tb_cell: str | None = None) -> Path:
    """A new cell ``tb_<dut>`` whose schematic holds the DUT's symbol,
    the IHP model library and an ngspice control block ready to edit."""

    tb_cell = tb_cell or f"tb_{dut_cell}"
    dut_sym = ws.view_path(lib, dut_cell, "symbol")
    if not dut_sym.is_file():
        raise FileNotFoundError(f"{lib}/{dut_cell} has no symbol yet: create it first")
    ws.new_cell(lib, tb_cell)
    sch = ws.view_path(lib, tb_cell, "schematic")
    library = ws.library(lib)
    ref = f"{library.path.name}/{dut_cell}/{dut_cell}.sym"

    pins = []
    for o in xschemfile.parse_file(dut_sym):
        if o.type == "B" and o.words and o.words[0] == "5":
            p = o.props
            pins.append((p.get("name", ""), float(o.words[1]), float(o.words[2]),
                         float(o.words[3]), float(o.words[4])))

    lines = [
        xschemfile.instance_line(ref, 400, -300, {"name": "x1"}),
        # Label every DUT pin with its own name so the nets are named.
        *[xschemfile.instance_line("lab_pin.sym", 400 + int((x1 + x2) / 2), -300 + int((y1 + y2) / 2),
                                   {"name": f"l{i + 1}", "sig_type": "std_logic", "lab": name},
                                   flip=0 if (x1 + x2) / 2 < 0 else 1)
          for i, (name, x1, y1, x2, y2) in enumerate(pins)],
        xschemfile.instance_line("devices/code_shown.sym", 0, -100, {
            "name": "MODEL", "only_toplevel": "true", "format": "tcleval( @value )",
            "value": MODELS_BLOCK}),
        xschemfile.instance_line("devices/code_shown.sym", 0, -600, {
            "name": "NGSPICE", "only_toplevel": "true",
            "value": "\n.param temp=27\n.control\nsave all\nop\n"
                     f"write {tb_cell}.raw\n.endc\n"}),
        xschemfile.instance_line("devices/title.sym", 160, -30, {"name": "title", "author": "FOSSLab"}),
    ]
    sch.write_text(xschemfile.empty_schematic("\n".join(lines) + "\n"))
    return sch


# --- language templates -------------------------------------------------------

def veriloga_template(cell: str, pins) -> str:
    names = [p.name for p in pins] or ["inp", "inn", "out"]
    ins = [p.name for p in pins if p.dir == "in"]
    outs = [p.name for p in pins if p.dir == "out"]
    body = ""
    if len(ins) >= 2 and outs:
        body = (f"    // Example: an ideal amplifier with gain A\n"
                f"    V({outs[0]}) <+ A * (V({ins[0]}) - V({ins[1]}));\n")
    return (
        '`include "constants.vams"\n`include "disciplines.vams"\n\n'
        f"module {cell}({', '.join(names)});\n"
        f"    inout {', '.join(names)};\n"
        f"    electrical {', '.join(names)};\n"
        "    parameter real A = 1000.0;\n\n"
        "    analog begin\n"
        f"{body}"
        "    end\n"
        "endmodule\n"
    )


def verilog_template(cell: str, pins) -> str:
    decl = []
    for p in pins:
        d = {"in": "input", "out": "output"}.get(p.dir, "inout")
        decl.append(f"    {d} wire {p.name}")
    if not decl:
        decl = ["    input wire a", "    output wire y"]
    return f"module {cell} (\n" + ",\n".join(decl) + "\n);\n\nendmodule\n"


# --- layouts (KLayout's own Python module, available in the image) -------------

def new_gds(path: Path, cell: str) -> None:
    import klayout.db as db

    layout = db.Layout()
    layout.dbu = 0.001
    layout.create_cell(cell)
    layout.write(str(path))


def extract_gds_cell(src: Path, cell: str, dst: Path, new_name: str | None = None) -> None:
    import klayout.db as db

    lay = db.Layout()
    lay.read(str(src))
    c = lay.cell(cell)
    if c is None:
        return
    out = db.Layout()
    out.dbu = lay.dbu
    top = out.create_cell(new_name or cell)
    top.copy_tree(c)
    out.write(str(dst))


def rename_gds_cell(path: Path, old: str, new: str) -> None:
    import klayout.db as db

    lay = db.Layout()
    lay.read(str(path))
    c = lay.cell(old)
    if c is not None:
        c.name = new
        lay.write(str(path))


def gds_top_cells(path: Path) -> list[str]:
    import klayout.db as db

    lay = db.Layout()
    lay.read(str(path))
    return [c.name for c in lay.top_cells()]

