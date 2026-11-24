"""``fosslab selftest``: every tool and flow, on real IHP SG13G2 data.

Builds a throw-away workspace with an inverter whose schematic is
generated here and whose layout is IHP's own sg13g2_inv_1, then runs:
symbol generation, hierarchy, testbench, simulation, DRC, LVS, PEX and a
post-layout simulation of the extracted inverter. This is what the
install script runs to say "the machine is ready".
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from . import config, flows, hierarchy, templates, xschemfile
from .workspace import Workspace

CELL = "inv"


def _check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{': ' + detail if detail else ''}", flush=True)
    return ok


def _tool_versions() -> list[bool]:
    results = []
    for argv, needle in ((["xschem", "--version"], "XSCHEM"),
                         (["klayout", "-v"], "KLayout"),
                         (["ngspice", "--version"], "ngspice"),
                         (["magic", "--version"], "."),
                         (["openvaf", "--version"], "OpenVAF"),
                         (["netgen", "-batch", "quit"], "Netgen"),
                         (["iverilog", "-V"], "Icarus"),
                         (["yosys", "-V"], "Yosys")):
        try:
            out = subprocess.run(argv, capture_output=True, text=True, timeout=60,
                                 stdin=subprocess.DEVNULL)
            text = (out.stdout + out.stderr).strip()
            line = next((ln for ln in text.splitlines() if needle.lower() in ln.lower()), "")
            results.append(_check(argv[0], bool(line), line.strip()[:70]))
        except (OSError, subprocess.TimeoutExpired) as e:
            results.append(_check(argv[0], False, str(e)))
    return results


def build_inverter(ws: Workspace, lib: str = "work") -> None:
    """Schematic generated from a netlist; layout copied from IHP's stdcell GDS."""

    ws.new_cell(lib, CELL)
    paths = hierarchy.search_path(ws)
    b = xschemfile.SchematicBuilder(lambda ref: hierarchy.resolve_symbol(ref, paths))
    b.device("sg13g2_pr/sg13_lv_pmos.sym", 300, -400,
             {"name": "M2", "l": "0.13u", "w": "1.12u", "ng": "1", "m": "1",
              "model": "sg13_lv_pmos", "spiceprefix": "X"},
             {"D": "Y", "G": "A", "S": "VDD", "B": "VDD"})
    b.device("sg13g2_pr/sg13_lv_nmos.sym", 300, -200,
             {"name": "M1", "l": "0.13u", "w": "0.74u", "ng": "1", "m": "1",
              "model": "sg13_lv_nmos", "spiceprefix": "X"},
             {"D": "Y", "G": "A", "S": "VSS", "B": "VSS"})
    b.pin("ipin", 100, -300, "A")
    b.pin("opin", 500, -300, "Y")
    b.pin("iopin", 100, -500, "VDD")
    b.pin("iopin", 100, -100, "VSS")
    ws.view_path(lib, CELL, "schematic").write_text(b.text())
    templates.update_symbol(ws, lib, CELL)
    gds = config.pdk("libs.ref", "sg13g2_stdcell", "gds", "sg13g2_stdcell.gds")
    templates.extract_gds_cell(gds, "sg13g2_inv_1", ws.view_path(lib, CELL, "layout"), CELL)


def build_testbench(ws: Workspace, lib: str = "work") -> Path:
    sch = templates.create_testbench(ws, lib, CELL)
    tb = f"tb_{CELL}"
    text = sch.read_text().replace(
        "\n.param temp=27\n.control",
        "\nVDD VDD 0 1.2\nVSS VSS 0 0\nVA A 0 PULSE(0 1.2 0.2n 50p 50p 1n 2n)\n"
        ".param temp=27\n.control")
    text = text.replace("save all\nop\n", "save all\ntran 5p 4n\n")
    text = text.replace(f"write {tb}.raw", f"write {tb}.raw\nmeas tran tpd_hl TRIG v(A) VAL=0.6 RISE=1 "
                                            "TARG v(Y) VAL=0.6 FALL=1\necho FOSSLAB_TPD $&tpd_hl")
    sch.write_text(text)
    return sch


def _tpd(res: flows.FlowResult) -> float | None:
    if not Path(res.log).is_file():
        return None
    for line in Path(res.log).read_text(errors="replace").splitlines():
        if line.startswith("FOSSLAB_TPD"):
            try:
                return float(line.split()[1])
            except (IndexError, ValueError):
                return None
    return None


def run_selftest(where: Path | None = None) -> int:
    t0 = time.time()
    tmp = Path(tempfile.mkdtemp(prefix="fosslab-selftest-", dir=where))
    ws = Workspace(tmp / "ws")
    ws.init()
    quiet = lambda _line: None  # noqa: E731
    print(f"FOSSLab self-test in {tmp}\n\nTools:")
    ok = all(_tool_versions())

    print("\nDesign database:")
    try:
        build_inverter(ws)
        ok &= _check("schematic generated", ws.view_path("work", CELL, "schematic").is_file())
        pins = [p.name for p in xschemfile.schematic_pins(ws.view_path("work", CELL, "schematic"))]
        ok &= _check("symbol from pins", ws.view_path("work", CELL, "symbol").is_file(), ", ".join(pins))
        ok &= _check("layout from IHP stdcell GDS",
                     templates.gds_top_cells(ws.view_path("work", CELL, "layout")) == [CELL])
        tb = build_testbench(ws)
        tree = hierarchy.build(ws, tb)
        found = [c for c in tree.children if c.cell == CELL]
        ok &= _check("testbench + hierarchy", bool(found) and len(found[0].children) == 2,
                     hierarchy.to_text(tree).replace("\n", " | ")[:90])
    except Exception as e:  # noqa: BLE001 - report anything as a failed check
        ok &= _check("design database", False, repr(e))
        return 1

    print("\nFlows:")
    res = flows.simulate(ws, "work", f"tb_{CELL}", echo=quiet)
    tpd = _tpd(res)
    ok &= _check("ngspice simulation", res.ok and tpd is not None,
                 f"{res.summary}; tpd = {tpd * 1e12:.1f} ps" if tpd else res.summary)
    res = flows.drc(ws, "work", CELL, echo=quiet)
    ok &= _check("DRC (IHP deck)", res.ok, res.summary)
    res = flows.lvs(ws, "work", CELL, echo=quiet)
    ok &= _check("LVS (IHP deck)", res.ok, res.summary)
    res = flows.pex(ws, "work", CELL, echo=quiet)
    ok &= _check("PEX (Magic)", res.ok, res.summary)
    res = flows.simulate(ws, "work", f"tb_{CELL}", use_extracted=[CELL], echo=quiet)
    tpd2 = _tpd(res)
    ok &= _check("post-layout simulation", res.ok and tpd2 is not None,
                 f"tpd = {tpd2 * 1e12:.1f} ps (schematic: {tpd * 1e12:.1f} ps)"
                 if tpd and tpd2 else res.summary)

    print(f"\n{'ALL PASSED' if ok else 'SOME CHECKS FAILED'} in {time.time() - t0:.0f} s")
    if ok:
        shutil.rmtree(tmp, ignore_errors=True)
    else:
        print(f"kept for inspection: {tmp}")
    return 0 if ok else 1
