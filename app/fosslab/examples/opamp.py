"""The tutorial's worked example: a two-stage Miller op-amp in IHP SG13G2.

    fosslab example opamp [--lib opamp_tut]

writes the reference library: the op-amp (schematic, symbol, layout), its
testbenches with their Simulation Environment setups (variables, outputs
and specifications, corners, Monte Carlo), and the op-amp's Verilog-A view
with the setup "model" of tb_opamp_ac that simulates it. The tutorial's
numbers and screenshots come from it.

Sizing (Allen & Holberg first-cut procedure, refined by simulation, VDD = 1.2 V,
CL = 1 pF, IBIAS = 10 uA):

    M1, M2  input pair     sg13_lv_nmos  W = 8 um (4 x 2 um)   L = 1 um
    M3, M4  current mirror sg13_lv_pmos  W = 8 um (4 x 2 um)   L = 1 um
    M5      tail           sg13_lv_nmos  W = 4 um (2 x 2 um)   L = 2 um
    M8      bias diode     sg13_lv_nmos  W = 4 um (2 x 2 um)   L = 2 um
    M6      2nd stage      sg13_lv_pmos  W = 80 um (40 x 2 um) L = 1 um
    M7      2nd-stage sink sg13_lv_nmos  W = 20 um (10 x 2 um) L = 2 um
    Cc      Miller cap     cap_cmim      24 um x 24 um

(W/L)6 / (W/L)4 = 2 (W/L)7 / (W/L)5 = 10 keeps M6's gate at M4's gate
voltage, cancelling the systematic offset to first order.
"""

from __future__ import annotations

from pathlib import Path

from .. import hierarchy, views, xschemfile
from ..simenv import Corner, MonteCarlo, Output, Setup
from ..workspace import Workspace

HERE = Path(__file__).resolve().parent

MOS = {  # name: (type, W um, L um, fingers)
    "M1": ("n", 8, 1, 4), "M2": ("n", 8, 1, 4),
    "M3": ("p", 8, 1, 4), "M4": ("p", 8, 1, 4),
    "M5": ("n", 4, 2, 2), "M8": ("n", 4, 2, 2),
    "M6": ("p", 80, 1, 40), "M7": ("n", 20, 2, 10),
}
CC_SIDE = 24.0   # um

# Pins of the op-amp, in the order of its subcircuit and symbol.
PINS = ["INP", "INN", "OUT", "IBIAS", "VDD", "VSS"]


# --- symbol: the usual op-amp triangle --------------------------------------------

def opamp_symbol() -> str:
    k = 'K {type=subcircuit\nformat="@name @pinlist @symname"\ntemplate="name=x1"\n}'
    return "\n".join([
        xschemfile.XSCHEM_VERSION_LINE, "G {}", k, "V {}", "S {}", "E {}",
        "L 4 -60 -80 -60 80 {}", "L 4 -60 -80 80 0 {}", "L 4 -60 80 80 0 {}",
        # INP (+) and INN (-) on the left, OUT on the right
        "L 4 -80 40 -60 40 {}", "B 5 -82.5 37.5 -77.5 42.5 {name=INP dir=in}",
        "L 4 -80 -40 -60 -40 {}", "B 5 -82.5 -42.5 -77.5 -37.5 {name=INN dir=in}",
        "L 4 80 0 100 0 {}", "B 5 97.5 -2.5 102.5 2.5 {name=OUT dir=out}",
        # IBIAS below, supplies on top and bottom
        "L 4 20 34 20 80 {}", "B 5 17.5 77.5 22.5 82.5 {name=IBIAS dir=in}",
        "L 4 -20 -80 -20 -57 {}", "B 5 -22.5 -82.5 -17.5 -77.5 {name=VDD dir=inout}",
        "L 4 -20 57 -20 80 {}", "B 5 -22.5 77.5 -17.5 82.5 {name=VSS dir=inout}",
        "T {+} -55 25 0 0 0.3 0.3 {}", "T {-} -53 -55 0 0 0.3 0.3 {}",
        "T {INP} -78 46 0 0 0.15 0.15 {}", "T {INN} -78 -55 0 0 0.15 0.15 {}",
        "T {OUT} 82 -14 0 0 0.15 0.15 {}", "T {IBIAS} 24 66 0 0 0.15 0.15 {}",
        "T {VDD} -16 -82 0 0 0.15 0.15 {}", "T {VSS} -16 70 0 0 0.15 0.15 {}",
        "T {@symname} -40 -8 0 0 0.2 0.2 {}", "T {@name} 30 -50 0 0 0.2 0.2 {}",
    ]) + "\n"


# --- schematic of the op-amp ---------------------------------------------------------

def opamp_schematic(paths) -> str:
    b = xschemfile.SchematicBuilder(lambda ref: hierarchy.resolve_symbol(ref, paths))

    def mos(name: str, x: int, y: int, d: str, g: str, s: str) -> None:
        t, w, l, ng = MOS[name]
        model = "sg13_lv_nmos" if t == "n" else "sg13_lv_pmos"
        b.device(f"sg13g2_pr/{model}.sym", x, y,
                 {"name": name, "l": f"{l}u", "w": f"{w}u", "ng": str(ng), "m": "1",
                  "model": model, "spiceprefix": "X"},
                 {"D": d, "G": g, "S": s, "B": "VDD" if t == "p" else "VSS"})

    # first stage: mirror load on top, input pair, tail
    mos("M3", 300, -700, "n1", "n1", "VDD")
    mos("M4", 600, -700, "out1", "n1", "VDD")
    mos("M1", 300, -500, "n1", "INN", "tail")
    mos("M2", 600, -500, "out1", "INP", "tail")
    mos("M5", 450, -300, "tail", "IBIAS", "VSS")
    # bias diode, second stage
    mos("M8", 100, -300, "IBIAS", "IBIAS", "VSS")
    mos("M6", 1000, -700, "OUT", "out1", "VDD")
    mos("M7", 1000, -300, "OUT", "IBIAS", "VSS")
    b.device("sg13g2_pr/cap_cmim.sym", 800, -550,
             {"name": "C1", "model": "cap_cmim", "w": f"{CC_SIDE:.1f}e-6", "l": f"{CC_SIDE:.1f}e-6",
              "m": "1", "spiceprefix": "X"}, {"c0": "out1", "c1": "OUT"})
    for i, (kind, net) in enumerate((("ipin", "INP"), ("ipin", "INN"), ("ipin", "IBIAS"))):
        b.pin(kind, -100, -700 + 80 * i, net)
    b.pin("opin", 1250, -500, "OUT")
    b.pin("iopin", -100, -400, "VDD")
    b.pin("iopin", -100, -320, "VSS")
    b.lines.append('T {Two-stage Miller op-amp, IHP SG13G2 (FOSSLab tutorial)} 100 -860 0 0 0.5 0.5 {}')
    b.lines.append('T {Nets are connected by name: every label with the same name is the same wire.} '
                   '100 -820 0 0 0.3 0.3 {}')
    return b.text()


# --- testbenches ------------------------------------------------------------------------

MODELS = ".lib cornerMOSlv.lib mos_tt\n.lib cornerCAP.lib cap_typ\n"

AC_CONTROL = """
.param vdd=1.2 vcm=0.8 ibias=10u cl=1p
.param temp=27
.control
save all
op
let vos = v(out) - v(inp)
let pdiss = -v(vdd) * i(vvdd)
print vos
print pdiss
write {tb}.raw
set appendwrite
ac dec 50 1 10G
let gain = vdb(out)
let phase = 180/PI*cph(out)
meas ac a0 find gain at=10
meas ac ugf when gain=0
meas ac phu find phase when gain=0
let pm = phu + 180
print pm
write {tb}.raw
.endc
"""

TRAN_CONTROL = """
.param vdd=1.2 vlow=0.7 vhigh=1.0 ibias=10u cl=1p
.param temp=27
.control
save all
tran 1n 4u
meas tran t20r when v(out)=0.76 rise=1
meas tran t80r when v(out)=0.94 rise=1
meas tran t80f when v(out)=0.94 fall=1
meas tran t20f when v(out)=0.76 fall=1
let srp = 0.18/(t80r-t20r)
let srn = 0.18/(t20f-t80f)
print srp
print srn
* settling: last time the output enters a +-1 mV band around its final value
meas tran vfin find v(out) at=1.95u
let vband = vfin - 1m
meas tran tset_r when v(out)=$&vband cross=last from=1u to=1.95u
let tsettle = tset_r - 1u
print tsettle
write {tb}.raw
.endc
"""


def _graph(x: int, y: int, w: int, h: int, props: dict[str, str]) -> str:
    body = "\n".join(f"{k}={v}" for k, v in props.items())
    return f"B 2 {x} {y} {x + w} {y + h} {{flags=graph\n{body}}}"


def tb_ac_schematic(paths, dut: str, tb: str, control: str = AC_CONTROL, models: str = MODELS,
                    title: str = "") -> str:
    b = xschemfile.SchematicBuilder(lambda ref: hierarchy.resolve_symbol(ref, paths))
    b.device(dut, 600, -350, {"name": "x1"},
             {"INP": "inp", "INN": "inn", "OUT": "out", "IBIAS": "ib", "VDD": "vdd", "VSS": "GND"})
    b.device("devices/vsource.sym", 100, -350, {"name": "VVDD", "value": "{vdd}"}, {"p": "vdd", "m": "GND"})
    b.device("devices/isource.sym", 250, -350, {"name": "IB", "value": "{ibias}"}, {"p": "vdd", "m": "ib"})
    b.device("devices/vsource.sym", 400, -200, {"name": "VIN", "value": "dc {vcm} ac 1"},
             {"p": "inp", "m": "GND"})
    b.device("devices/capa.sym", 850, -250, {"name": "CL", "value": "{cl}", "m": "1"}, {"p": "out", "m": "GND"})
    b.device("devices/res.sym", 750, -550, {"name": "RFB", "value": "1G", "m": "1"}, {"P": "out", "M": "inn"})
    b.device("devices/capa.sym", 400, -550, {"name": "CFB", "value": "1", "m": "1"}, {"p": "inn", "m": "GND"})
    b.code(0, 0, "MODELS", models, models=True)
    # the model card makes the MODELS block wide: keep the control block clear of it
    b.code(300, 0, "NGSPICE", control.replace("{tb}", tb))
    b.lines.append(f"T {{{title or 'Open-loop AC: RFB-CFB close the loop for DC only'}}} 100 -700 0 0 0.4 0.4 {{}}")
    b.lines.append(_graph(1000, -700, 600, 300, {
        "y1": "-20", "y2": "70", "divy": "9", "subdivy": "1", "x1": "0", "x2": "10", "divx": "10",
        "subdivx": "8", "logx": "1", "node": '"gain;out db20()"', "color": "4",
        "dataset": "-1", "unitx": "1", "sim_type": "ac", "autoload": "1",
        "rawfile": f"[fosslab_simdir]/{tb}.raw"}))
    b.lines.append(_graph(1000, -380, 600, 300, {
        # xschem keeps the magnitude of AC vectors: the phase (always negative
        # here, 0 to -312 deg) is drawn as -|phase|
        "y1": "-360", "y2": "0", "divy": "8", "subdivy": "1", "x1": "0", "x2": "10", "divx": "10",
        "subdivx": "8", "logx": "1", "node": '"phase (deg);phase -1 *"', "color": "7",
        "dataset": "-1", "unitx": "1", "sim_type": "ac", "autoload": "1",
        "rawfile": f"[fosslab_simdir]/{tb}.raw"}))
    return b.text()


def tb_tran_schematic(paths, tb: str) -> str:
    b = xschemfile.SchematicBuilder(lambda ref: hierarchy.resolve_symbol(ref, paths))
    b.device("opamp_tut/opamp/opamp.sym", 600, -350, {"name": "x1"},
             {"INP": "inp", "INN": "out", "OUT": "out", "IBIAS": "ib", "VDD": "vdd", "VSS": "GND"})
    b.device("devices/vsource.sym", 100, -350, {"name": "VVDD", "value": "{vdd}"}, {"p": "vdd", "m": "GND"})
    b.device("devices/isource.sym", 250, -350, {"name": "IB", "value": "{ibias}"}, {"p": "vdd", "m": "ib"})
    b.device("devices/vsource.sym", 400, -200,
             {"name": "VIN", "value": "pulse({vlow} {vhigh} 1u 1n 1n 1u 2u)"}, {"p": "inp", "m": "GND"})
    b.device("devices/capa.sym", 850, -250, {"name": "CL", "value": "{cl}", "m": "1"}, {"p": "out", "m": "GND"})
    b.code(0, 0, "MODELS", MODELS, models=True)
    b.code(300, 0, "NGSPICE", TRAN_CONTROL.replace("{tb}", tb))
    b.lines.append("T {Unity-gain follower: slew rate and settling} 100 -700 0 0 0.4 0.4 {}")
    b.lines.append(_graph(1000, -700, 700, 380, {
        "y1": "0.6", "y2": "1.1", "divy": "5", "subdivy": "1", "x1": "0", "x2": "4e-6", "divx": "8",
        "subdivx": "1", "node": '"inp\nout"', "color": "4 7", "dataset": "-1", "unitx": "1",
        "sim_type": "tran", "autoload": "1", "rawfile": f"[fosslab_simdir]/{tb}.raw"}))
    return b.text()


# --- Verilog-A model: a view of cell opamp ---------------------------------------------

def va_source(two_poles: bool = False) -> str:
    return (HERE / ("opamp_2pole.va" if two_poles else "opamp.va")).read_text()


# The model's parameters in the setup "model" of tb_opamp_ac (tab Views): each
# one drawn from a Gaussian whose mean and sigma are design variables, so a
# Monte Carlo run draws a new op-amp each time (sigma 0: always the mean).
VA_PARAMS = {"A0dB": "agauss(A0dB_mean, A0dB_sd, 1)", "GBW": "agauss(GBW_mean, GBW_sd, 1)",
             "VOS": "agauss(VOS_mean, VOS_sd, 1)", "SR": "10.6e6"}


# --- the Simulation Environment setups ----------------------------------------------------

def ac_setup() -> Setup:
    return Setup(
        variables={"vdd": "1.2", "vcm": "0.8", "ibias": "10u", "cl": "1p"},
        outputs=[
            Output("a0", "DC gain", 55, None, 1.0, "dB"),
            Output("ugf", "Unity-gain frequency", 15, None, 1e-6, "MHz"),
            Output("pm", "Phase margin", 55, None, 1.0, "deg"),
            Output("vos", "Output offset (follower)", -5, 5, 1e3, "mV"),
            Output("pdiss", "Power", None, 100, 1e6, "uW"),
            # defined here, not in the testbench: the tool adds it to the netlist
            Output("g1m", "Gain at 1 MHz", 20, None, 1.0, "dB", "meas ac g1m find vdb(out) at=1e6"),
        ],
        wave="vdb(out)", wave_logx=True,
        corners=[Corner(f"{m[4:]}_{t:g}C", True, m, {"mos_ff": "cap_bcs", "mos_ss": "cap_wcs"}.get(m, "cap_typ"),
                        "res_typ", t)
                 for m in ("mos_tt", "mos_ss", "mos_ff", "mos_sf", "mos_fs") for t in (-40, 27, 125)],
        montecarlo=MonteCarlo(runs=200, variation="mismatch", seed=1, jobs=8),
    )


def tran_setup() -> Setup:
    return Setup(
        variables={"vdd": "1.2", "vlow": "0.7", "vhigh": "1.0", "ibias": "10u", "cl": "1p"},
        outputs=[
            Output("srp", "Slew rate, rising", 10, None, 1e-6, "V/us"),
            Output("srn", "Slew rate, falling", 10, None, 1e-6, "V/us"),
            Output("tsettle", "Settling to 1 mV", None, 0.25, 1e6, "us"),
        ],
        wave="v(out)",
        corners=[Corner(f"{m[4:]}_27C", True, m, "cap_typ", "res_typ", 27)
                 for m in ("mos_tt", "mos_ss", "mos_ff", "mos_sf", "mos_fs")],
        montecarlo=MonteCarlo(runs=100, variation="mismatch", seed=1, jobs=8),
    )


def va_setup(lib: str = "opamp_tut") -> Setup:
    """Setup "model" of tb_opamp_ac: the same testbench, with the op-amp's Verilog-A view."""

    s = ac_setup()
    s.outputs = [o for o in s.outputs if o.name not in ("pdiss", "g1m")]
    s.variables = {"vdd": "1.2", "vcm": "0.8", "ibias": "10u", "cl": "1p",
                   "A0dB_mean": "57.6", "A0dB_sd": "0", "GBW_mean": "16.2e6", "GBW_sd": "0",
                   "VOS_mean": "1.98e-3", "VOS_sd": "0"}
    s.corners = []
    s.montecarlo = MonteCarlo(runs=200, variation="mismatch", seed=1, jobs=8)
    s.set_binding(views.key(lib, "opamp"), views.Binding(views.VERILOGA, dict(VA_PARAMS)))
    return s


# --- building the library ----------------------------------------------------------------

def build(ws: Workspace, lib: str = "opamp_tut", with_layout: bool = True) -> list[str]:
    """Create (or refresh) the reference library in ``ws``. Returns what it did."""

    done = []
    if lib not in [l.name for l in ws.libraries()]:
        ws.add_library(lib)
        done.append(f"library {lib}")
    library = ws.library(lib)
    paths = hierarchy.search_path(ws)

    def cell(name: str) -> Path:
        d = library.path / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    d = cell("opamp")
    (d / "opamp.sch").write_text(opamp_schematic(paths))
    (d / "opamp.sym").write_text(opamp_symbol())
    (d / "opamp.md").write_text(__doc__ or "")
    done.append("opamp: schematic, symbol")

    paths = hierarchy.search_path(ws)   # the new symbol is now findable
    d = cell("tb_opamp_ac")
    (d / "tb_opamp_ac.sch").write_text(tb_ac_schematic(paths, f"{lib}/opamp/opamp.sym", "tb_opamp_ac"))
    ac_setup().save(ws, lib, "tb_opamp_ac")
    d = cell("tb_opamp_tran")
    (d / "tb_opamp_tran.sch").write_text(tb_tran_schematic(paths, "tb_opamp_tran").replace(
        "opamp_tut/opamp/opamp.sym", f"{lib}/opamp/opamp.sym"))
    tran_setup().save(ws, lib, "tb_opamp_tran")
    done.append("testbenches tb_opamp_ac, tb_opamp_tran (with corners and Monte Carlo setups)")

    (library.path / "opamp" / "opamp.va").write_text(va_source())
    va_setup(lib).save(ws, lib, "tb_opamp_ac", "model")
    done.append("opamp: Verilog-A view; tb_opamp_ac: setup 'model' that simulates it")

    if with_layout:
        from . import opamp_layout
        gds = library.path / "opamp" / "opamp.gds"
        opamp_layout.build(gds)
        done.append("opamp layout")
    return done


def write_solution(ws: Workspace, lib: str = "opamp_tut") -> Path:
    """The exercise's solution, for teachers: the two-pole model, a second
    Verilog-A view of cell opamp, and the setup "model_2pole" of tb_opamp_ac
    that simulates it (what the students are asked to build)."""

    library = ws.library(lib)
    va = library.path / "opamp" / "opamp_2pole.va"
    va.write_text(va_source(two_poles=True))
    s = va_setup(lib)
    # calibrated on the transistor-level Monte Carlo (chapter "Monte Carlo with the model"):
    # UGF 16.17 MHz, PM 60.38 deg -> fp2 = UGF/tan(90-PM), GBW = UGF*sqrt(1+(UGF/fp2)^2)
    s.variables.update({"A0dB_mean": "57.61", "A0dB_sd": "0.031", "GBW_mean": "18.60e6", "GBW_sd": "0.262e6",
                        "VOS_mean": "1.98e-3", "VOS_sd": "2.14e-3", "FP2_mean": "28.44e6", "FP2_sd": "0"})
    s.set_binding(views.key(lib, "opamp"), views.Binding(
        f"{views.VERILOGA}:opamp_2pole", {**VA_PARAMS, "FP2": "agauss(FP2_mean, FP2_sd, 1)"}))
    s.save(ws, lib, "tb_opamp_ac", "model_2pole")
    return va
