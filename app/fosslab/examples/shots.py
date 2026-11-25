"""Build the tutorial's op-amp example from scratch, run every flow, and take
the tutorial's screenshots from the real programs.

Not run directly: use ``fosslab shots`` or, in the Library Manager,
Tools > Retake tutorial screenshots (see examples/capture.py), which start it
on a display of its own:

    python3 -m fosslab.examples.shots WORKDIR IMGDIR

WORKDIR gets a fresh workspace and results.json (every number the tutorial
quotes); IMGDIR the screenshots.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path

from PIL import Image

from fosslab import simenv, flows, tools
from fosslab.examples import opamp, tour
from fosslab.gui import style
from fosslab.gui.simenv_window import SimEnvWindow
from fosslab.gui.app import MainWindow
from fosslab.gui.flow_window import FlowWindow
from fosslab.gui.hierarchy_window import HierarchyWindow
from fosslab.workspace import Workspace

work = Path(sys.argv[1])
img = Path(sys.argv[2])
MARK = ".fosslab-shots"
# Start from scratch, but only ever delete a folder this script made.
if work.exists():
    if not (work / MARK).exists() and any(work.iterdir()):
        sys.exit(f"{work} exists and was not made by 'fosslab shots': choose another folder")
    shutil.rmtree(work)
work.mkdir(parents=True)
(work / MARK).write_text("made by fosslab shots: deleted at every run\n")
img.mkdir(parents=True, exist_ok=True)
for old_png in img.glob("*.png"):
    old_png.unlink()
ws = Workspace(work / "fosslab")
ws.init()
LIB = "opamp_tut"
quiet = lambda s: None  # noqa: E731
numbers: dict = {}


# --- screenshots ---------------------------------------------------------------------

def screen() -> Image.Image:
    raw = subprocess.run("xwd -root -silent", shell=True, capture_output=True).stdout
    import struct
    h = struct.unpack(">25I", raw[:100])
    hsize, w, ht, bpl, ncol = h[0], h[4], h[5], h[12], h[19]
    off = hsize + ncol * 12
    return Image.frombuffer("RGB", (w, ht), raw[off:off + bpl * ht], "raw", "BGRX", bpl, 1)


def save(im: Image.Image, name: str, max_w: int = 1200) -> None:
    if im.width > max_w:
        im = im.resize((max_w, int(im.height * max_w / im.width)), Image.LANCZOS)
    im.save(img / f"{name}.png", optimize=True)
    print("  shot", name, im.size, flush=True)


def pump(root, seconds=0.6):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)


def grab_tk(win, name: str, root) -> None:
    win.lift()
    pump(root, 0.8)
    x, y, w, h = win.winfo_rootx(), win.winfo_rooty(), win.winfo_width(), win.winfo_height()
    save(screen().crop((x, y, x + w, y + h)), name)


def x_window(title_re: str, timeout: float = 30):
    """Geometry (x, y, w, h) of the biggest top window whose title matches."""
    end = time.time() + timeout
    while time.time() < end:
        out = subprocess.run(["xwininfo", "-root", "-tree"], capture_output=True, text=True).stdout
        best = None
        for line in out.splitlines():
            m = re.search(r'"([^"]*)".*?(\d+)x(\d+)\+(-?\d+)\+(-?\d+)\s+\+(-?\d+)\+(-?\d+)', line)
            if m and re.search(title_re, m.group(1)):
                w, h, ax, ay = int(m.group(2)), int(m.group(3)), int(m.group(6)), int(m.group(7))
                if w > 300 and h > 200 and (best is None or w * h > best[2] * best[3]):
                    best = (ax, ay, w, h)
        if best:
            return best
        time.sleep(0.5)
    raise RuntimeError(f"no window {title_re}")


def grab_app(proc, title_re: str, name: str, wait: float = 4) -> None:
    time.sleep(wait)
    x, y, w, h = x_window(title_re)
    time.sleep(1.5)
    save(screen().crop((x, y, x + w, y + h)), name)
    proc.kill()
    proc.wait()


def xschem(path: Path, name: str, wait: float = 5) -> None:
    rc, env = tools.xschem_setup(ws)
    size = "wm geometry [xschem get top_path] 1400x880+0+0; after 800 {xschem zoom_full}"
    p = subprocess.Popen(["xschem", "--rcfile", str(rc), "--command", size, str(path)],
                         cwd=path.parent, env={**__import__("os").environ, **env},
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    grab_app(p, r"xschem", name, wait)


# --- build and run ---------------------------------------------------------------------

print("building the example", flush=True)
for line in opamp.build(ws, LIB):
    print(" ", line)
lib = ws.library(LIB)

print("flows", flush=True)
for tb in ("tb_opamp_ac", "tb_opamp_tran"):
    r = flows.simulate(ws, LIB, tb, echo=quiet)
    numbers[tb] = simenv.parse_results(Path(r.log).read_text())
for f in ("drc", "lvs", "pex"):
    r = flows.FLOWS[f](ws, LIB, "opamp", echo=quiet)
    numbers[f] = r.summary
    print(" ", f, r.summary, flush=True)
post = {}
for tb in ("tb_opamp_ac", "tb_opamp_tran"):
    r = flows.simulate(ws, LIB, tb, use_extracted=["opamp"], echo=quiet)
    post[tb] = simenv.parse_results(Path(r.log).read_text())
numbers["postlayout"] = post
for tb in ("tb_opamp_ac", "tb_opamp_tran"):       # back to the schematic results for the graphs
    flows.simulate(ws, LIB, tb, echo=quiet)

rs_c = simenv.run_corners(ws, LIB, "tb_opamp_ac", echo=quiet)
numbers["corners"] = {r.name: r.values for r in rs_c.results}
rs_mc = simenv.run_montecarlo(ws, LIB, "tb_opamp_ac", echo=quiet)
numbers["mc"] = {o.name: rs_mc.stats(o.name) for o in rs_mc.outputs}
numbers["mc_yield"] = rs_mc.yield_()
for f in ("hist_vos", "hist_pm", "hist_ugf", "waves"):
    shutil.copy(Path(rs_mc.run_dir) / f"{f}.png", img / f"mc_{f}.png")
for f in ("bars_pm", "bars_ugf", "bars_vos", "waves"):
    shutil.copy(Path(rs_c.run_dir) / f"{f}.png", img / f"corners_{f}.png")
rs_t = simenv.run_corners(ws, LIB, "tb_opamp_tran", echo=quiet)
numbers["corners_tran"] = {r.name: r.values for r in rs_t.results}
shutil.copy(Path(rs_t.run_dir) / "waves.png", img / "corners_tran_waves.png")

print("verilog-a", flush=True)
# the op-amp's Verilog-A view, simulated by the setup "model" of the same testbench
numbers["va_compile"] = flows.compile_va(ws, LIB, "opamp", echo=quiet).summary
va = simenv.Setup.load(ws, LIB, "tb_opamp_ac", "model")
numbers["va_nominal"] = simenv.run_nominal(ws, LIB, "tb_opamp_ac", va, echo=quiet).results[0].values
mc = numbers["mc"]
va.variables.update({
    "A0dB_mean": f"{mc['a0']['mean']:.4g}", "A0dB_sd": f"{mc['a0']['std']:.3g}",
    "GBW_mean": f"{mc['ugf']['mean']:.4g}", "GBW_sd": f"{mc['ugf']['std']:.3g}",
    "VOS_mean": f"{mc['vos']['mean'] + (0.8 - 0.6) / 10 ** (mc['a0']['mean'] / 20):.3g}",
    "VOS_sd": f"{mc['vos']['std']:.3g}"})
va.save(ws, LIB, "tb_opamp_ac")
numbers["va_vars"] = va.variables
rs_va = simenv.run_montecarlo(ws, LIB, "tb_opamp_ac", va, echo=quiet)
numbers["va_mc"] = {o.name: rs_va.stats(o.name) for o in rs_va.outputs}
for f in ("hist_vos", "hist_pm"):
    shutil.copy(Path(rs_va.run_dir) / f"{f}.png", img / f"va_mc_{f}.png")
(work / "results.json").write_text(json.dumps(numbers, indent=1, default=str))

# --- program windows ---------------------------------------------------------------------

print("screenshots", flush=True)
cd = lib.path
xschem(cd / "opamp" / "opamp.sch", "xschem_opamp")
xschem(cd / "opamp" / "opamp.sym", "xschem_opamp_symbol")
xschem(cd / "tb_opamp_ac" / "tb_opamp_ac.sch", "xschem_tb_ac", wait=7)
xschem(cd / "tb_opamp_tran" / "tb_opamp_tran.sch", "xschem_tb_tran", wait=7)
# a bigger KLayout window for the pictures, showing all hierarchy levels
big = work / "klayout_big.py"
big.write_text("import pya\nmw = pya.Application.instance().main_window()\nmw.resize(1400, 880)\n"
               "v = pya.LayoutView.current()\nv.max_hier()\nv.zoom_fit()\n")


def klayout(gds, name, extra=()):
    p = subprocess.Popen(["klayout", "-e", "-n", "sg13g2", str(gds), *extra, "-rr", str(big)],
                         cwd=gds.parent, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    grab_app(p, r"KLayout", name, wait=12)


klayout(cd / "opamp" / "opamp.gds", "klayout_opamp")
drc_db = next(Path(ws.run_dir(LIB, "opamp", "drc")).glob("*.lyrdb"))
lvs_db = next(Path(ws.run_dir(LIB, "opamp", "lvs")).glob("*.lvsdb"))
klayout(cd / "opamp" / "opamp.gds", "klayout_lvs", ("-mn", str(lvs_db)))
klayout(cd / "opamp" / "opamp.gds", "klayout_drc", ("-m", str(drc_db)))

root = tk.Tk()
style.apply(root)
root.geometry("+0+0")
win = MainWindow(root, ws)
root.geometry("1180x640+0+0")
win.reveal(LIB, "opamp")
# Getting started: the window with numbered markers, as a student sees it
ws_text = win.ws_label.cget("text")
win.ws_label.configure(text="~/fosslab")
root.lift()
pump(root, 0.8)
save(tour.grab(win, screen), "lm_tour")
win.ws_label.configure(text=ws_text)
grab_tk(root, "lm_opamp", root)
win.reveal(LIB, "tb_opamp_ac")
grab_tk(root, "lm_tb_ac", root)

h = HierarchyWindow(root, ws, cd / "tb_opamp_ac" / "tb_opamp_ac.sch")
h.geometry("980x520+0+0")
grab_tk(h, "hierarchy", root)
h.destroy()

for flow in ("drc", "lvs"):
    fw = FlowWindow(root, ws, flow, LIB, "opamp")
    fw.geometry("900x520+0+0")
    t0 = time.time()
    while fw.result is None and time.time() - t0 < 300:
        pump(root, 0.3)
    grab_tk(fw, f"flow_{flow}", root)
    fw.destroy()

a = SimEnvWindow(root, ws, LIB, "tb_opamp_ac")
a.geometry("1180x880+0+0")
for i, name in enumerate(("ade_variables", "ade_views", "ade_outputs", "ade_corners", "ade_montecarlo")):
    a.nb.select(i)
    grab_tk(a, name, root)
a.show_results(rs_c)
a.res_tree.selection_set("pm")
grab_tk(a, "ade_corners_results", root)
a.show_results(rs_mc)
a.res_tree.selection_set("vos")
grab_tk(a, "ade_mc_results", root)
a.destroy()

a = SimEnvWindow(root, ws, LIB, "tb_opamp_ac", "model")
a.geometry("1180x880+0+0")
a.nb.select(0)
grab_tk(a, "ade_va_variables", root)
a.nb.select(1)
a.view_tree.selection_set(f"{LIB}/opamp")
grab_tk(a, "ade_va_views", root)


def grab_dialog():
    from fosslab.gui.simenv_window import ViewDialog
    d = next(w for w in a.winfo_children() if isinstance(w, ViewDialog))
    d.geometry("+0+0")
    grab_tk(d, "ade_va_view_dialog", root)
    d.destroy()


root.after(1200, grab_dialog)
a.view_edit()          # modal: grab_dialog takes its picture and closes it
a.show_results(rs_va)
a.res_tree.selection_set("pm")
grab_tk(a, "ade_va_mc_results", root)
a.destroy()
root.destroy()
print("done", flush=True)
