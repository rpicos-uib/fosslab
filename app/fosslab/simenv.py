"""Simulation environment: design variables, outputs with specs, corners and
Monte Carlo for a testbench.

The setup of each testbench is kept next to it, in ``<tb>.simenv.json``, and
edited from the Simulation Environment window (gui/simenv_window.py):

    {
      "variables": {"vdd": "1.2", "vcm": "0.8"},          # design variables
      "outputs": [                                         # what to collect
        {"name": "a0",  "label": "DC gain (dB)", "min": 55, "max": null},
        ...],
      "corners": [                                         # one row per corner
        {"name": "tt_27", "enabled": true, "mos": "mos_tt", "cap": "cap_typ",
         "res": "res_typ", "temp": 27, "vars": {"vdd": "1.2"}},
        ...],
      "montecarlo": {"runs": 200, "variation": "mismatch", "seed": 1, "jobs": 4},
      "views": {"opamp_tut/opamp": {"view": "veriloga",     # which view of each
                "params": {"A0dB": "agauss(A0dB_mean, A0dB_sd, 1)"}}}   # cell (views.py)
    }

A testbench can have several named setups (like saved states): the default one
in ``<tb>.simenv.json`` and others in ``<tb>.<name>.simenv.json``, e.g. the
same testbench with the op-amp's transistors and with its Verilog-A model.

How a run works: the testbench is netlisted once with xschem; then, for every
job (a corner or a Monte Carlo sample) the netlist is copied with
  * the IHP model sections replaced (.lib cornerMOSlv.lib mos_tt -> mos_ss, ...),
  * every ``.param <variable>=`` line set to the job's value,
  * the temperature set (.option temp / .param temp),
  * for Monte Carlo, ``.option seed=<n>`` so each run draws new random values,
and ngspice runs it. Every ``name = value`` that ngspice prints (``meas`` and
``print``) is collected; the outputs listed in the setup are shown and
checked against their limits.
"""

from __future__ import annotations

import csv
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from . import flows, views
from .workspace import Workspace

Echo = Callable[[str], None]

MOS_SECTIONS = ["mos_tt", "mos_ss", "mos_ff", "mos_sf", "mos_fs"]
CAP_SECTIONS = ["cap_typ", "cap_bcs", "cap_wcs"]
RES_SECTIONS = ["res_typ", "res_bcs", "res_wcs"]
VARIATIONS = {
    # what Monte Carlo varies -> how each model section is renamed
    "mismatch": "{section}_mismatch",   # device-to-device (local): offset, matching
    "process": "{section}_stat",        # wafer-to-wafer (global): Vth, mobility, Cox...
}


@dataclass
class Output:
    name: str
    label: str = ""
    min: float | None = None
    max: float | None = None
    scale: float = 1.0           # shown value = raw * scale (e.g. 1e-6 for MHz)
    unit: str = ""
    # How to compute it, in ngspice's language, if the testbench does not:
    # a 'meas' statement ("meas ac f1m find vdb(out) at=1e6") or an
    # expression ("vdb(out)[0]", stored with 'let'). Empty: the testbench
    # itself prints <name> (with meas or print).
    expr: str = ""

    def control_lines(self) -> list[str]:
        e = self.expr.strip()
        if not e:
            return []
        if e.lower().startswith("meas"):
            return [e]
        return [f"let {self.name} = {e}", f"print {self.name}"]

    def show(self, raw: float | None) -> float | None:
        return None if raw is None else raw * self.scale

    def passes(self, raw: float | None) -> bool | None:
        if raw is None:
            return None
        v = self.show(raw)
        if self.min is not None and v < self.min:
            return False
        if self.max is not None and v > self.max:
            return False
        return True


@dataclass
class Corner:
    name: str
    enabled: bool = True
    mos: str = "mos_tt"
    cap: str = "cap_typ"
    res: str = "res_typ"
    temp: float = 27.0
    vars: dict[str, str] = field(default_factory=dict)


@dataclass
class MonteCarlo:
    runs: int = 100
    variation: str = "mismatch"
    seed: int = 1
    jobs: int = 4


@dataclass
class Setup:
    variables: dict[str, str] = field(default_factory=dict)
    outputs: list[Output] = field(default_factory=list)
    corners: list[Corner] = field(default_factory=list)
    montecarlo: MonteCarlo = field(default_factory=MonteCarlo)
    schematic: str = ""          # which schematic of the cell (default <cell>.sch)
    # A waveform saved from every run and drawn on top of each other
    # (corners: one curve per corner; Monte Carlo: the family of curves),
    # e.g. "vdb(out)" after an ac analysis. Empty: none.
    wave: str = ""
    wave_logx: bool = False
    # which view of each cell to simulate: {"lib/cell": {"view": ..., "params": {...}}}
    views: dict[str, dict] = field(default_factory=dict)
    name: str = ""               # "" = the default setup (not saved in the file)

    @staticmethod
    def path(ws: Workspace, lib: str, cell: str, name: str = "") -> Path:
        return ws.cell_dir(lib, cell) / (f"{cell}.{name}.simenv.json" if name else f"{cell}.simenv.json")

    @staticmethod
    def names(ws: Workspace, lib: str, cell: str) -> list[str]:
        """The testbench's setups: "" (the default) and the named ones."""

        d = ws.cell_dir(lib, cell)
        named = sorted(p.name[len(cell) + 1:-len(".simenv.json")] for p in d.glob(f"{cell}.*.simenv.json"))
        return [""] + [n for n in named if n and "." not in n]

    @classmethod
    def load(cls, ws: Workspace, lib: str, cell: str, name: str = "") -> "Setup":
        p = cls.path(ws, lib, cell, name)
        if not p.is_file():
            if name:
                raise flows.FlowError(f"{lib}/{cell} has no setup '{name}'")
            return cls.default(ws, lib, cell)
        d = json.loads(p.read_text())
        return cls(
            variables={k: str(v) for k, v in d.get("variables", {}).items()},
            outputs=[Output(**o) for o in d.get("outputs", [])],
            corners=[Corner(**c) for c in d.get("corners", [])],
            montecarlo=MonteCarlo(**d.get("montecarlo", {})),
            schematic=d.get("schematic", ""),
            wave=d.get("wave", ""),
            wave_logx=bool(d.get("wave_logx", False)),
            views={k: views.Binding.from_json(v).to_json() for k, v in d.get("views", {}).items()},
            name=name,
        )

    def bindings(self) -> dict[str, views.Binding]:
        return {k: views.Binding.from_json(v) for k, v in self.views.items()}

    def set_binding(self, key: str, b: views.Binding) -> None:
        if b.view == views.SCHEMATIC and not b.params:
            self.views.pop(key, None)
        else:
            self.views[key] = b.to_json()

    @classmethod
    def default(cls, ws: Workspace, lib: str, cell: str) -> "Setup":
        s = cls()
        sch = ws.view_path(lib, cell, "schematic")
        if sch.is_file():
            s.variables = scan_variables(sch.read_text(errors="replace"))
        s.corners = [Corner(f"{m[4:]}_{t}", True, m, "cap_typ", "res_typ", t)
                     for m in MOS_SECTIONS for t in (27,)]
        return s

    def save(self, ws: Workspace, lib: str, cell: str, name: str | None = None) -> Path:
        if name is not None:
            self.name = views_name(name)
        p = self.path(ws, lib, cell, self.name)
        d = asdict(self)
        d.pop("name")
        p.write_text(json.dumps(d, indent=2) + "\n")
        return p


def views_name(name: str) -> str:
    """A setup's name: letters, digits, _ and - (it goes into a file name)."""

    name = name.strip()
    if name and not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ValueError(f"setup name '{name}': use letters, digits, _ and -")
    return name


# --- netlist editing -------------------------------------------------------------

_PARAM_RE = re.compile(r"^\s*\.param\s+(.*)$", re.I | re.M)


def scan_variables(text: str) -> dict[str, str]:
    """``.param name=value`` lines of a testbench (its design variables).
    Lines whose value calls a random function belong to the models: skipped."""

    out: dict[str, str] = {}
    for m in _PARAM_RE.finditer(text):
        for name, value in re.findall(r"(\w+)\s*=\s*('[^']*'|\{[^}]*\}|\S+)", m.group(1)):
            if name.lower() == "temp" or "gauss" in value:
                continue
            out[name] = value.strip("'{}")
    return out


def set_param(text: str, name: str, value: str) -> str:
    """Set every ``.param name=...`` (alone on its line or among others); add one if missing."""

    pat = re.compile(r"(^\s*\.param\b[^\n]*?\b" + re.escape(name) + r"\s*=\s*)('[^']*'|\{[^}]*\}|[^\s]+)",
                     re.I | re.M)
    new, n = pat.subn(lambda m: m.group(1) + str(value), text)
    if n:
        return new
    return _insert_before_control(text, f".param {name}={value}\n")


def add_missing_variables(text: str, variables: dict[str, str]) -> str:
    """Define the design variables the netlist does not define yet (``.param``)."""

    for name, value in variables.items():
        if not re.search(r"^\s*\.param\b[^\n]*?\b" + re.escape(name) + r"\s*=", text, re.I | re.M):
            text = _insert_before_control(text, f".param {name}={value}\n")
    return text


def _insert_before_control(text: str, lines: str) -> str:
    m = re.search(r"^\s*\.control\b", text, re.M | re.I)
    if m:
        return text[:m.start()] + lines + text[m.start():]
    m = re.search(r"^\s*\.end\s*$", text, re.M | re.I)
    return (text[:m.start()] + lines + text[m.start():]) if m else text + lines


def set_section(text: str, family: str, section: str) -> str:
    """``.lib cornerMOSlv.lib mos_tt`` -> ``... <section>`` (family: MOS, CAP, RES)."""

    lib = {"mos": r"cornerMOS(?:lv|hv)\.lib", "cap": r"cornerCAP\.lib", "res": r"cornerRES\.lib"}[family]
    return re.sub(r"(^\s*\.lib\s+\S*" + lib + r"\s+)(\S+)", lambda m: m.group(1) + section,
                  text, flags=re.M | re.I)


def ensure_section(text: str, family: str, section: str) -> str:
    """Like set_section, adding the .lib line when the testbench has none
    (needed for MC of capacitors/resistors in a testbench that only has MOS)."""

    new = set_section(text, family, section)
    if new != text or re.search(section, text):
        return new
    if family == "mos":
        return new
    fname = {"cap": "cornerCAP.lib", "res": "cornerRES.lib"}[family]
    return _insert_before_control(text, f".lib {fname} {section}\n")


WAVE_FILE = "fosslab_wave.txt"


def add_measurements(text: str, outputs: list[Output], wave: str = "") -> str:
    """Put the outputs' own measurements (and the waveform to save) at the end
    of the last .control block, after the testbench's analyses."""

    lines = [ln for o in outputs for ln in o.control_lines()]
    if wave.strip():
        lines.append(f"wrdata {WAVE_FILE} {wave.strip()}")
    if not lines:
        return text
    ends = list(re.finditer(r"^\s*\.endc\b", text, re.M | re.I))
    block = "* --- added by the FOSSLab Simulation Environment ---\n" + "\n".join(lines) + "\n"
    if not ends:
        return _insert_before_control(text, ".control\n" + block + ".endc\n")
    pos = ends[-1].start()
    return text[:pos] + block + text[pos:]


def job_netlist(base: str, corner: Corner, variables: dict[str, str],
                seed: int | None = None, variation: str | None = None,
                outputs: list[Output] | None = None, wave: str = "") -> str:
    text = add_measurements(base, outputs or [], wave)
    vars_ = dict(variables)
    vars_.update(corner.vars)
    for name, value in vars_.items():
        text = set_param(text, name, value)
    mos, cap, res = corner.mos, corner.cap, corner.res
    if variation:
        fmt = VARIATIONS[variation]
        # IHP names: mos_tt_mismatch / mos_tt_stat, cap_typ_mismatch / cap_typ_stat,
        # res_typ_mismatch / res_stat
        mos = fmt.format(section=mos)
        cap = fmt.format(section=cap)
        res = "res_stat" if variation == "process" else fmt.format(section=res)
    text = set_section(text, "mos", mos)
    text = ensure_section(text, "cap", cap) if re.search(r"cornerCAP", base, re.I) else text
    text = ensure_section(text, "res", res) if re.search(r"cornerRES", base, re.I) else text
    text = re.sub(r"^\s*\.param\s+temp\s*=\s*\S+", f".param temp={corner.temp}", text, flags=re.M | re.I)
    extra = f".option temp={corner.temp}\n"
    if seed is not None:
        extra += f".option seed={seed}\n"
    text = _insert_before_control(text, extra)
    # jobs already run in parallel: one thread each
    return re.sub(r"^(\s*\.control\s*\n)", r"\1set num_threads=1\n", text, count=1, flags=re.M | re.I)


_RESULT_RE = re.compile(r"^\s*([A-Za-z_][\w.]*)\s*=\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*$")


def parse_results(log_text: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for line in log_text.splitlines():
        m = _RESULT_RE.match(line)
        if m:
            out[m.group(1).lower()] = float(m.group(2))
    return out


# --- running -------------------------------------------------------------------------

@dataclass
class JobResult:
    name: str
    values: dict[str, float]
    ok: bool
    error: str = ""
    seed: int | None = None
    wave: tuple[list[float], list[float]] | None = None


def read_wave(path: Path) -> tuple[list[float], list[float]] | None:
    """x and y columns of an ngspice 'wrdata' file."""

    if not path.is_file():
        return None
    xs, ys = [], []
    for line in path.read_text(errors="replace").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            try:
                xs.append(float(parts[0]))
                ys.append(float(parts[1]))
            except ValueError:
                continue
    return (xs, ys) if xs else None


def _run_job(work: Path, name: str, netlist: str, seed: int | None) -> JobResult:
    d = work / name
    d.mkdir(parents=True, exist_ok=True)
    net = d / "netlist.spice"
    net.write_text(netlist)
    try:
        p = subprocess.run(["ngspice", "-b", net.name], cwd=d, capture_output=True, text=True,
                           timeout=1800, stdin=subprocess.DEVNULL, errors="replace")
        log = p.stdout + p.stderr
    except subprocess.TimeoutExpired:
        return JobResult(name, {}, False, "timeout", seed)
    (d / "ngspice.log").write_text(log)
    errors = [ln for ln in log.splitlines() if re.match(r"^\s*(Error|ERROR)\b", ln)]
    vals = parse_results(log)
    return JobResult(name, vals, not errors and bool(vals), errors[0] if errors else "", seed,
                     read_wave(d / WAVE_FILE))


@dataclass
class RunSet:
    kind: str                      # corners | montecarlo | nominal
    lib: str
    cell: str
    run_dir: str
    outputs: list[Output]
    results: list[JobResult]
    time: float = field(default_factory=time.time)
    variation: str = ""

    def column(self, name: str) -> list[float]:
        return [r.values[name] for r in self.results if r.ok and name in r.values]

    def stats(self, name: str) -> dict[str, float]:
        xs = self.column(name)
        if not xs:
            return {}
        out = {"n": len(xs), "mean": statistics.fmean(xs), "min": min(xs), "max": max(xs)}
        out["std"] = statistics.stdev(xs) if len(xs) > 1 else 0.0
        return out

    def yield_(self) -> float | None:
        checked = [o for o in self.outputs if o.min is not None or o.max is not None]
        if not checked or not self.results:
            return None
        good = sum(1 for r in self.results if r.ok and
                   all(o.passes(r.values.get(o.name)) for o in checked))
        return good / len(self.results)

    def write_csv(self, path: Path) -> Path:
        names = [o.name for o in self.outputs] or sorted({k for r in self.results for k in r.values})
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["run", "seed", "ok", *names])
            for r in self.results:
                w.writerow([r.name, r.seed if r.seed is not None else "", int(r.ok),
                            *[r.values.get(n, "") for n in names]])
        return path

    def save(self) -> None:
        d = Path(self.run_dir)
        self.write_csv(d / "results.csv")
        summary = {"kind": self.kind, "lib": self.lib, "cell": self.cell, "time": self.time,
                   "variation": self.variation, "runs": len(self.results),
                   "failed_runs": sum(1 for r in self.results if not r.ok),
                   "yield": self.yield_(),
                   "stats": {o.name: self.stats(o.name) for o in self.outputs}}
        (d / "summary.json").write_text(json.dumps(summary, indent=2))


def base_netlist(ws: Workspace, lib: str, cell: str, setup: Setup, out_dir: Path,
                 echo: Echo | None = None) -> str:
    sch = None
    if setup.schematic:
        sch = ws.cell_dir(lib, cell) / setup.schematic
    net = flows.netlist(ws, lib, cell, out_dir, schematic=sch, echo=echo)
    text = net.read_text(errors="replace")
    b = setup.bindings()
    if any(x.view != views.SCHEMATIC for x in b.values()):
        # the variables first: the views' parameters may use them
        text = views.apply(ws, add_missing_variables(text, setup.variables), b, out_dir, echo)
        net.write_text(text)
    # graphs and interactive commands make no sense in batch runs
    text = re.sub(r"^\s*(plot|setplot|gnuplot|wrdata\s+/dev)\b.*$", r"* (removed by FOSSLab) \g<0>",
                  text, flags=re.M | re.I)
    return text


def _run_dir(ws: Workspace, lib: str, cell: str, kind: str, name: str = "") -> Path:
    d = ws.sim_dir(lib, cell) / (f"{kind}.{name}" if name else kind)
    if d.is_dir():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    return d


def run_corners(ws: Workspace, lib: str, cell: str, setup: Setup | None = None,
                echo: Echo | None = None, progress: Callable[[int, int], None] | None = None,
                jobs: int | None = None) -> RunSet:
    setup = setup or Setup.load(ws, lib, cell)
    echo = echo or (lambda s: print(s, flush=True))
    d = _run_dir(ws, lib, cell, "corners", setup.name)
    base = base_netlist(ws, lib, cell, setup, d, echo)
    corners = [c for c in setup.corners if c.enabled]
    if not corners:
        raise flows.FlowError("no corner is enabled")
    echo(f"running {len(corners)} corners")
    results = _parallel(d, [(c.name, job_netlist(base, c, setup.variables, outputs=setup.outputs,
                                                  wave=setup.wave), None) for c in corners],
                        jobs or setup.montecarlo.jobs, echo, progress)
    rs = RunSet("corners", lib, cell, str(d), setup.outputs, results)
    rs.save()
    for o in setup.outputs:
        bar_chart(rs, o, d / f"bars_{o.name}.png")
    if setup.wave:
        wave_plot(rs, setup, d / "waves.png")
    return rs


def run_montecarlo(ws: Workspace, lib: str, cell: str, setup: Setup | None = None,
                   echo: Echo | None = None, progress: Callable[[int, int], None] | None = None,
                   corner: Corner | None = None) -> RunSet:
    setup = setup or Setup.load(ws, lib, cell)
    echo = echo or (lambda s: print(s, flush=True))
    mc = setup.montecarlo
    if mc.variation not in VARIATIONS:
        raise flows.FlowError(f"unknown variation '{mc.variation}' (use {', '.join(VARIATIONS)})")
    d = _run_dir(ws, lib, cell, "montecarlo", setup.name)
    base = base_netlist(ws, lib, cell, setup, d, echo)
    corner = corner or Corner("nominal")
    echo(f"running {mc.runs} Monte Carlo samples ({mc.variation}), seeds {mc.seed}..{mc.seed + mc.runs - 1}")
    jobs = [(f"run{i + 1:04d}", job_netlist(base, corner, setup.variables, seed=mc.seed + i,
                                            variation=mc.variation, outputs=setup.outputs,
                                            wave=setup.wave), mc.seed + i)
            for i in range(mc.runs)]
    results = _parallel(d, jobs, mc.jobs, echo, progress)
    rs = RunSet("montecarlo", lib, cell, str(d), setup.outputs, results, variation=mc.variation)
    rs.save()
    for o in setup.outputs:
        histogram(rs, o, d / f"hist_{o.name}.png")
    if setup.wave:
        wave_plot(rs, setup, d / "waves.png")
    return rs


def run_nominal(ws: Workspace, lib: str, cell: str, setup: Setup | None = None,
                echo: Echo | None = None) -> RunSet:
    setup = setup or Setup.load(ws, lib, cell)
    d = _run_dir(ws, lib, cell, "nominal", setup.name)
    base = base_netlist(ws, lib, cell, setup, d, echo)
    res = _parallel(d, [("nominal", job_netlist(base, Corner("nominal"), setup.variables,
                                                outputs=setup.outputs, wave=setup.wave), None)],
                    1, echo or (lambda s: None), None)
    rs = RunSet("nominal", lib, cell, str(d), setup.outputs, res)
    rs.save()
    if setup.wave:
        wave_plot(rs, setup, d / "waves.png")
    return rs


def _parallel(work: Path, jobs: list[tuple[str, str, int | None]], n: int, echo: Echo,
              progress: Callable[[int, int], None] | None) -> list[JobResult]:
    n = max(1, min(int(n or 1), os.cpu_count() or 1, len(jobs)))
    done = 0
    results: dict[str, JobResult] = {}
    with ThreadPoolExecutor(max_workers=n) as ex:
        futs = {ex.submit(_run_job, work, name, net, seed): name for name, net, seed in jobs}
        for fut in futs:
            r = fut.result()
            results[r.name] = r
            done += 1
            echo(f"  {r.name}: {'ok' if r.ok else 'FAILED ' + r.error}")
            if progress:
                progress(done, len(jobs))
    return [results[name] for name, _, _ in jobs]


def histogram(rs: RunSet, out: Output, path: Path, bins: int = 25) -> Path | None:
    xs = [out.show(x) for x in rs.column(out.name)]
    if len(xs) < 2:
        return None
    plt = _plt()
    st = rs.stats(out.name)
    mean, std = st["mean"] * out.scale, st["std"] * out.scale
    fig, ax = plt.subplots(figsize=(6.4, 3.6), dpi=110)
    lo, hi = min(xs), max(xs)
    span = max(hi - lo, abs(mean) * 1e-3, 1e-12)
    x1, x2 = lo - 0.15 * span, hi + 0.15 * span
    off_scale = []
    for lim in (out.min, out.max):
        if lim is None:
            continue
        if x1 - 2 * span <= lim <= x2 + 2 * span:   # near the data: draw it
            x1, x2 = min(x1, lim - 0.05 * span), max(x2, lim + 0.05 * span)
            ax.axvline(lim, color="#b3261e", linestyle="--", linewidth=1.2)
        else:
            off_scale.append(f"{lim:g}")
    ax.hist(xs, bins=bins, range=(lo - 0.02 * span, hi + 0.02 * span), color="#3a6ea5", edgecolor="white")
    ax.set_xlim(x1, x2)
    ax.axvline(mean, color="#1b1b1b", linewidth=1)
    label = out.label or out.name
    ax.set_xlabel(f"{label}" + (f" ({out.unit})" if out.unit else ""))
    ax.set_ylabel("runs")
    note = f"   [spec {', '.join(off_scale)}: off scale]" if off_scale else ""
    ax.set_title(f"{label}: mean {mean:.4g}, σ {std:.3g}  (N={len(xs)}){note}", fontsize=9)
    ax.grid(axis="y", alpha=.3)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def bar_chart(rs: RunSet, out: Output, path: Path) -> Path | None:
    """One bar per corner, with the specification limits."""

    names = [r.name for r in rs.results if r.ok and out.name in r.values]
    vals = [out.show(r.values[out.name]) for r in rs.results if r.ok and out.name in r.values]
    if not vals:
        return None
    plt = _plt()
    fig, ax = plt.subplots(figsize=(6.4, 3.6), dpi=110)
    colors = ["#b3261e" if out.passes(r.values[out.name]) is False else "#3a6ea5"
              for r in rs.results if r.ok and out.name in r.values]
    ax.bar(range(len(vals)), vals, color=colors)
    ax.set_xticks(range(len(vals)), names, rotation=60, ha="right", fontsize=8)
    for lim in (out.min, out.max):
        if lim is not None:
            ax.axhline(lim, color="#b3261e", linestyle="--", linewidth=1.2)
    lo, hi = min(vals + [v for v in (out.min, out.max) if v is not None]), \
        max(vals + [v for v in (out.min, out.max) if v is not None])
    pad = (hi - lo) * 0.15 or abs(hi) * 0.1 or 1
    ax.set_ylim(lo - pad, hi + pad)
    label = out.label or out.name
    ax.set_title(f"{label} per corner" + (f" ({out.unit})" if out.unit else ""), fontsize=10)
    ax.grid(axis="y", alpha=.3)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def wave_plot(rs: RunSet, setup: Setup, path: Path) -> Path | None:
    """The saved waveform of every run, on top of each other."""

    runs = [r for r in rs.results if r.wave]
    if not runs:
        return None
    plt = _plt()
    fig, ax = plt.subplots(figsize=(6.4, 3.8), dpi=110)
    many = len(runs) > 12
    for r in runs:
        xs, ys = r.wave
        ax.plot(xs, ys, linewidth=0.6 if many else 1.2, alpha=0.35 if many else 1.0,
                color="#3a6ea5" if many else None, label=None if many else r.name)
    if setup.wave_logx:
        ax.set_xscale("log")
    ax.set_title(f"{setup.wave}: {len(runs)} runs", fontsize=10)
    ax.grid(alpha=.3)
    if not many:
        ax.legend(fontsize=7, ncol=3)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def fmt(v: float | None) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "-"
    return f"{v:.4g}"
