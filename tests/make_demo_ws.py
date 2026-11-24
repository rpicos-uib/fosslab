"""Build a small workspace with a real IHP inverter + testbench (for tests and demos).

    python3 tests/make_demo_ws.py DIR
"""
import sys
from pathlib import Path

from fosslab import flows, tools
from fosslab.selftest import build_inverter, build_testbench
from fosslab.workspace import Workspace

ws = Workspace(Path(sys.argv[1]))
ws.init()
build_inverter(ws)
build_testbench(ws)
tools.xschem_setup(ws)
quiet = lambda _l: None
for f in ("drc", "lvs", "pex"):
    print(f, flows.FLOWS[f](ws, "work", "inv", echo=quiet).summary)
print("sim", flows.simulate(ws, "work", "tb_inv", echo=quiet).summary)
print("workspace:", ws.root)
