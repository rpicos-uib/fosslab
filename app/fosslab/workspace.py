"""The design database: libraries -> cells -> views, on plain files.

A workspace is a directory (by default ~/fosslab) laid out like this:

    fosslab.lib              library definitions
    libs/<lib>/<cell>/       one directory per cell, one file per view:
        <cell>.sch             schematic        (xschem)
        <cell>.sym             symbol           (xschem)
        <cell>.gds             layout           (KLayout)
        <cell>.mag             Magic layout     (Magic)
        <cell>.va              Verilog-A model  (editor + OpenVAF)
        <cell>.v               Verilog          (editor + Icarus)
        <cell>.spice           hand-written SPICE subcircuit
        <cell>.md              notes
    sim/<lib>/<cell>/        simulation runs (netlists, .raw, logs)
    verif/<lib>/<cell>/{drc,lvs,pex}/   verification runs and status.json
    .fosslab/                generated tool setup (xschemrc, ...)

xschem finds a symbol by its path relative to a library-path entry, so an
instance in a schematic refers to ``<lib>/<cell>/<cell>.sym`` and the parent
of every library directory is put on xschem's library path. This is why a
library directory must have the same name as the library.

PDK libraries (IHP primitives and standard cells, xschem's own devices) are
added read-only and use the PDK's flat layout: one file per view, named
after the cell, all in one directory.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import config

LIB_FILE = "fosslab.lib"
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class ViewKind:
    name: str          # schematic, symbol, layout, ...
    suffix: str        # file suffix of the view
    tool: str          # program that edits it
    label: str         # what the GUI shows
    creatable: bool = True


VIEW_KINDS: list[ViewKind] = [
    ViewKind("schematic", ".sch", "xschem", "Schematic"),
    ViewKind("symbol", ".sym", "xschem", "Symbol"),
    ViewKind("layout", ".gds", "klayout", "Layout"),
    ViewKind("magic", ".mag", "magic", "Magic layout"),
    ViewKind("veriloga", ".va", "editor", "Verilog-A"),
    ViewKind("verilog", ".v", "editor", "Verilog"),
    ViewKind("spice", ".spice", "editor", "SPICE subckt"),
    ViewKind("notes", ".md", "editor", "Notes"),
]
KIND_BY_NAME = {k.name: k for k in VIEW_KINDS}
KIND_BY_SUFFIX = {k.suffix: k for k in VIEW_KINDS}

# Results of the flows, shown as read-only views next to the real ones.
DERIVED_KINDS = {
    "netlist": "Netlist (sim)",
    "lvs_netlist": "Netlist (LVS)",
    "extracted": "Extracted (LVS)",
    "pex": "Extracted + parasitics",
    "osdi": "Compiled model (OSDI)",
}


@dataclass
class Library:
    name: str
    path: Path
    readonly: bool = False
    flat: bool = False                 # PDK layout: <dir>/<cell>.<ext>
    extra_dirs: tuple[Path, ...] = ()  # more flat dirs (e.g. stdcell sch + sym)
    layout_file: Path | None = None    # one GDS holding every cell
    description: str = ""
    included: bool = False             # from an INCLUDEd file: someone else's library


@dataclass
class View:
    kind: str
    path: Path
    derived: bool = False
    cell_in_file: str | None = None    # for a GDS that holds many cells

    @property
    def label(self) -> str:
        if self.kind in KIND_BY_NAME:
            return KIND_BY_NAME[self.kind].label
        return DERIVED_KINDS.get(self.kind, self.kind)


@dataclass
class CellStatus:
    """Last verification results, read from verif/<lib>/<cell>/*/status.json."""

    results: dict[str, dict] = field(default_factory=dict)

    def get(self, flow: str) -> str:
        return self.results.get(flow, {}).get("status", "")


def check_name(name: str, what: str = "name") -> str:
    name = name.strip()
    if not NAME_RE.match(name):
        raise ValueError(
            f"Invalid {what} '{name}': use letters, digits and _, starting with a letter."
        )
    return name


def _pdk_libraries() -> list[Library]:
    libs = []
    xs = config.pdk("libs.tech", "xschem")
    if (xs / "sg13g2_pr").is_dir():
        libs.append(Library("sg13g2_pr", xs / "sg13g2_pr", readonly=True, flat=True,
                            description="IHP SG13G2 primitive devices (transistors, R, C, ...)"))
    sc = config.pdk("libs.ref", "sg13g2_stdcell")
    if sc.is_dir():
        libs.append(Library("sg13g2_stdcell", sc / "sym" / "xschem" if (sc / "sym" / "xschem").is_dir() else sc / "sch",
                            readonly=True, flat=True,
                            extra_dirs=(sc / "sch" / "xschem", sc / "sch"),
                            layout_file=sc / "gds" / "sg13g2_stdcell.gds",
                            description="IHP SG13G2 standard cells (logic gates)"))
    devices = config.TOOLS / "xschem" / "share" / "xschem" / "xschem_library" / "devices"
    if devices.is_dir():
        libs.append(Library("devices", devices, readonly=True, flat=True,
                            description="xschem generic devices: sources, ground, pins, code blocks"))
    if (xs / "sg13g2_tests").is_dir():
        libs.append(Library("sg13g2_tests", xs / "sg13g2_tests", readonly=True, flat=True,
                            description="IHP example testbenches (read only: copy a cell to edit it)"))
    return libs


class Workspace:
    def __init__(self, root: Path, readonly: bool = False, run_root: Path | None = None,
                 owner: str = ""):
        self.root = Path(root).expanduser()
        self.readonly = readonly
        self.owner = owner
        # Where flows write. A supervisor browsing a student writes runs in
        # their own workspace, never in the student's.
        self.run_root = Path(run_root) if run_root else self.root

    # --- setup -----------------------------------------------------------

    @property
    def lib_file(self) -> Path:
        return self.root / LIB_FILE

    @property
    def setup_dir(self) -> Path:
        return self.run_root / ".fosslab"

    def exists(self) -> bool:
        return self.lib_file.is_file()

    def init(self) -> None:
        """Create an empty workspace (does nothing to an existing one)."""

        if self.readonly:
            raise PermissionError("read-only workspace")
        for d in ("libs", "sim", "verif", ".fosslab"):
            (self.root / d).mkdir(parents=True, exist_ok=True)
        if not self.lib_file.exists():
            self.lib_file.write_text(
                "# FOSSLab library definitions (one line per library).\n"
                "# DEFINE <library> <directory>   (relative to this file)\n"
                "# INCLUDE <another fosslab.lib>  (e.g. a library shared by the teacher)\n"
                "# The IHP SG13G2 PDK libraries are always available, read only.\n"
            )
            self.add_library("work")

    # --- libraries -------------------------------------------------------

    def _parse_lib_file(self, path: Path, seen: set[Path]) -> list[Library]:
        path = path.resolve()
        if path in seen or not path.is_file():
            return []
        seen.add(path)
        libs: list[Library] = []
        for raw in path.read_text(errors="replace").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            key = parts[0].upper()
            if key == "DEFINE" and len(parts) >= 3:
                p = Path(parts[2]).expanduser()
                if not p.is_absolute():
                    p = path.parent / p
                ro = len(parts) > 3 and parts[3].lower() in ("ro", "readonly")
                libs.append(Library(parts[1], p, readonly=ro))
            elif key in ("INCLUDE", "SOFTINCLUDE") and len(parts) >= 2:
                p = Path(parts[1]).expanduser()
                if not p.is_absolute():
                    p = path.parent / p
                for lib in self._parse_lib_file(p, seen):
                    lib.readonly = lib.included = True   # someone else's library
                    libs.append(lib)
            elif key == "UNDEFINE" and len(parts) >= 2:
                libs = [lib for lib in libs if lib.name != parts[1]]
        return libs

    def libraries(self, include_pdk: bool = True) -> list[Library]:
        libs = self._parse_lib_file(self.lib_file, set())
        if self.readonly:
            for lib in libs:
                lib.readonly = True
        if include_pdk:
            names = {lib.name for lib in libs}
            libs += [lib for lib in _pdk_libraries() if lib.name not in names]
        return libs

    def own_libraries(self) -> list[Library]:
        """The libraries defined in this workspace (not PDK, not included),
        whether or not we may write to them."""

        return [lib for lib in self.libraries(include_pdk=False) if not lib.included]

    def library(self, name: str) -> Library:
        for lib in self.libraries():
            if lib.name == name:
                return lib
        raise KeyError(f"no library '{name}'")

    def add_library(self, name: str, path: Path | None = None) -> Library:
        name = check_name(name, "library name")
        if self.readonly:
            raise PermissionError("read-only workspace")
        if any(lib.name == name for lib in self.libraries()):
            raise ValueError(f"library '{name}' already exists")
        if path is None:
            path = self.root / "libs" / name
            rel = f"libs/{name}"
        else:
            path = Path(path).expanduser().resolve()
            if path.name != name:
                raise ValueError("the library directory must have the same name as the library")
            rel = str(path)
        path.mkdir(parents=True, exist_ok=True)
        with self.lib_file.open("a") as f:
            f.write(f"DEFINE {name} {rel}\n")
        return Library(name, path)

    def remove_library(self, name: str, delete_files: bool = False) -> None:
        lib = self.library(name)
        if lib.readonly:
            raise PermissionError(f"library '{name}' is read only")
        lines = self.lib_file.read_text().splitlines(keepends=True)
        keep = [ln for ln in lines
                if not (ln.split("#", 1)[0].split()[:2] == ["DEFINE", name])]
        self.lib_file.write_text("".join(keep))
        if delete_files and lib.path.is_dir():
            shutil.rmtree(lib.path)

    def xschem_library_path(self) -> list[Path]:
        """Directories xschem must search so that ``<lib>/<cell>/<cell>.sym`` resolves."""

        out: list[Path] = []
        for lib in self.libraries(include_pdk=False):
            parent = lib.path.parent
            if parent not in out:
                out.append(parent)
        return out

    # --- cells -----------------------------------------------------------

    def cells(self, lib: Library | str) -> list[str]:
        if isinstance(lib, str):
            lib = self.library(lib)
        if not lib.path.is_dir():
            return []
        if lib.flat:
            names = set()
            for d in (lib.path, *lib.extra_dirs):
                if d.is_dir():
                    for f in d.iterdir():
                        if f.suffix in (".sym", ".sch") and f.is_file():
                            names.add(f.stem)
            return sorted(names)
        return sorted(d.name for d in lib.path.iterdir()
                      if d.is_dir() and not d.name.startswith("."))

    def cell_dir(self, lib: Library | str, cell: str) -> Path:
        if isinstance(lib, str):
            lib = self.library(lib)
        return lib.path if lib.flat else lib.path / cell

    def view_path(self, lib: Library | str, cell: str, kind: str) -> Path:
        if isinstance(lib, str):
            lib = self.library(lib)
        suffix = KIND_BY_NAME[kind].suffix
        if lib.flat:
            for d in (lib.path, *lib.extra_dirs):
                p = d / f"{cell}{suffix}"
                if p.exists():
                    return p
            return lib.path / f"{cell}{suffix}"
        return lib.path / cell / f"{cell}{suffix}"

    def views(self, lib: Library | str, cell: str) -> list[View]:
        if isinstance(lib, str):
            lib = self.library(lib)
        views: list[View] = []
        for kind in VIEW_KINDS:
            p = self.view_path(lib, cell, kind.name)
            if p.is_file():
                views.append(View(kind.name, p))
        if lib.flat and lib.layout_file and lib.layout_file.is_file():
            views.append(View("layout", lib.layout_file, cell_in_file=cell))
        if not lib.flat:
            # Extra testbench-style schematics in the cell dir (tb_*.sch etc.)
            for f in sorted(self.cell_dir(lib, cell).glob("*.sch")):
                if f.stem != cell:
                    views.append(View("schematic", f))
        views += self.derived_views(lib, cell)
        return views

    def derived_views(self, lib: Library | str, cell: str) -> list[View]:
        if isinstance(lib, str):
            lib = self.library(lib)
        out = []
        for kind, rel in (("netlist", Path("sim") / lib.name / cell / f"{cell}.spice"),
                          ("lvs_netlist", Path("verif") / lib.name / cell / "lvs" / f"{cell}.cdl"),
                          ("extracted", Path("verif") / lib.name / cell / "lvs" / f"{cell}_extracted.cir"),
                          ("pex", Path("verif") / lib.name / cell / "pex" / f"{cell}_pex.spice")):
            found = [r / rel for r in self._result_roots() if (r / rel).is_file()]
            if found:
                out.append(View(kind, max(found, key=lambda p: p.stat().st_mtime), derived=True))
        osdi = self.cell_dir(lib, cell) / f"{cell}.osdi"
        if osdi.is_file():
            out.append(View("osdi", osdi, derived=True))
        return out

    def new_cell(self, lib: str, cell: str) -> Path:
        cell = check_name(cell, "cell name")
        library = self.library(lib)
        if library.readonly:
            raise PermissionError(f"library '{lib}' is read only")
        d = library.path / cell
        if d.exists():
            raise ValueError(f"cell '{lib}/{cell}' already exists")
        d.mkdir(parents=True)
        return d

    def delete_cell(self, lib: str, cell: str) -> None:
        library = self.library(lib)
        if library.readonly:
            raise PermissionError(f"library '{lib}' is read only")
        shutil.rmtree(library.path / cell)
        for sub in (self.sim_dir(lib, cell), self.run_root / "verif" / lib / cell):
            if sub.is_dir():
                shutil.rmtree(sub, ignore_errors=True)

    def copy_cell(self, src_ws: "Workspace", src_lib: str, cell: str,
                  dst_lib: str, new_cell: str | None = None) -> Path:
        """Copy a cell (from any workspace, PDK libraries included) into this one."""

        new_cell = check_name(new_cell or cell, "cell name")
        src = src_ws.library(src_lib)
        dst = self.library(dst_lib)
        if dst.readonly:
            raise PermissionError(f"library '{dst_lib}' is read only")
        target = dst.path / new_cell
        if target.exists():
            raise ValueError(f"cell '{dst_lib}/{new_cell}' already exists")
        target.mkdir(parents=True)
        if src.flat:
            for v in src_ws.views(src, cell):
                if v.derived or v.cell_in_file:
                    continue
                shutil.copy2(v.path, target / f"{new_cell}{v.path.suffix}")
            if src.layout_file and src.layout_file.is_file():
                from . import templates
                templates.extract_gds_cell(src.layout_file, cell, target / f"{new_cell}.gds", new_cell)
        else:
            for f in (src.path / cell).iterdir():
                name = f.name
                # cell.sch, cell.simenv.json, ... -> new_cell.sch, new_cell.simenv.json, ...
                if name.startswith(cell + "."):
                    name = new_cell + name[len(cell):]
                if f.is_dir():
                    shutil.copytree(f, target / name)
                else:
                    shutil.copy2(f, target / name)
        if new_cell != cell or src_lib != dst_lib:
            # The copy's own schematic may show its own symbol (e.g. in a
            # testbench next to it): point those at the copy.
            self.replace_references(f"{src_lib}/{cell}/{cell}.sym",
                                    f"{dst_lib}/{new_cell}/{new_cell}.sym", only_dir=target)
            gds = target / f"{new_cell}.gds"
            if gds.exists() and new_cell != cell:
                from . import templates
                templates.rename_gds_cell(gds, cell, new_cell)
        return target

    def rename_cell(self, lib: str, cell: str, new_cell: str) -> Path:
        target = self.copy_cell(self, lib, cell, lib, new_cell)
        self.replace_references(f"{lib}/{cell}/{cell}.sym", f"{lib}/{new_cell}/{new_cell}.sym")
        self.delete_cell(lib, cell)
        return target

    def replace_references(self, old: str, new: str, only_dir: Path | None = None) -> list[Path]:
        """Point every schematic instance of symbol ``old`` at ``new``."""

        changed = []
        dirs = [only_dir] if only_dir else [lib.path for lib in self.libraries(include_pdk=False)
                                             if not lib.readonly]
        pat = re.compile(r"^(C \{)" + re.escape(old) + r"(\})", re.M)
        for d in dirs:
            for sch in Path(d).rglob("*.sch"):
                text = sch.read_text(errors="replace")
                new_text = pat.sub(lambda m: m.group(1) + new + m.group(2), text)
                if new_text != text:
                    sch.write_text(new_text)
                    changed.append(sch)
        return changed

    # --- run directories and status ---------------------------------------

    def sim_dir(self, lib: str, cell: str) -> Path:
        return self.run_root / "sim" / lib / cell

    def run_dir(self, lib: str, cell: str, flow: str) -> Path:
        return self.run_root / "verif" / lib / cell / flow

    def _result_roots(self) -> list[Path]:
        """Where results may be: our own run area first, then (for a supervisor
        browsing a student) the student's own runs."""

        return [self.run_root] if self.run_root == self.root else [self.run_root, self.root]

    def status(self, lib: str, cell: str) -> CellStatus:
        st = CellStatus()
        for root in self._result_roots():
            files = {flow: root / "verif" / lib / cell / flow / "status.json"
                     for flow in ("drc", "lvs", "pex")}
            files["sim"] = root / "sim" / lib / cell / "status.json"
            for flow, f in files.items():
                if not f.is_file():
                    continue
                try:
                    r = json.loads(f.read_text())
                except (ValueError, OSError):
                    continue
                if r.get("time", 0) > st.results.get(flow, {}).get("time", 0):
                    st.results[flow] = r
        return st

    # --- locating files ----------------------------------------------------

    def locate(self, path: Path) -> tuple[Library, str] | None:
        """Which (library, cell) does a file belong to?"""

        path = Path(path).resolve()
        for lib in self.libraries():
            for d in (lib.path, *lib.extra_dirs):
                try:
                    rel = path.relative_to(d.resolve())
                except ValueError:
                    continue
                if lib.flat:
                    return lib, path.stem
                if rel.parts:
                    return lib, rel.parts[0]
        # A simulation or verification run of a cell
        for top in ("sim", "verif"):
            try:
                rel = path.relative_to((self.run_root / top).resolve())
            except ValueError:
                continue
            if len(rel.parts) >= 2:
                try:
                    return self.library(rel.parts[0]), rel.parts[1]
                except KeyError:
                    return None
        return None

    def last_modified(self) -> float:
        newest = 0.0
        for lib in self.own_libraries():
            if not lib.path.is_dir():
                continue
            for f in lib.path.rglob("*"):
                try:
                    newest = max(newest, f.stat().st_mtime)
                except OSError:
                    pass
        return newest


def fmt_time(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else "-"
