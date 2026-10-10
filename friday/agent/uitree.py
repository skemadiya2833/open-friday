"""Parse the text that Windows-MCP's ``Snapshot`` tool returns.

Format reference: windows-mcp 0.8.7 ``tools/_snapshot_helpers.build_snapshot_response`` and
``tree/views.py`` (read from the pinned package). The sections are::

    Cursor Position / Screenshot Size / Visible Displays ...
    Focused Window:  <tabulate table: Name Depth Status Width Height Handle>
    Opened Windows:  <same table>
    UI Tree:
    desktop
    └── window "Untitled - Notepad"
        ├── (812,420) edit "Text editor"  [action: fill]  [focused]
        └── (80,40) menu item "File"  [action: click]

Windows-MCP accepts a ``label`` (an index into an internal interactive-node list) but never
prints it, so this parser assigns *its own* ids, and the agent turns an id into the element's
printed centre coordinate. Everything here is treated as UNTRUSTED text: it is only parsed,
never interpreted as instructions.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

_ROW = re.compile(
    r"^(?P<name>.*?)\s{2,}(?P<depth>\d+)\s+(?P<status>Maximized|Minimized|Normal|Hidden)\s+"
    r"(?P<w>\d+)\s+(?P<h>\d+)\s+(?P<handle>\d+)\s*$"
)
_ELEM = re.compile(
    r'^(?P<prefix>[│ ├└─\s]*)\((?P<x>-?\d+),(?P<y>-?\d+)\)\s+(?P<type>[^"]+?)\s+"(?P<name>.*)"\s+'
    r"\[action:\s*(?P<action>[\w-]+)\](?P<meta>.*)$"
)
_NODE_START = re.compile(r'^[│ ├└─\s]*(\(-?\d+,-?\d+\)\s+)?[A-Za-z][\w ]*\s+"')
_TEXT = re.compile(r'^[│ ├└─\s]*text\s+"(?P<name>.*)"\s*$')
_WIN = re.compile(r'^(?P<prefix>[│ ├└─\s]*)window "(?P<name>.*)"\s*$')
_META = re.compile(r"\[([^\]]*)\]")
_DISPLAY = re.compile(r"(\d+):(\S+)\s+\((-?\d+),(-?\d+),(-?\d+),(-?\d+)\)(\s+primary)?")


@dataclass
class Win:
    name: str
    status: str
    width: int
    height: int
    handle: int


@dataclass
class Element:
    id: int
    window: str
    ctype: str
    name: str
    x: int
    y: int
    action: str
    meta: list[str] = field(default_factory=list)
    scrollable: bool = False

    @property
    def focused(self) -> bool:
        return "focused" in self.meta

    @property
    def password(self) -> bool:
        return "password" in self.meta

    @property
    def value(self) -> str:
        for m in self.meta:
            if m.startswith('value:"'):
                return m[7:-1]
        return ""

    def line(self) -> str:
        extra = f" [{', '.join(self.meta)}]" if self.meta else ""
        nm = self.name if len(self.name) <= 80 else self.name[:77] + "..."
        return f'{self.id}: {self.ctype} "{nm}" ({self.action}){extra}'


@dataclass
class Snapshot:
    raw: str = ""
    focused: Win | None = None
    windows: list[Win] = field(default_factory=list)
    elements: list[Element] = field(default_factory=list)
    displays: list[dict] = field(default_factory=list)
    screenshot_scale: float = 1.0
    truncated: bool = False
    texts: list[tuple[str, str]] = field(default_factory=list)     # (window, text) of non-interactive text nodes
    has_image: bool = False
    image_b64: str | None = None

    def by_id(self, element_id: int) -> Element | None:
        for e in self.elements:
            if e.id == element_id:
                return e
        return None

    def focused_title(self) -> str:
        return self.focused.name if self.focused else ""

    def fingerprint(self) -> str:
        """Stable hash of what the user can see; used for post-action verification."""
        parts = [self.focused_title()]
        parts += [f"{e.window}|{e.ctype}|{e.name}|{e.value}|{e.meta}" for e in self.elements[:300]]
        parts += [f"text|{w}|{t}" for w, t in self.texts[:300]]
        return hashlib.sha1("\n".join(parts).encode("utf-8", "replace")).hexdigest()[:16]

    def visible_text(self) -> str:
        """Everything text-like on screen, for evidence checks."""
        bits = [self.focused_title(), *[w.name for w in self.windows], *[t for _, t in self.texts]]
        for e in self.elements:
            bits.append(e.name)
            if e.value:
                bits.append(e.value)
        return "\n".join(b for b in bits if b)


def _section(text: str, header: str, nxt: tuple[str, ...]) -> str:
    m = re.search(rf"^[ \t]*{re.escape(header)}[ \t]*$", text, re.M)
    if not m:
        return ""
    rest = text[m.end():]
    ends = [mm.start() for n in nxt if (mm := re.search(rf"^[ \t]*{re.escape(n)}\s*$", rest, re.M))]
    return rest[: min(ends)] if ends else rest


def _parse_windows(block: str) -> list[Win]:
    out: list[Win] = []
    for ln in block.splitlines():
        m = _ROW.match(ln.rstrip())
        if m:
            out.append(Win(m["name"].strip(), m["status"], int(m["w"]), int(m["h"]), int(m["handle"])))
    return out


def normalize(text: str) -> str:
    """Live Windows-MCP returns the report as a JSON array of strings inside one text block
    (verified live 2026-10-06, docs/research/live_snapshot_sample.txt); unwrap it."""
    t = text.lstrip()
    if t.startswith("[") and t.rstrip().endswith("]"):
        try:
            data = json.loads(t)
        except ValueError:
            return text
        if isinstance(data, list) and data and all(isinstance(x, str) for x in data):
            return "\n".join(data)
    return text


def join_multiline_nodes(tree: str, max_extra: int = 8) -> list[str]:
    """Windows-MCP prints element names verbatim, so a name with a line break spans several lines.
    A node line is complete when it ends with `]` (interactive: ... [action: x]) or `"` (text node);
    a node line that is not complete takes the following lines until it is."""
    out: list[str] = []
    pending: str | None = None
    extra = 0
    for ln in tree.splitlines():
        if pending is not None:
            pending += " " + ln.strip()
            extra += 1
            if ln.rstrip().endswith(("]", "\"")) or extra >= max_extra:
                out.append(pending)
                pending = None
            continue
        s = ln.rstrip()
        if _NODE_START.match(s) and not s.endswith(("]", "\"")):
            pending, extra = s, 0
            continue
        out.append(ln)
    if pending is not None:
        out.append(pending)
    return out


def parse_snapshot(text: str, *, max_elements: int = 400) -> Snapshot:
    text = normalize(text)
    s = Snapshot(raw=text)
    focused = _parse_windows(_section(text, "Focused Window:", ("Opened Windows:", "UI Tree:")))
    s.focused = focused[0] if focused else None
    s.windows = _parse_windows(_section(text, "Opened Windows:", ("UI Tree:",)))

    mscale = re.search(r"Screenshot Coordinate Scale:\s*([\d.]+)", text)
    if mscale:
        s.screenshot_scale = float(mscale.group(1))
    mdisp = re.search(r"^[ \t]*Visible Displays:\s*(.*)$", text, re.M)
    if mdisp:
        for d in _DISPLAY.finditer(mdisp.group(1)):
            s.displays.append({
                "index": int(d[1]), "name": d[2],
                "box": [int(d[3]), int(d[4]), int(d[5]), int(d[6])], "primary": bool(d[7]),
            })

    mt = re.search(r"^[ \t]*UI Tree:\s*$", text, re.M)
    tree = text[mt.end():] if mt else ""
    s.truncated = "[truncated:" in tree
    window = ""
    for ln in join_multiline_nodes(tree):
        w = _WIN.match(ln)
        if w:
            window = w["name"]
            continue
        e = _ELEM.match(ln)
        if not e:
            tm = _TEXT.match(ln)
            if tm and len(s.texts) < 300 and tm["name"].strip():
                s.texts.append((window, tm["name"].strip()))
            continue
        meta = [m.strip() for m in _META.findall(e["meta"])]
        s.elements.append(Element(
            id=len(s.elements), window=window, ctype=e["type"].strip().lower(), name=e["name"],
            x=int(e["x"]), y=int(e["y"]), action=e["action"], meta=meta,
            scrollable=("v:" in e["meta"] or "h:" in e["meta"]),
        ))
        if len(s.elements) >= max_elements:
            s.truncated = True
            break
    return s


def render_for_model(s: Snapshot, *, max_elements: int = 120) -> str:
    """Compact, clearly delimited observation. The delimiters mark it as data."""
    lines = []
    if s.focused:
        lines.append(f'focused_window: "{s.focused.name}" ({s.focused.status})')
    others = [w for w in s.windows if not s.focused or w.handle != s.focused.handle]
    if others:
        lines.append("other_windows: " + "; ".join(f'"{w.name}"' for w in others[:10]))
    # Elements of the focused window first: that is where actions will land.
    ft = s.focused.name if s.focused else None
    ordered = [e for e in s.elements if e.window == ft] + [e for e in s.elements if e.window != ft]
    for e in ordered[:max_elements]:
        lines.append(e.line())
    shown = [t for w, t in s.texts if not ft or w == ft][:40]
    if shown:
        lines.append("page_text: " + " | ".join(t[:80] for t in shown))
    if len(s.elements) > max_elements:
        lines.append(f"... {len(s.elements) - max_elements} more elements not shown")
    if s.truncated:
        lines.append("... tree truncated by the capture limit")
    return "\n".join(lines) if lines else "(no accessibility elements found)"
