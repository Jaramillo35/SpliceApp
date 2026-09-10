"""Record the structure of DEF Editor's windows, without their contents.

The automation was written against a sanitized description of the
application: control names, no tree. That is enough to name a control and
not enough to *find* it — ``child_window(auto_id=...)`` with no control type
can land on a sibling, which is how the Vehicle field came to be offered
"Phase" and "Close". What is missing is the real UI Automation tree, and this
module records it so the tree can be read where the application is not.

What a snapshot holds, per element: control type, AutomationId, class name,
rectangle, enabled / visible, and the parent–child structure. **Names are
recorded only for controls whose name is part of the interface** — buttons,
menu items, tabs, headers, checkboxes, windows — because a grid cell's name
IS the cell's value, an edit's name is what was typed, a list item's name is
the item. For those, only the *shape* is kept: length and character class
(``"3 upper/digit"``), which is enough to recognise a sales-code column and
nothing else. Grids record their column headers and their row count, and
descend into the first two rows only, for shape. ``redact=False`` exists for
running against a test instance; the default is on.

Snapshots are written as JSON, one file per snapshot, with an ``index.md``
beside them, so a folder of them can be pushed to a repository and read.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, List, Optional

#: control types whose Name is interface, not data
NAMED_TYPES = {
    "Window", "Pane", "Button", "MenuBar", "Menu", "MenuItem", "TabItem", "Tab",
    "Header", "HeaderItem", "CheckBox", "RadioButton", "ToolBar", "StatusBar",
    "TitleBar", "Group", "Hyperlink", "SplitButton", "Separator", "ScrollBar",
    "Thumb", "Spinner", "ToolTip",
}
#: control types whose Name is data (or might be): shape only
DATA_TYPES = {"DataItem", "DataGrid", "Edit", "Document", "Text", "ListItem",
              "List", "ComboBox", "Custom", "Image", "TreeItem", "Table"}

MAX_DEPTH = 14
MAX_NODES = 6000
GRID_ROWS_TO_DESCEND = 2


def shape_of(text: str) -> str:
    """The shape of a value, never the value: length and character class."""
    text = (text or "").strip()
    if not text:
        return "empty"
    if re.fullmatch(r"[0-9]+", text):
        cls = "digits"
    elif re.fullmatch(r"[A-Z0-9]+", text):
        cls = "upper/digit"
    elif re.fullmatch(r"[A-Za-z ]+", text):
        cls = "letters"
    else:
        cls = "mixed"
    lines = text.count("\n") + 1
    return f"{len(text)} {cls}" + (f", {lines} lines" if lines > 1 else "")


@dataclass
class Node:
    """One element of the tree, as recorded."""

    control_type: str = ""
    automation_id: str = ""
    class_name: str = ""
    name: str = ""              # interface names only; see module docstring
    name_shape: str = ""        # for data-carrying controls
    rect: List[int] = field(default_factory=list)   # left, top, right, bottom
    enabled: Optional[bool] = None
    visible: Optional[bool] = None
    row_count: Optional[int] = None                 # DataGrid / List / Table
    headers: List[str] = field(default_factory=list)  # DataGrid column headers
    truncated: str = ""         # why children were not all recorded
    children: List["Node"] = field(default_factory=list)


class Element:
    """What the walker needs from an element — a tiny adapter so the walk is
    testable over an invented tree and the same over pywinauto wrappers."""

    control_type: str
    automation_id: str
    class_name: str
    name: str
    rect: List[int]
    enabled: Optional[bool]
    visible: Optional[bool]

    def children(self) -> List["Element"]:   # pragma: no cover - protocol
        raise NotImplementedError


def _describe(element: Element, redact: bool) -> Node:
    ctype = element.control_type or ""
    name = element.name or ""
    node = Node(control_type=ctype, automation_id=element.automation_id or "",
                class_name=element.class_name or "", rect=list(element.rect or []),
                enabled=element.enabled, visible=element.visible)
    if not redact or ctype in NAMED_TYPES:
        node.name = name
    else:
        node.name_shape = shape_of(name)
    return node


def walk(element: Element, redact: bool = True, max_depth: int = MAX_DEPTH,
         max_nodes: int = MAX_NODES) -> Node:
    """The tree under ``element``, capped in depth and size.

    A DataGrid with two thousand rows is two thousand DataItems each with
    ninety cells; recording it all is slow and records nothing but data. The
    grid's headers and row count are kept, and the first two rows are
    descended for their shape.
    """
    budget = {"nodes": 0}

    def visit(el: Element, depth: int) -> Node:
        budget["nodes"] += 1
        node = _describe(el, redact)
        if depth >= max_depth:
            node.truncated = f"depth {max_depth}"
            return node
        if budget["nodes"] >= max_nodes:
            node.truncated = f"{max_nodes} nodes"
            return node
        try:
            kids = list(el.children())
        except Exception as exc:  # noqa: BLE001 - an element may vanish mid-walk
            node.truncated = f"children unavailable: {type(exc).__name__}"
            return node
        if node.control_type in ("DataGrid", "Table", "List"):
            rows = [k for k in kids if (k.control_type or "") in ("DataItem", "ListItem")]
            others = [k for k in kids if k not in rows]
            node.row_count = len(rows)
            for header in others:
                if (header.control_type or "") in ("Header", "HeaderItem"):
                    node.headers.extend(
                        h.name for h in ([header] + list(_safe_children(header)))
                        if (h.control_type or "") == "HeaderItem" and h.name)
            kids = others + rows[:GRID_ROWS_TO_DESCEND]
            if len(rows) > GRID_ROWS_TO_DESCEND:
                node.truncated = (f"{len(rows)} rows; first {GRID_ROWS_TO_DESCEND} "
                                  "recorded for shape")
        for kid in kids:
            node.children.append(visit(kid, depth + 1))
            if budget["nodes"] >= max_nodes:
                break
        return node

    return visit(element, 0)


def _safe_children(el: Element) -> Iterable[Element]:
    try:
        return list(el.children())
    except Exception:  # noqa: BLE001
        return []


# ---------------------------------------------------------------- pywinauto
class UiaElement(Element):
    """A pywinauto wrapper seen through the adapter."""

    def __init__(self, wrapper) -> None:
        self._w = wrapper
        info = wrapper.element_info
        self.control_type = getattr(info, "control_type", "") or ""
        self.automation_id = getattr(info, "automation_id", "") or ""
        self.class_name = getattr(info, "class_name", "") or ""
        self.name = getattr(info, "name", "") or ""
        try:
            r = info.rectangle
            self.rect = [int(r.left), int(r.top), int(r.right), int(r.bottom)]
        except Exception:  # noqa: BLE001
            self.rect = []
        try:
            self.enabled = bool(wrapper.is_enabled())
            self.visible = bool(wrapper.is_visible())
        except Exception:  # noqa: BLE001
            self.enabled = self.visible = None

    def children(self) -> List["UiaElement"]:
        return [UiaElement(c) for c in self._w.children()]


def process_windows(pid: int) -> List:
    """Every top-level window of a process — DEF Editor is MDI and opens
    forms as separate windows."""
    from pywinauto import Desktop  # noqa: PLC0415 - Windows only

    out = []
    for w in Desktop(backend="uia").windows():
        try:
            if int(w.process_id()) == int(pid):
                out.append(w)
        except Exception:  # noqa: BLE001
            continue
    return out


def signature(windows: List) -> str:
    """A cheap fingerprint of the desktop state, for the auto-snapshot: the
    windows' titles and, where it can be read, the focused element."""
    parts = []
    for w in windows:
        try:
            parts.append(w.window_text())
        except Exception:  # noqa: BLE001
            continue
    try:
        from pywinauto import Desktop  # noqa: PLC0415

        focused = Desktop(backend="uia").get_active()
        parts.append(getattr(focused.element_info, "automation_id", "") or "")
    except Exception:  # noqa: BLE001
        pass
    return " | ".join(parts)


# ------------------------------------------------------------------ record
@dataclass
class Snapshot:
    taken_at: str
    label: str
    redacted: bool
    windows: List[dict]
    notes: List[str] = field(default_factory=list)


def take(roots: List[Element], label: str, redact: bool = True,
         titles: Optional[List[str]] = None) -> Snapshot:
    windows = []
    for i, root in enumerate(roots):
        tree = walk(root, redact=redact)
        windows.append({"title": (titles[i] if titles and i < len(titles)
                                  else tree.name), "tree": asdict(tree)})
    return Snapshot(taken_at=datetime.now().isoformat(timespec="seconds"),
                    label=label, redacted=redact, windows=windows)


def save(snapshot: Snapshot, out_dir: Path | str) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", snapshot.label).strip("_") or "snapshot"
    path = out / f"{stamp}_{safe}.json"
    path.write_text(json.dumps(asdict(snapshot), indent=1), encoding="utf-8")
    _index(out)
    return path


def _index(out: Path) -> None:
    """``index.md``: one line per snapshot, so a folder of them reads at a
    glance on GitHub."""
    lines = ["# DEF Editor structure snapshots", "",
             "Recorded by the automation kit. Redacted: control types, ids and "
             "layout only — no cell values, no typed text.", ""]
    for path in sorted(out.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        n = sum(_count(w["tree"]) for w in data.get("windows", []))
        titles = ", ".join(w.get("title", "") for w in data.get("windows", []))
        lines.append(f"- `{path.name}` — {data.get('label', '')} — "
                     f"{len(data.get('windows', []))} window(s), {n} element(s)"
                     + (f" — {titles}" if titles else "")
                     + ("" if data.get("redacted", True) else " — **UNREDACTED**"))
    (out / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _count(tree: dict) -> int:
    return 1 + sum(_count(c) for c in tree.get("children", []))


class Recorder:
    """Snapshot on demand, or whenever the desktop changes.

    ``roots_of`` returns the current window wrappers (or fake elements);
    ``fingerprint`` returns something that changes when the UI does.
    """

    def __init__(self, roots_of: Callable[[], List], fingerprint: Callable[[], str],
                 out_dir: Path | str, redact: bool = True,
                 titles_of: Optional[Callable[[List], List[str]]] = None) -> None:
        self.roots_of = roots_of
        self.fingerprint = fingerprint
        self.titles_of = titles_of or (lambda roots: [])
        self.out_dir = Path(out_dir)
        self.redact = redact
        self.last_signature: Optional[str] = None
        self.taken: List[Path] = []

    def snapshot(self, label: str) -> Path:
        roots = self.roots_of()
        adapted = [r if isinstance(r, Element) else UiaElement(r) for r in roots]
        shot = take(adapted, label, self.redact, self.titles_of(roots))
        path = save(shot, self.out_dir)
        self.taken.append(path)
        self.last_signature = self.fingerprint()
        return path

    def tick(self, label: str = "auto") -> Optional[Path]:
        """Snapshot if the UI changed since the last one; else nothing."""
        now = self.fingerprint()
        if now == self.last_signature:
            return None
        self.last_signature = now
        return self.snapshot(f"{label}_{int(time.time()) % 100000}")
