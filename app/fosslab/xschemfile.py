"""Read xschem .sch/.sym files and write simple ones.

Only what the manager needs: instances (for the hierarchy), pins (to make
a symbol from a schematic), the global K {...} properties of a symbol (its
type), and writing templates. xschem itself does all real editing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

XSCHEM_VERSION_LINE = "v {xschem version=3.4.8RC file_version=1.2}"

# Number of {...} groups that close each object type.
_BRACES = {"C": 2, "T": 2}


def _tokens(text: str):
    """Yield ('brace', content) or ('word', text) tokens."""

    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c == "{":
            depth, j, buf = 1, i + 1, []
            while j < n and depth:
                ch = text[j]
                if ch == "\\" and j + 1 < n:
                    buf.append(text[j:j + 2])
                    j += 2
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        break
                buf.append(ch)
                j += 1
            yield "brace", "".join(buf)
            i = j + 1
        elif c in "[]":
            yield "word", c
            i += 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in "{}[]":
                j += 1
            yield "word", text[i:j]
            i = j


@dataclass
class XObject:
    type: str
    words: list[str] = field(default_factory=list)
    braces: list[str] = field(default_factory=list)

    @property
    def props(self) -> dict[str, str]:
        return parse_props(self.braces[-1]) if self.braces else {}


def parse(text: str) -> list[XObject]:
    objs: list[XObject] = []
    cur: XObject | None = None
    depth_embedded = 0
    for kind, val in _tokens(text):
        if kind == "word" and val == "[":
            depth_embedded += 1          # an embedded symbol: skip its contents
            continue
        if kind == "word" and val == "]":
            depth_embedded = max(0, depth_embedded - 1)
            continue
        if depth_embedded:
            continue
        if cur is None:
            if kind == "word" and len(val) == 1 and val.isalpha():
                cur = XObject(val)
            continue
        if kind == "brace":
            cur.braces.append(val)
            if len(cur.braces) >= _BRACES.get(cur.type, 1):
                objs.append(cur)
                cur = None
        else:
            cur.words.append(val)
    return objs


def parse_file(path: Path) -> list[XObject]:
    return parse(Path(path).read_text(errors="replace"))


def parse_props(s: str) -> dict[str, str]:
    """``name=M1 w=1u value="a b"`` -> dict. Handles quotes and escapes."""

    props: dict[str, str] = {}
    i, n = 0, len(s)
    while i < n:
        while i < n and s[i].isspace():
            i += 1
        j = i
        while j < n and s[j] not in "=" and not s[j].isspace():
            j += 1
        key = s[i:j]
        if not key:
            break
        if j >= n or s[j] != "=":
            props[key] = ""
            i = j
            continue
        j += 1
        if j < n and s[j] == '"':
            j += 1
            buf = []
            while j < n and s[j] != '"':
                if s[j] == "\\" and j + 1 < n:
                    buf.append(s[j + 1])
                    j += 2
                    continue
                buf.append(s[j])
                j += 1
            props[key] = "".join(buf)
            i = j + 1
        else:
            k = j
            while k < n and not s[k].isspace():
                k += 1
            props[key] = s[j:k]
            i = k
    return props


@dataclass
class Instance:
    name: str
    symbol: str          # as written in the schematic, e.g. sg13g2_pr/sg13_lv_nmos.sym
    props: dict[str, str]


def instances(path: Path) -> list[Instance]:
    out = []
    for o in parse_file(path):
        if o.type == "C" and o.braces:
            props = o.props
            out.append(Instance(props.get("name", "?"), o.braces[0].strip(), props))
    return out


def symbol_props(path: Path) -> dict[str, str]:
    for o in parse_file(path):
        if o.type in ("K", "G") and o.braces and o.braces[0].strip():
            return parse_props(o.braces[0])
    return {}


PIN_SYMBOLS = {"ipin.sym": "in", "opin.sym": "out", "iopin.sym": "inout"}


@dataclass
class Pin:
    name: str
    dir: str


def schematic_pins(path: Path) -> list[Pin]:
    pins, seen = [], set()
    for inst in instances(path):
        base = inst.symbol.rsplit("/", 1)[-1]
        if base in PIN_SYMBOLS:
            lab = inst.props.get("lab", "")
            for name in [x for x in lab.split(",") if x]:
                if name not in seen:
                    seen.add(name)
                    pins.append(Pin(name, PIN_SYMBOLS[base]))
    return pins


# --- writing ----------------------------------------------------------------

def _q(value: str) -> str:
    """A property value as xschem writes it: quoted, with \\, " and braces escaped."""

    for a, b in (("\\", "\\\\"), ('"', '\\"'), ("{", "\\{"), ("}", "\\}")):
        value = value.replace(a, b)
    return '"' + value + '"'


POWER = re.compile(r"^(A|D)?(VDD|VCC|VPWR|VDDA|VDDD|VPP)\w*$", re.I)
GROUND = re.compile(r"^(A|D)?(VSS|GND|VGND|VSSA|VSSD|VEE|VNN)\w*$", re.I)


def symbol_from_pins(cell: str, pins: list[Pin]) -> str:
    """A box symbol: inputs left, outputs right, supplies top/bottom."""

    left = [p for p in pins if p.dir == "in" or
            (p.dir == "inout" and not POWER.match(p.name) and not GROUND.match(p.name))]
    right = [p for p in pins if p.dir == "out"]
    top = [p for p in pins if p.dir == "inout" and POWER.match(p.name)]
    bottom = [p for p in pins if p.dir == "inout" and GROUND.match(p.name)]

    rows = max(len(left), len(right), 1)
    cols = max(len(top), len(bottom), 1)
    h = 20 * rows + 20              # half-height
    w = max(60, 20 * cols + 20)     # half-width
    h = 10 * round(h / 10)
    w = 10 * round(w / 10)

    lines = [XSCHEM_VERSION_LINE, "G {}",
             "K {type=subcircuit\nformat=\"@name @pinlist @symname\"\ntemplate=\"name=x1\"\n}",
             "V {}", "S {}", "E {}",
             f"L 4 {-w} {-h} {w} {-h} {{}}", f"L 4 {w} {-h} {w} {h} {{}}",
             f"L 4 {w} {h} {-w} {h} {{}}", f"L 4 {-w} {h} {-w} {-h} {{}}"]

    for p, y in zip(left, _spread(len(left), h)):
        lines += [f"L 4 {-w - 20} {y} {-w} {y} {{}}",
                  f"B 5 {-w - 22.5} {y - 2.5} {-w - 17.5} {y + 2.5} {{name={p.name} dir={p.dir}}}",
                  f"T {{{p.name}}} {-w + 5} {y - 6} 0 0 0.2 0.2 {{}}"]
    for p, y in zip(right, _spread(len(right), h)):
        lines += [f"L 4 {w} {y} {w + 20} {y} {{}}",
                  f"B 5 {w + 17.5} {y - 2.5} {w + 22.5} {y + 2.5} {{name={p.name} dir={p.dir}}}",
                  f"T {{{p.name}}} {w - 5} {y - 6} 0 1 0.2 0.2 {{}}"]
    for p, x in zip(top, _spread(len(top), w)):
        lines += [f"L 4 {x} {-h - 20} {x} {-h} {{}}",
                  f"B 5 {x - 2.5} {-h - 22.5} {x + 2.5} {-h - 17.5} {{name={p.name} dir={p.dir}}}",
                  f"T {{{p.name}}} {x + 4} {-h + 4} 0 0 0.2 0.2 {{}}"]
    for p, x in zip(bottom, _spread(len(bottom), w)):
        lines += [f"L 4 {x} {h} {x} {h + 20} {{}}",
                  f"B 5 {x - 2.5} {h + 17.5} {x + 2.5} {h + 22.5} {{name={p.name} dir={p.dir}}}",
                  f"T {{{p.name}}} {x + 4} {h - 16} 0 0 0.2 0.2 {{}}"]
    lines += [f"T {{@symname}} {-w} {-h - 30} 0 0 0.25 0.25 {{}}",
              f"T {{@name}} {-w} {h + 8} 0 0 0.2 0.2 {{}}"]
    return "\n".join(lines) + "\n"


def _spread(count: int, half: int) -> list[int]:
    """Evenly spaced positions on a 20-unit grid, centred on 0."""

    if count == 0:
        return []
    step = 40 if 40 * (count - 1) <= 2 * half - 20 else 20
    start = -step * (count - 1) / 2
    return [int(10 * round((start + step * i) / 10)) for i in range(count)]


def empty_schematic(extra: str = "") -> str:
    return "\n".join([XSCHEM_VERSION_LINE, "G {}", "K {}", "V {}", "S {}", "E {}"]) + "\n" + extra


def instance_line(symbol: str, x: int, y: int, props: dict[str, str], rot: int = 0, flip: int = 0) -> str:
    def fmt(v: str) -> str:
        return _q(v) if any(c in v for c in ' \n"{}') else v

    body = " ".join(f"{k}={fmt(v)}" for k, v in props.items())
    return f"C {{{symbol}}} {x} {y} {rot} {flip} {{{body}}}"


# --- building schematics from a netlist ------------------------------------------

def symbol_pins(sym_path: Path) -> list[tuple[str, float, float]]:
    """(pin name, x, y) of each pin hotspot of a symbol, in symbol coordinates."""

    pins = []
    for o in parse_file(sym_path):
        if o.type == "B" and len(o.words) >= 5 and o.words[0] == "5":
            x1, y1, x2, y2 = (float(w) for w in o.words[1:5])
            pins.append((o.props.get("name", ""), (x1 + x2) / 2, (y1 + y2) / 2))
    return pins


class SchematicBuilder:
    """Place instances and connect their pins by net labels (no wires needed:
    xschem connects every label with the same name). Rotation 0 only."""

    def __init__(self, resolve):
        self.resolve = resolve          # symbol ref -> Path of the .sym
        self.lines: list[str] = []
        self._n = 0

    def _label(self, x: float, y: float, net: str, left: bool) -> None:
        self._n += 1
        self.lines.append(instance_line("lab_pin.sym", int(x), int(y),
                                        {"name": f"l{self._n}", "sig_type": "std_logic", "lab": net},
                                        flip=0 if left else 1))

    def device(self, symbol: str, x: int, y: int, props: dict[str, str], nets: dict[str, str],
               stub: int = 40) -> None:
        """Place a symbol; each connected pin gets a short wire pointing away
        from the symbol, with the net label at its end (no clash with the
        symbol's own texts)."""

        sym = self.resolve(symbol)
        if sym is None:
            raise FileNotFoundError(f"symbol {symbol} not found")
        self.lines.append(instance_line(symbol, x, y, props))
        pins = symbol_pins(sym)
        for name, px, py in pins:
            if name not in nets:
                continue
            x1, y1 = x + px, y + py
            if abs(px) >= abs(py):                       # side pin: horizontal stub
                # a 4-terminal device's bulk (right side, middle): longer, past the parameter texts
                length = stub * 2 if (px > 0 and py == 0 and len(pins) >= 4) else stub
                x2, y2 = (x1 + length, y1) if px > 0 else (x1 - length, y1)
            else:                                        # top/bottom pin: vertical stub
                x2, y2 = (x1, y1 - stub) if py < 0 else (x1, y1 + stub)
            self.lines.append(f"N {int(x1)} {int(y1)} {int(x2)} {int(y2)} {{lab={nets[name]}}}")
            self._label(x2, y2, nets[name], left=x2 <= x1 and not (x2 == x1 and px > 0))

    def pin(self, kind: str, x: int, y: int, net: str) -> None:
        """kind: ipin, opin or iopin."""

        self._n += 1
        self.lines.append(instance_line(f"{kind}.sym", x, y, {"name": f"p{self._n}", "lab": net},
                                        flip=1 if kind == "opin" else 0))

    def code(self, x: int, y: int, name: str, value: str, models: bool = False) -> None:
        props = {"name": name, "only_toplevel": "true"}
        if models:
            props["format"] = "tcleval( @value )"
        props["value"] = value
        self.lines.append(instance_line("devices/code_shown.sym", x, y, props))

    def text(self) -> str:
        return empty_schematic("\n".join(self.lines) + "\n")
