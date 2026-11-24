"""fosslab command line. ``fosslab`` alone starts the Library Manager.

Every action of the GUI is also a command, which is how the FOSSLab menus
inside xschem and KLayout work, e.g.

    fosslab open --file ~/fosslab/libs/work/opamp/opamp.sch --view layout
    fosslab lvs work opamp --show
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__, simenv, config, flows, hierarchy, ipc, templates, tools
from .workspace import KIND_BY_NAME, VIEW_KINDS, Workspace, fmt_time


def workspace_from_env(path: str | None = None) -> Workspace:
    root = Path(path).expanduser() if path else config.default_workspace()
    run_root = os.environ.get("FOSSLAB_RUN_ROOT")
    readonly = root.exists() and not os.access(root, os.W_OK)
    return Workspace(root, readonly=readonly, run_root=Path(run_root) if run_root else None)


def _target(ws: Workspace, args) -> tuple[str, str]:
    """(lib, cell) from --file or from the LIB CELL arguments."""

    if getattr(args, "file", None):
        loc = ws.locate(Path(args.file))
        if loc is None:
            sys.exit(f"fosslab: {args.file} is not in a library of workspace {ws.root}")
        return loc[0].name, loc[1]
    if not args.lib or not args.cell:
        sys.exit("fosslab: give LIB CELL or --file FILE")
    return args.lib, args.cell


def _add_target(p: argparse.ArgumentParser) -> None:
    p.add_argument("lib", nargs="?")
    p.add_argument("cell", nargs="?")
    p.add_argument("--file", help="a file of the cell (any view)")


# --- commands --------------------------------------------------------------------

def cmd_gui(ws: Workspace, args) -> int:
    from .gui.app import run_gui

    select = None
    if args.select and "/" in args.select:
        select = tuple(args.select.split("/", 1))
    return run_gui(ws, supervisor=args.supervisor, select=select)


def cmd_init(ws: Workspace, args) -> int:
    ws.init()
    tools.xschem_setup(ws)
    tools.ensure_user_xschemrc(ws)
    print(f"workspace ready: {ws.root}")
    return 0


def cmd_libs(ws: Workspace, args) -> int:
    for lib in ws.libraries():
        flag = " (read only)" if lib.readonly else ""
        print(f"{lib.name:20s} {lib.path}{flag}")
    return 0


def cmd_cells(ws: Workspace, args) -> int:
    for c in ws.cells(args.lib):
        views = ", ".join(v.kind for v in ws.views(args.lib, c) if not v.derived)
        st = ws.status(args.lib, c)
        flags = " ".join(f"{f}:{st.get(f)}" for f in ("drc", "lvs", "pex", "sim") if st.get(f))
        print(f"{c:24s} {views:40s} {flags}")
    return 0


def cmd_new_lib(ws: Workspace, args) -> int:
    lib = ws.add_library(args.name, Path(args.path) if args.path else None)
    print(f"library {lib.name} -> {lib.path}")
    _notify_refresh()
    return 0


def cmd_new_cell(ws: Workspace, args) -> int:
    ws.new_cell(args.lib, args.cell)
    for kind in [k for k in (args.views or "").split(",") if k]:
        print(templates.create_view(ws, args.lib, args.cell, kind))
    _notify_refresh()
    return 0


def cmd_new_view(ws: Workspace, args) -> int:
    lib, cell = args.lib, args.cell
    p = templates.create_view(ws, lib, cell, args.kind)
    print(p)
    if args.open:
        view = next(v for v in ws.views(lib, cell) if v.path == p)
        tools.open_view(ws, view)
    _notify_refresh()
    return 0


def cmd_open(ws: Workspace, args) -> int:
    lib, cell = _target(ws, args)
    views = [v for v in ws.views(lib, cell) if v.kind == args.view]
    if not views:
        label = KIND_BY_NAME[args.view].label if args.view in KIND_BY_NAME else args.view
        msg = f"{lib}/{cell} has no {label.lower()} view."
        if args.view in KIND_BY_NAME and not ws.library(lib).readonly and _from_tool():
            if _ask_yes_no("FOSSLab", msg + "\nCreate it now?"):
                p = templates.create_view(ws, lib, cell, args.view)
                views = [v for v in ws.views(lib, cell) if v.path == p]
        if not views:
            _message("FOSSLab", msg)
            return 1
    # Prefer the cell's own view (cell.sch over tb_*.sch)
    views.sort(key=lambda v: v.path.stem != cell)
    tools.open_view(ws, views[0], tool=args.tool)
    return 0


def cmd_reveal(ws: Workspace, args) -> int:
    lib, cell = _target(ws, args)
    msg = {"cmd": "reveal", "lib": lib, "cell": cell, "workspace": str(ws.root)}
    if ipc.send(msg):
        return 0
    tools.spawn([sys.executable, "-m", "fosslab", "gui", "--select", f"{lib}/{cell}"],
                env=tools.ws_env(ws))
    return 0


def cmd_hier(ws: Workspace, args) -> int:
    if args.file and Path(args.file).suffix == ".sch":
        sch = Path(args.file)
    else:
        lib, cell = _target(ws, args)
        sch = ws.view_path(lib, cell, "schematic")
    if not sch.is_file():
        sys.exit(f"fosslab: no schematic {sch}")
    if args.gui:
        from .gui.app import run_hierarchy

        return run_hierarchy(ws, sch)
    print(hierarchy.to_text(hierarchy.build(ws, sch)))
    return 0


def cmd_symbol(ws: Workspace, args) -> int:
    lib, cell = _target(ws, args)
    p = templates.update_symbol(ws, lib, cell)
    print(f"symbol written: {p}")
    _message("FOSSLab", f"Symbol of {lib}/{cell} created from the schematic's pins.\n\n{p}")
    _notify_refresh()
    return 0


def cmd_testbench(ws: Workspace, args) -> int:
    lib, cell = _target(ws, args)
    sch = templates.create_testbench(ws, lib, cell, args.name)
    print(f"testbench: {sch}")
    if args.open:
        tools.open_xschem(ws, sch)
    _notify_refresh()
    return 0


def cmd_flow(ws: Workspace, args) -> int:
    lib, cell = _target(ws, args)
    kwargs = {}
    if args.flow == "sim":
        if args.file and Path(args.file).suffix == ".sch":
            kwargs["schematic"] = Path(args.file)
        if args.extracted:
            kwargs["use_extracted"] = [c for c in args.extracted.split(",") if c]
    if args.show:
        from .gui.app import run_flow_window

        return run_flow_window(ws, args.flow, lib, cell, **kwargs)
    res = flows.FLOWS[args.flow](ws, lib, cell, **kwargs)
    print(f"\n{args.flow.upper()} {lib}/{cell}: {res.status.upper()}: {res.summary}")
    print(f"run folder: {res.run_dir}")
    return 0 if res.ok else 1


def cmd_simenv(ws: Workspace, args) -> int:
    lib, cell = _target(ws, args)
    from .gui.app import run_simenv

    return run_simenv(ws, lib, cell)


def cmd_sweep(ws: Workspace, args) -> int:
    """Corners or Monte Carlo from the command line, with the saved setup."""

    lib, cell = _target(ws, args)
    setup = simenv.Setup.load(ws, lib, cell)
    if args.cmd == "mc":
        if args.runs:
            setup.montecarlo.runs = args.runs
        if args.variation:
            setup.montecarlo.variation = args.variation
        if args.seed is not None:
            setup.montecarlo.seed = args.seed
        rs = simenv.run_montecarlo(ws, lib, cell, setup)
        print(f"\n{'output':16s} {'mean':>12s} {'std':>12s} {'min':>12s} {'max':>12s}")
        for o in rs.outputs:
            st = rs.stats(o.name)
            if st:
                print(f"{o.name:16s} {simenv.fmt(o.show(st['mean'])):>12s} {simenv.fmt(abs(o.show(st['std']))):>12s} "
                      f"{simenv.fmt(o.show(st['min'])):>12s} {simenv.fmt(o.show(st['max'])):>12s}")
        y = rs.yield_()
        if y is not None:
            print(f"yield: {100 * y:.1f} %")
    else:
        rs = simenv.run_corners(ws, lib, cell, setup)
        names = [r.name for r in rs.results]
        print("\n" + f"{'output':16s}" + "".join(f"{n:>14s}" for n in names))
        for o in rs.outputs:
            print(f"{o.name:16s}" + "".join(f"{simenv.fmt(o.show(r.values.get(o.name))):>14s}" for r in rs.results))
    print(f"results: {rs.run_dir}/results.csv")
    return 0 if all(r.ok for r in rs.results) else 1


def cmd_example(ws: Workspace, args) -> int:
    from .examples import opamp

    for line in opamp.build(ws, args.lib, with_layout=not args.no_layout):
        print(" ", line)
    if args.solution:
        print("  exercise solution:", opamp.write_solution(ws, args.lib))
    _notify_refresh()
    return 0


def cmd_copy(ws: Workspace, args) -> int:
    src = workspace_from_env(args.from_workspace) if args.from_workspace else ws
    p = ws.copy_cell(src, args.src_lib, args.cell, args.dst_lib, args.new_name)
    print(f"copied to {p}")
    _notify_refresh()
    return 0


def cmd_rename(ws: Workspace, args) -> int:
    p = ws.rename_cell(args.lib, args.cell, args.new_name)
    print(f"renamed to {p}")
    _notify_refresh()
    return 0


def cmd_delete(ws: Workspace, args) -> int:
    ws.delete_cell(args.lib, args.cell)
    _notify_refresh()
    return 0


def cmd_status(ws: Workspace, args) -> int:
    for lib in ws.libraries(include_pdk=False):
        for c in ws.cells(lib):
            st = ws.status(lib.name, c)
            if not st.results:
                continue
            for flow, r in st.results.items():
                print(f"{lib.name}/{c:20s} {flow:4s} {r.get('status', ''):6s} "
                      f"{fmt_time(r.get('time', 0))}  {r.get('summary', '')}")
    print(f"last change: {fmt_time(ws.last_modified())}")
    return 0


def cmd_selftest(ws: Workspace, args) -> int:
    from .selftest import run_selftest

    return run_selftest(Path(args.dir) if args.dir else None)


# --- small helpers ------------------------------------------------------------------

def _notify_refresh() -> None:
    ipc.send({"cmd": "refresh"})


def _tk_root():
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    return root


def _from_tool() -> bool:
    """Started from a menu inside xschem/KLayout (no terminal to print to)?"""

    return bool(os.environ.get("FOSSLAB_FROM_TOOL") and os.environ.get("DISPLAY"))


def _message(title: str, text: str) -> None:
    if not _from_tool():
        return
    from tkinter import messagebox

    root = _tk_root()
    messagebox.showinfo(title, text, parent=root)
    root.destroy()


def _ask_yes_no(title: str, text: str) -> bool:
    from tkinter import messagebox

    root = _tk_root()
    ans = messagebox.askyesno(title, text, parent=root)
    root.destroy()
    return ans


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fosslab", description="FOSSLab design manager (IHP SG13G2)")
    p.add_argument("--version", action="version", version=f"fosslab {__version__}")
    p.add_argument("-w", "--workspace", help="workspace folder (default ~/fosslab)")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("gui", help="the Library Manager (default)")
    s.add_argument("--supervisor", action="store_true", help="supervise the students' workspaces")
    s.add_argument("--select", help="LIB/CELL to show")
    s.set_defaults(func=cmd_gui)

    sub.add_parser("init", help="create the workspace").set_defaults(func=cmd_init)
    sub.add_parser("libs", help="list libraries").set_defaults(func=cmd_libs)
    s = sub.add_parser("cells", help="list the cells of a library")
    s.add_argument("lib")
    s.set_defaults(func=cmd_cells)

    s = sub.add_parser("new-lib", help="new library")
    s.add_argument("name")
    s.add_argument("--path", help="library folder (its name must be the library name)")
    s.set_defaults(func=cmd_new_lib)

    s = sub.add_parser("new-cell", help="new cell")
    s.add_argument("lib")
    s.add_argument("cell")
    s.add_argument("--views", help="comma-separated views to create: "
                   + ",".join(k.name for k in VIEW_KINDS))
    s.set_defaults(func=cmd_new_cell)

    s = sub.add_parser("new-view", help="new view of a cell")
    s.add_argument("lib")
    s.add_argument("cell")
    s.add_argument("kind", choices=[k.name for k in VIEW_KINDS])
    s.add_argument("--open", action="store_true")
    s.set_defaults(func=cmd_new_view)

    s = sub.add_parser("open", help="open a view in its tool")
    _add_target(s)
    s.add_argument("--view", default="schematic")
    s.add_argument("--tool", choices=["xschem", "klayout", "magic", "editor"])
    s.set_defaults(func=cmd_open)

    s = sub.add_parser("reveal", help="show a cell in the Library Manager")
    _add_target(s)
    s.set_defaults(func=cmd_reveal)

    s = sub.add_parser("hier", help="design hierarchy of a schematic")
    _add_target(s)
    s.add_argument("--gui", action="store_true", help="open the Hierarchy browser window")
    s.set_defaults(func=cmd_hier)

    s = sub.add_parser("symbol", help="create/update the symbol from the schematic pins")
    _add_target(s)
    s.set_defaults(func=cmd_symbol)

    s = sub.add_parser("testbench", help="new testbench cell tb_<cell> for a cell")
    _add_target(s)
    s.add_argument("--name", help="testbench cell name (default tb_<cell>)")
    s.add_argument("--open", action="store_true")
    s.set_defaults(func=cmd_testbench)

    for flow, helptext in (("sim", "netlist and simulate with ngspice"),
                           ("drc", "design rule check (IHP KLayout deck)"),
                           ("lvs", "layout versus schematic (IHP KLayout deck)"),
                           ("pex", "parasitic extraction (Magic)"),
                           ("va", "compile the Verilog-A view with OpenVAF")):
        s = sub.add_parser(flow, help=helptext)
        _add_target(s)
        s.add_argument("--show", action="store_true", help="show progress and result in a window")
        if flow == "sim":
            s.add_argument("--extracted", help="cells to simulate from their PEX netlist (c1,c2)")
        s.set_defaults(func=cmd_flow, flow=flow)

    s = sub.add_parser("simenv", help="Simulation Environment window (variables, corners, Monte Carlo)")
    _add_target(s)
    s.set_defaults(func=cmd_simenv)
    s = sub.add_parser("corners", help="run the corners of a testbench's saved setup")
    _add_target(s)
    s.set_defaults(func=cmd_sweep)
    s = sub.add_parser("mc", help="run Monte Carlo with a testbench's saved setup")
    _add_target(s)
    s.add_argument("-n", "--runs", type=int)
    s.add_argument("--variation", choices=list(simenv.VARIATIONS))
    s.add_argument("--seed", type=int)
    s.set_defaults(func=cmd_sweep)

    s = sub.add_parser("example", help="install the tutorial's reference op-amp library")
    s.add_argument("name", choices=["opamp"])
    s.add_argument("--lib", default="opamp_tut")
    s.add_argument("--no-layout", action="store_true")
    s.add_argument("--solution", action="store_true", help="also the exercise solution (teachers)")
    s.set_defaults(func=cmd_example)

    s = sub.add_parser("copy", help="copy a cell")
    s.add_argument("src_lib")
    s.add_argument("cell")
    s.add_argument("dst_lib")
    s.add_argument("new_name", nargs="?")
    s.add_argument("--from-workspace", help="copy from another workspace (e.g. a student's)")
    s.set_defaults(func=cmd_copy)

    s = sub.add_parser("rename", help="rename a cell (updates instances)")
    s.add_argument("lib")
    s.add_argument("cell")
    s.add_argument("new_name")
    s.set_defaults(func=cmd_rename)

    s = sub.add_parser("delete", help="delete a cell")
    s.add_argument("lib")
    s.add_argument("cell")
    s.set_defaults(func=cmd_delete)

    sub.add_parser("status", help="verification status of every cell").set_defaults(func=cmd_status)

    s = sub.add_parser("selftest", help="check every tool and flow on real IHP data")
    s.add_argument("--dir", help="where to build the test workspace (default: a temp dir)")
    s.set_defaults(func=cmd_selftest)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not getattr(args, "func", None):
        args.func, args.supervisor, args.select = cmd_gui, False, None
    ws = workspace_from_env(args.workspace)
    if args.func is not cmd_gui and args.func is not cmd_selftest and args.func is not cmd_init:
        if not ws.exists():
            if ws.readonly:
                sys.exit(f"fosslab: no workspace in {ws.root}")
            ws.init()
    try:
        return args.func(ws, args)
    except (ValueError, KeyError, PermissionError, FileExistsError, FileNotFoundError,
            flows.FlowError) as e:
        if os.environ.get("FOSSLAB_DEBUG"):
            raise
        msg = e.args[0] if e.args else str(e)
        print(f"fosslab: {msg}", file=sys.stderr)
        _message("FOSSLab", str(msg))
        return 1


if __name__ == "__main__":
    sys.exit(main())
