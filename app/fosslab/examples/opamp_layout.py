"""Layout of the tutorial op-amp, drawn with IHP's PCells (SG13_dev library).

Run by KLayout, which provides the PCells:

    klayout -zz -n sg13g2 -r opamp_layout.py -rd out=opamp.gds

or from Python: ``opamp_layout.build(Path("opamp.gds"))`` (starts KLayout).

The placement is deliberately simple and regular, so that it is easy to
read and to modify (see the tutorial's layout chapter):

  * one transistor per row, stacked: bias and sinks (M8, M5, M7), the
    input pair (M1, M2), the PMOS mirror (M3, M4) and M6 on top;
  * each transistor gets three terminal bars: source on Metal1 under the
    fingers, gate on a contacted poly strap above them, drain on Metal2
    across them;
  * every terminal runs to the right on Metal2 to a routing channel of
    vertical Metal3 trunks, one per net, with a Via2 where it belongs;
  * the Miller capacitor (MIM, Metal5 / TopMetal1) sits right of the
    channel and joins the trunks on Metal4;
  * under every NMOS row a substrate-tap strip (ptap1) to VSS, under every
    PMOS row a well-tap strip (ntap1) to VDD inside its N-well;
  * the pins are Metal3 labels on the trunks of INP, INN, OUT, IBIAS, VDD, VSS.

Change the device sizes in examples/opamp.py (MOS, CC_SIDE): this file
reads them from there.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Layers (sg13g2.lyp): (layer, datatype)
L = {
    "Activ": (1, 0), "GatPoly": (5, 0), "Cont": (6, 0), "Metal1": (8, 0), "Via1": (19, 0),
    "Metal2": (10, 0), "Via2": (29, 0), "Metal3": (30, 0), "Metal3.pin": (30, 2),
    "Metal3.text": (30, 25), "Via3": (49, 0), "Metal4": (50, 0), "Via4": (66, 0), "Metal5": (67, 0),
    "TopVia1": (125, 0), "TopMetal1": (126, 0), "NWell": (31, 0),
}

NETS = ["VDD", "VSS", "IBIAS", "INP", "INN", "tail", "n1", "out1", "OUT"]
PINS = ["INP", "INN", "OUT", "IBIAS", "VDD", "VSS"]

# rows, bottom to top: (device, D, G, S, tap net)
ROWS = [
    ("M8", "IBIAS", "IBIAS", "VSS"),
    ("M5", "tail", "IBIAS", "VSS"),
    ("M7", "OUT", "IBIAS", "VSS"),
    ("M1", "n1", "INN", "tail"),
    ("M2", "out1", "INP", "tail"),
    ("M3", "n1", "n1", "VDD"),
    ("M4", "out1", "n1", "VDD"),
    ("M6", "OUT", "out1", "VDD"),
]

# geometry (nm)
VIA = 190            # Via1..Via4 size
PAD = 400            # metal pad around a single via (enclosure 105)
STUB_W = 400         # Metal2 stubs
TRUNK_W = 400        # Metal3 trunks
TRUNK_PITCH = 1000
ROW_GAP = 1600


def build(gds: Path) -> Path:
    """Generate the layout with KLayout (which provides IHP's PCells)."""

    gds = Path(gds)
    cmd = ["klayout", "-zz", "-n", "sg13g2", "-r", str(Path(__file__).resolve()), "-rd", f"out={gds}"]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0 or not gds.is_file():
        raise RuntimeError(f"layout generation failed:\n{p.stdout[-2000:]}\n{p.stderr[-2000:]}")
    return gds


def _generate(out: str) -> None:
    import pya

    sys.path.insert(0, str(HERE.parent.parent))
    from fosslab.examples.opamp import CC_SIDE, MOS

    lib = pya.Library.library_by_name("SG13_dev", "sg13g2")
    ly = pya.Layout()
    ly.dbu = 0.001
    ly.technology_name = "sg13g2"
    top = ly.create_cell("opamp")
    li = {k: ly.layer(*v) for k, v in L.items()}

    def box(layer, x1, y1, x2, y2):
        top.shapes(li[layer]).insert(pya.Box(int(min(x1, x2)), int(min(y1, y2)), int(max(x1, x2)), int(max(y1, y2))))

    def pcell(name, params, x, y):
        cid = ly.add_pcell_variant(lib, lib.layout().pcell_id(name), params)
        top.insert(pya.CellInstArray(cid, pya.Trans(int(x), int(y))))
        return ly.cell(cid)

    def shapes_of(cell, layer):
        idx = ly.find_layer(*L[layer])
        if idx is None:
            return []
        return sorted((it.shape().bbox().transformed(it.trans()) for it in cell.begin_shapes_rec(idx)
                       if not it.shape().is_text()), key=lambda b: (b.left, b.bottom))

    def via(kind, x, y, lower, upper):
        """A single via centred at (x, y) with square pads on both metals."""
        h = VIA // 2
        box(kind, x - h, y - h, x + h, y + h)
        p = PAD // 2
        box(lower, x - p, y - p, x + p, y + p)
        box(upper, x - p, y - p, x + p, y + p)

    stubs = {n: [] for n in NETS}     # net -> list of (y, x_start) Metal2 stubs to the channel
    m4_stubs = {n: [] for n in NETS}  # net -> list of (y, x_end) Metal4 stubs from the capacitor
    right_edge = 0
    y = 0
    rows = []

    for name, d_net, g_net, s_net in ROWS:
        kind, w, l_, ng = MOS[name]
        model = "nmos" if kind == "n" else "pmos"
        x0 = 3000
        cell = pcell(model, {"w": f"{w}u", "l": f"{l_}u", "ng": str(ng)}, x0, y)
        m1 = [b for b in shapes_of(cell, "Metal1")]
        # S/D strips: unique Metal1 boxes (the PCell has duplicates), left to right
        strips = []
        for b in m1:
            b = b.moved(x0, y)
            if not strips or strips[-1].left != b.left:
                strips.append(b)
        gates = [b.moved(x0, y) for b in shapes_of(cell, "GatPoly")]
        gates = [g for i, g in enumerate(gates) if i == 0 or g.left != gates[i - 1].left]
        wf = strips[0].height()                 # finger width
        sources = strips[0::2]
        drains = strips[1::2]
        dev_right = max(b.right for b in strips) + 400
        rows.append((name, y, wf, dev_right))

        # source: strips down to a Metal1 bar under the device
        sb_y1, sb_y2 = y - 600, y - 340
        for s in sources:
            box("Metal1", s.left, sb_y2, s.right, s.bottom)
        box("Metal1", sources[0].left, sb_y1, dev_right + 600, sb_y2)
        via("Via1", dev_right + 400, (sb_y1 + sb_y2) // 2, "Metal1", "Metal2")
        stubs[s_net].append(((sb_y1 + sb_y2) // 2, dev_right + 200))

        # gate: poly strap over the gate ends, contacts, Metal1 bar
        gy1, gy2 = y + wf + 180, y + wf + 640
        box("GatPoly", gates[0].left, gy1, gates[-1].right, gy2)
        cy = y + wf + 390
        xc = gates[0].left + 90
        while xc + 160 <= gates[-1].right - 90:
            box("Cont", xc, cy, xc + 160, cy + 160)
            xc += 340
        box("Metal1", gates[0].left + 40, y + wf + 340, dev_right + 600, y + wf + 600)
        gyc = y + wf + 470
        via("Via1", dev_right + 400, gyc, "Metal1", "Metal2")
        stubs[g_net].append((gyc, dev_right + 200))

        # drain: Via1 on each drain strip, Metal2 bar across
        dyc = y + wf // 2
        for dbox in drains:
            cx = (dbox.left + dbox.right) // 2
            via("Via1", cx, dyc, "Metal1", "Metal2")
        box("Metal2", drains[0].left - 120, dyc - STUB_W // 2, dev_right + 200, dyc + STUB_W // 2)
        stubs[d_net].append((dyc, dev_right + 200))

        # bulk taps: a strip under the whole row (latch-up rule: no transistor
        # farther than 20 um from a tap), between y-1800 and y-800
        tap_w = (dev_right - 400 - x0) / 1000
        if kind == "n":
            pcell("ptap1", {"w": f"{tap_w:.2f}u", "l": "1u"}, x0, y - 1800)
            ty = y - 1300
            box("Metal1", dev_right - 1200, ty - 200, dev_right + 600, ty + 200)  # overlaps the strip
            via("Via1", dev_right + 400, ty, "Metal1", "Metal2")
            stubs["VSS"].append((ty, dev_right + 200))
        else:
            pcell("ntap1", {"w": f"{tap_w:.2f}u", "l": "1u"}, x0, y - 1800)
            # the well tap is VDD, like the PMOS sources: join it to the source bar
            box("Metal1", x0 + 80, y - 900, x0 + 600, sb_y2)
            box("NWell", x0 - 400, y - 2100, dev_right - 90, y + wf + 310)
        right_edge = max(right_edge, dev_right + 800)
        y = y + wf + 640 + ROW_GAP + 1800
        if name == "M2":
            y += 1500   # NMOS to PMOS: room for the N-well spacing rules

    # --- routing channel: one vertical Metal3 trunk per net -------------------------------
    x_trunk = {n: right_edge + 1500 + i * TRUNK_PITCH for i, n in enumerate(NETS)}
    chan_right = max(x_trunk.values()) + 1500

    # --- Miller capacitor right of the channel ------------------------------------------------
    side = int(CC_SIDE * 1000)
    cx0, cy0 = chan_right + 3000, 4000
    pcell("cmim", {"Calculate": "C", "w": f"{CC_SIDE}u", "l": f"{CC_SIDE}u"}, cx0, cy0)
    mid = cx0 + side // 2
    # bottom plate (Metal5) tab downwards -> Via4 -> Metal4 stub left to the channel
    box("Metal5", mid - 1000, cy0 - 3200, mid + 1000, cy0 - 600)
    by = cy0 - 2700
    via("Via4", mid, by, "Metal4", "Metal5")
    m4_stubs["OUT"].append((by, mid))
    # top plate (TopMetal1) tab upwards -> TopVia1 -> Metal5 island -> Via4 -> Metal4
    ty1 = cy0 + side + 600 + 1500          # island 1.5 um above the bottom plate edge
    box("TopMetal1", mid - 1000, cy0 + side - 30, mid + 1000, ty1 + 2000)
    box("Metal5", mid - 1000, ty1, mid + 1000, ty1 + 2000)
    tv = 210
    box("TopVia1", mid - tv, ty1 + 1000 - tv, mid + tv, ty1 + 1000 + tv)
    via("Via4", mid - 600, ty1 + 400, "Metal4", "Metal5")
    m4_stubs["out1"].append((ty1 + 400, mid - 600))

    # Metal4 stubs to their trunk, Via3 down to Metal3
    for net, items in m4_stubs.items():
        for sy, sx in items:
            x = x_trunk[net]
            box("Metal4", x - PAD // 2, sy - STUB_W // 2, sx + PAD // 2, sy + STUB_W // 2)
            via("Via3", x, sy, "Metal3", "Metal4")

    # Metal2 stubs to their trunk, Via2 up to Metal3; then the trunks
    for net in NETS:
        ys = [sy for sy, _ in stubs[net]] + [sy for sy, _ in m4_stubs[net]]
        if not ys:
            continue
        x = x_trunk[net]
        for sy, sx in stubs[net]:
            box("Metal2", sx, sy - STUB_W // 2, x + PAD // 2, sy + STUB_W // 2)
            via("Via2", x, sy, "Metal2", "Metal3")
        y1, y2 = min(ys) - PAD // 2, max(ys) + PAD // 2
        if net in PINS:
            y2 = max(y2, y1 + 3000)
        box("Metal3", x - TRUNK_W // 2, y1, x + TRUNK_W // 2, y2)
        if net in PINS:
            # pin: Metal3.pin shape and a Metal3 text label with the net name
            top.shapes(li["Metal3.pin"]).insert(pya.Box(x - TRUNK_W // 2, y2 - 1000, x + TRUNK_W // 2, y2))
            top.shapes(li["Metal3.text"]).insert(pya.Text(net, pya.Trans(x, y2 - 500)))

    ly.write(out)
    print(f"written {out}: {top.bbox()}")


if __name__ == "__main__" and "out" in globals():
    _generate(globals()["out"])
