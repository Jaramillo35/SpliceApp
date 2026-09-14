"""The seam between the automation logic and pywinauto.

Everything above this file — navigation, the modules, the validators, the
reports — is written against ``Backend``, a dozen verbs keyed by
AutomationId. Two things implement it:

``UiaBackend``   the real one, pywinauto with ``backend="uia"``. Windows only.
``FakeBackend``  a scripted DEF Editor in memory (``fake.py``).

That seam is the point. UI automation is normally provable only in front of
the application it drives, on the one operating system it runs on, which
makes it the kind of code that is written once and then never safely changed.
With the seam, every workflow in this kit is exercised by tests on any
machine, and the GUI has a Demo mode that runs the same code paths with no
DEF Editor at all — so the thing you take to Windows has already been run.

What ``UiaBackend`` must get right is therefore small and inspectable: find a
control by AutomationId, and read or poke it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Protocol, Sequence


class AutomationError(RuntimeError):
    """Something the automation asked for is not there, or would not answer."""


class ControlNotFound(AutomationError):
    def __init__(self, automation_id: str, scope: str = "") -> None:
        where = f" within {scope}" if scope else ""
        super().__init__(f"No control with AutomationId {automation_id!r}{where}")
        self.automation_id = automation_id
        self.scope = scope


class NotConnected(AutomationError):
    def __init__(self) -> None:
        super().__init__("Not attached to DEF Editor — connect first")


@dataclass
class WindowInfo:
    """One top-level window, as the picker shows it."""

    handle: int
    pid: int
    title: str
    process: str = ""

    @property
    def likely(self) -> bool:
        """Does this look like DEF Editor? Flagged in the list, never chosen."""
        text = f"{self.title} {self.process}".lower()
        return "def" in text and ("editor" in text or "master form" in text)

    def __str__(self) -> str:
        tag = "  ← looks like DEF Editor" if self.likely else ""
        proc = f"  [{self.process}]" if self.process else ""
        return f"{self.title}{proc}  (pid {self.pid}){tag}"


def _process_name(pid: int) -> str:
    """The executable behind a pid, when psutil is there; blank otherwise."""
    try:
        import psutil  # noqa: PLC0415 - optional

        return psutil.Process(pid).name()
    except Exception:  # noqa: BLE001 - optional information
        return ""


@dataclass
class Grid:
    """A DataGridView read out as text.

    Grids are the primary data source in DEF Editor, so this is the shape most
    of the kit deals in. Values stay strings: the grid shows text, and parsing
    it into numbers here would guess at types the application never stated.
    """

    headers: List[str] = field(default_factory=list)
    rows: List[List[str]] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.rows)

    def __iter__(self):
        return iter(self.dicts())

    def column(self, header: str) -> List[str]:
        """One column by header name, case-insensitively."""
        index = self.index_of(header)
        return [row[index] if index < len(row) else "" for row in self.rows]

    def index_of(self, header: str) -> int:
        wanted = header.strip().lower()
        for i, name in enumerate(self.headers):
            if name.strip().lower() == wanted:
                return i
        raise KeyError(f"{header!r} is not a column of this grid: {self.headers}")

    def dicts(self) -> List[dict]:
        return [dict(zip(self.headers, row)) for row in self.rows]

    def to_csv(self) -> str:
        import csv
        import io
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(self.headers)
        writer.writerows(self.rows)
        return buf.getvalue()


class Backend(Protocol):
    """Every UI verb the kit needs, addressed by AutomationId.

    Deliberately flat. A richer control-object model reads better in the
    abstract and is worse here: it multiplies what the fake has to imitate,
    and it invites callers to hold references to controls that DEF Editor
    disposes when a page changes.
    """

    def attached(self) -> bool: ...

    def exists(self, automation_id: str, scope: str = "") -> bool: ...

    def click(self, automation_id: str, scope: str = "") -> None: ...

    def text(self, automation_id: str, scope: str = "") -> str: ...

    def set_text(self, automation_id: str, value: str, scope: str = "") -> None: ...

    def checked(self, automation_id: str, scope: str = "") -> bool: ...

    def set_checked(self, automation_id: str, value: bool,
                    scope: str = "") -> None: ...

    def options(self, automation_id: str, scope: str = "") -> List[str]: ...

    def selected(self, automation_id: str, scope: str = "") -> Optional[str]: ...

    def select(self, automation_id: str, value: str, scope: str = "") -> None: ...

    def grid(self, automation_id: str, scope: str = "",
             columns: Optional[Sequence[str]] = None,
             progress: Optional[Callable[[int, int], None]] = None) -> Grid:
        """The grid as text. ``columns`` limits the read to those headers —
        on a 785-row, 20-column DEF Editor grid every cell is a
        cross-process call, and the updater needs three columns, not
        twenty. ``progress(done, total)`` is called as rows are read."""
        ...

    def cell(self, automation_id: str, row: int, column: str,
             scope: str = "") -> str:
        """One cell's text, for reading a write back without re-reading
        the whole grid."""
        ...

    def set_cell(self, automation_id: str, row: int, column: str, value: str,
                 scope: str = "") -> None:
        """Open a grid cell's list editor and pick ``value``.

        ``row`` is 0-based in the grid as ``grid()`` returned it; ``column`` is
        a header. The only verb in the kit that writes into DEF Editor.
        """
        ...

    def menu(self, *path: str) -> None: ...

    def invoke(self, name: str, scope: str = "") -> None:
        """Press something identified by its visible text.

        The escape hatch, and the only place visible text is used to find
        anything. The three inline actions ("Run All Inline Pair" and its
        siblings) were given no AutomationId, so there is nothing else to go
        on. Everything with an id goes through the id.
        """
        ...


# --------------------------------------------------------------------- UIA
class UiaBackend:
    """pywinauto over DEF Editor. Windows only.

    pywinauto is imported inside ``connect`` rather than at module import, so
    this file — and every test above it — loads on any operating system. The
    kit is developed and tested on whatever machine you have and run on
    Windows.
    """

    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout
        self._app = None
        self._window = None
        #: what the lookups had to do to find things — the GUI shows these,
        #: because "found it by fallback" is worth knowing before Apply
        self.notes: List[str] = []
        self._resolved: dict = {}

    # ---------------------------------------------------------- attaching
    def connect(self, process: Optional[int] = None,
                title: Optional[str] = None) -> "UiaBackend":
        from pywinauto import Application  # noqa: PLC0415 - Windows only

        from defauto import ids

        app = Application(backend="uia")
        if process is not None:
            self._app = app.connect(process=process, timeout=self.timeout)
        else:
            self._app = app.connect(title=title or ids.MAIN_WINDOW_TITLE,
                                    timeout=self.timeout)
        self._window = self._app.window(title=title or ids.MAIN_WINDOW_TITLE)
        self._window.wait("visible", timeout=self.timeout)
        return self

    @staticmethod
    def list_windows() -> List["WindowInfo"]:
        """Every top-level window on the desktop, so the user can point at
        DEF Editor rather than the kit guessing its title.

        The title this kit was written against is ``DEF EDITOR - Master
        Form``; a different release, a different language pack or a document
        name appended to the title all defeat a guess. A list defeats none of
        them. Likely candidates are flagged, never chosen.
        """
        from pywinauto import Desktop  # noqa: PLC0415 - Windows only

        out: List[WindowInfo] = []
        for window in Desktop(backend="uia").windows():
            try:
                title = window.window_text()
                if not title.strip():
                    continue
                out.append(WindowInfo(
                    handle=int(window.handle), pid=int(window.process_id()),
                    title=title, process=_process_name(window.process_id())))
            except Exception:  # noqa: BLE001 - a window may vanish mid-scan
                continue
        out.sort(key=lambda w: (not w.likely, w.title.lower()))
        return out

    def connect_handle(self, handle: int) -> "UiaBackend":
        """Attach to the window the user picked from ``list_windows``."""
        from pywinauto import Application  # noqa: PLC0415 - Windows only

        self._app = Application(backend="uia").connect(handle=handle,
                                                        timeout=self.timeout)
        self._window = self._app.window(handle=handle)
        self._window.wait("visible", timeout=self.timeout)
        return self

    def attached(self) -> bool:
        return self._window is not None

    # ----------------------------------------------------------- resolving
    def _root(self):
        if self._window is None:
            raise NotConnected()
        return self._window

    def _find(self, automation_id: str, scope: str = ""):
        parent = self._root()
        if scope:
            try:
                parent = parent.child_window(auto_id=scope)
                parent.wait("exists", timeout=self.timeout)
            except Exception as exc:  # noqa: BLE001 - reported, not raised raw
                raise ControlNotFound(scope) from exc
        from defauto import ids

        types = ids.CONTROL_TYPES.get(automation_id)
        if isinstance(types, str):
            types = (types,)
        # by id, with each accepted type, then with no type at all
        for control_type in [*(types or ()), None]:
            kwargs = {"auto_id": automation_id}
            if control_type:
                kwargs["control_type"] = control_type
            try:
                control = parent.child_window(**kwargs)
                control.wait("exists", timeout=2)
                return control
            except Exception:  # noqa: BLE001 - try the next way
                continue
        # a grid by its owner: the one Table/DataGrid under the page's user control
        owner = ids.GRID_OWNER.get(automation_id)
        if owner:
            try:
                page = parent.child_window(auto_id=owner)
                page.wait("exists", timeout=2)
                grids = [g for t in ids.GRID_TYPES
                         for g in page.descendants(control_type=t)]
            except Exception:  # noqa: BLE001
                grids = []
            if len(grids) == 1:
                found = grids[0]
                real = getattr(found.element_info, "automation_id", "") or "(no id)"
                if automation_id not in self._resolved:
                    self._resolved[automation_id] = real
                    self.notes.append(f"{automation_id!r} not found by id; using the "
                                      f"only grid under {owner!r} (its id is {real!r} "
                                      f"— put that in defauto/ids.py)")
                return found
            if grids:
                raise ControlNotFound(
                    automation_id, f"{owner}: {len(grids)} grids there — "
                    + ", ".join(repr(getattr(g.element_info, "automation_id", "") or "(no id)")
                                for g in grids))
        raise ControlNotFound(automation_id, scope)

    # ------------------------------------------------------------- verbs
    def exists(self, automation_id: str, scope: str = "") -> bool:
        try:
            self._find(automation_id, scope)
            return True
        except AutomationError:
            return False

    def click(self, automation_id: str, scope: str = "") -> None:
        self._find(automation_id, scope).click_input()

    def text(self, automation_id: str, scope: str = "") -> str:
        control = self._find(automation_id, scope)
        try:
            return control.get_value()
        except Exception:  # noqa: BLE001 - not every control has a value pattern
            return control.window_text()

    def set_text(self, automation_id: str, value: str, scope: str = "") -> None:
        control = self._find(automation_id, scope)
        control.set_edit_text("")
        control.type_keys(value, with_spaces=True, set_foreground=False)

    def checked(self, automation_id: str, scope: str = "") -> bool:
        return bool(self._find(automation_id, scope).get_toggle_state())

    def set_checked(self, automation_id: str, value: bool,
                    scope: str = "") -> None:
        if self.checked(automation_id, scope) != value:
            self._find(automation_id, scope).toggle()

    def options(self, automation_id: str, scope: str = "") -> List[str]:
        """The items a combo box or list offers.

        ``texts()`` on a UIA wrapper returns the texts of whatever it
        descended into, which for a mismatched element was 'Phase' and
        'Close'. Items are read as items: the ListItem descendants of the
        control, expanding a collapsed combo box to get them.
        """
        control = self._find(automation_id, scope)
        try:
            if hasattr(control, "expand"):
                control.expand()
        except Exception:  # noqa: BLE001 - a list has nothing to expand
            pass
        try:
            items = [i.window_text() for i in control.descendants(control_type="ListItem")]
        except Exception:  # noqa: BLE001
            items = []
        try:
            if hasattr(control, "collapse"):
                control.collapse()
        except Exception:  # noqa: BLE001
            pass
        if items:
            return [t for t in items if t]
        return [t for t in control.texts()[1:] if t]

    def structure_roots(self) -> List:
        """The wrappers the recorder walks: every window of the process."""
        from defauto.observe import process_windows

        pid = int(self._root().process_id())
        return process_windows(pid) or [self._root()]

    def selected(self, automation_id: str, scope: str = "") -> Optional[str]:
        value = self._find(automation_id, scope).selected_text()
        return value or None

    def select(self, automation_id: str, value: str, scope: str = "") -> None:
        self._find(automation_id, scope).select(value)

    # ------------------------------------------------------ grid reading
    @staticmethod
    def _text(element) -> str:
        """An element's interface text: a header, a list item, a button."""
        try:
            value = element.window_text()
            if value:
                return str(value)
        except Exception:  # noqa: BLE001
            pass
        for getter in ("get_value", "legacy_properties"):
            try:
                got = getattr(element, getter)()
                if isinstance(got, dict):
                    got = got.get("Value") or got.get("Name") or ""
                if got:
                    return str(got)
            except Exception:  # noqa: BLE001
                continue
        return ""

    #: how a WinForms DataGridView names its cells: "<column header> Row <n>"
    CELL_LABEL = re.compile(r".* Row \d+$")

    @classmethod
    def _cell_text(cls, element) -> str:
        """A grid cell's CONTENT.

        A WinForms DataGridView (DEF Editor's circuits grid; the third
        structure snapshot shows a cell named " Row 0") gives every cell the
        accessible *name* "<column header> Row <n>" and puts what the cell
        shows in its *value*. Reading the name matched labels against the
        Excel and found nothing. So: the Value pattern first, the legacy
        Value next, and the name only when it is not that label.
        """
        try:
            value = element.iface_value.CurrentValue
            if value is not None and str(value) != "":
                return str(value)
        except Exception:  # noqa: BLE001 - no Value pattern here
            pass
        try:
            got = element.legacy_properties().get("Value")
            if got:
                return str(got)
        except Exception:  # noqa: BLE001
            pass
        try:
            name = element.window_text()
        except Exception:  # noqa: BLE001
            name = ""
        name = str(name or "")
        if cls.CELL_LABEL.match(name):
            return ""
        return name

    @staticmethod
    def _ctype(element) -> str:
        return getattr(element.element_info, "control_type", "") or ""

    def _rows_of(self, control) -> tuple:
        """``(headers, [row elements])`` of a grid, whatever its make.

        A WinForms DataGridView has a Header of HeaderItems and DataItem rows.
        A DevExpress grid (what DEF Editor uses; seen as control type Table)
        has Custom rows, the first of which holds Header elements named for
        the columns. Both are read the same way: headers are every Header /
        HeaderItem name in order; rows are the row-like children that are not
        the header row.
        """
        headers: List[str] = []
        rows = []
        for child in control.children():
            ctype = self._ctype(child)
            kids = child.children()
            if ctype in ("Header", "HeaderItem"):
                for h in [child, *kids]:
                    if self._ctype(h) in ("Header", "HeaderItem") and self._text(h) \
                            and self._text(h) not in headers:
                        headers.append(self._text(h))
                continue
            if ctype == "Custom" and kids and all(self._ctype(k) in ("Header", "HeaderItem")
                                                  for k in kids):
                for h in kids:
                    if self._text(h) and self._text(h) not in headers:
                        headers.append(self._text(h))
                continue
            if ctype in ("DataItem", "ListItem", "Custom"):
                rows.append(child)
        if not headers:
            try:
                headers = [str(h) for h in control.column_headers()]
            except Exception:  # noqa: BLE001
                headers = []
        return headers, rows

    def _cells_of(self, row) -> list:
        kids = row.children()
        return kids if kids else [row]

    # A WinForms DataGridView (DEF Editor's circuits grid, per the second
    # structure snapshot: Table, 785 Custom rows with NO children) does not
    # put its cells in the UI Automation tree. They are reached through the
    # Grid pattern — GetItem(row, column) — which is what these use. The
    # tree walk stays as the fallback for a grid that does expose cells.
    def _grid_cell(self, control, row: int, col: int):
        try:
            element = control.iface_grid.GetItem(row, col)
        except Exception:  # noqa: BLE001 - no Grid pattern, or out of range
            return None
        if element is None:
            return None
        try:
            from pywinauto.controls.uiawrapper import UIAWrapper  # noqa: PLC0415
            from pywinauto.uia_element_info import UIAElementInfo  # noqa: PLC0415

            return UIAWrapper(UIAElementInfo(element))
        except Exception:  # noqa: BLE001
            return None

    def _column_index(self, headers: List[str], column: str) -> int:
        wanted = column.strip().lower().replace(" ", "")
        for i, h in enumerate(headers):
            if h.strip().lower().replace(" ", "") == wanted:
                return i
        raise AutomationError(f"the grid has no column {column!r}; headers: {headers}")

    def grid(self, automation_id: str, scope: str = "",
             columns: Optional[Sequence[str]] = None,
             progress: Optional[Callable[[int, int], None]] = None) -> Grid:
        control = self._find(automation_id, scope)
        headers, rows = self._rows_of(control)
        if not headers:
            self.notes.append(f"{automation_id!r}: no column headers found — columns "
                              "are matched by name, so take a structure snapshot")
            return Grid(headers=[], rows=[])
        wanted = list(range(len(headers))) if not columns else \
            [self._column_index(headers, c) for c in columns]
        first = self._grid_cell(control, 0, wanted[0]) if rows else None
        by_pattern = first is not None
        if by_pattern and "grid pattern" not in " ".join(self.notes):
            self.notes.append(f"{automation_id!r}: cells read through the Grid pattern "
                              f"({len(rows)} rows × {len(wanted)} columns)")
            if self.CELL_LABEL.match(self._text(first) or ""):
                self.notes.append(f"{automation_id!r}: cells are named "
                                  f"'<column> Row <n>' — values read through the "
                                  "Value pattern, not the name")
        out: List[List[str]] = []
        total = len(rows)
        for r, row in enumerate(rows):
            if by_pattern:
                values = []
                for c in wanted:
                    cell = self._grid_cell(control, r, c)
                    values.append(self._cell_text(cell) if cell is not None else "")
            else:
                cells = self._cells_of(row)
                values = [self._cell_text(cells[c]) if c < len(cells) else ""
                          for c in wanted]
            out.append(values)
            if progress is not None and (r % 25 == 0 or r == total - 1):
                progress(r + 1, total)
        return Grid(headers=[headers[c] for c in wanted], rows=out)

    def cell(self, automation_id: str, row: int, column: str, scope: str = "") -> str:
        control = self._find(automation_id, scope)
        headers, rows = self._rows_of(control)
        col = self._column_index(headers, column)
        found = self._grid_cell(control, row, col)
        if found is not None:
            return self._cell_text(found)
        if row < len(rows):
            cells = self._cells_of(rows[row])
            return self._cell_text(cells[col]) if col < len(cells) else ""
        raise AutomationError(f"row {row + 1} is beyond the grid's {len(rows)} rows")

    def set_cell(self, automation_id: str, row: int, column: str, value: str,
                 scope: str = "") -> None:
        """Click the cell, take the list editor that opens, pick the value.

        Written against the description of DEF Editor's grids, not a recorded
        tree: a WinForms DataGridView exposes rows as DataItems and cells as
        their children, and a combo-box column opens a ComboBox editor on
        click whose items are ListItems. Each step is checked and named, so
        a wrong assumption reports which one.
        """
        import time

        control = self._find(automation_id, scope)
        headers, rows = self._rows_of(control)
        col = self._column_index(headers, column)
        if row >= len(rows):
            raise AutomationError(f"grid {automation_id!r} has {len(rows)} rows, "
                                  f"row {row + 1} asked for")
        cell = self._grid_cell(control, row, col)
        if cell is None:
            cells = self._cells_of(rows[row])
            if col >= len(cells):
                raise AutomationError(f"row {row + 1} exposes no cell for column "
                                      f"{column!r} — the Grid pattern is not "
                                      "available and the tree has no cells")
            cell = cells[col]
        pid = int(self._root().process_id())
        cell.click_input()
        time.sleep(0.3)

        # DEF Editor's Term Matl editor (third structure snapshot, list open):
        # its own pane under the column, a ListBox of the materials, a close
        # button. Pick from that list; close the pane if the pick leaves it
        # open, so the next row starts clean.
        pane = self._term_matl_pane()
        if pane is None:
            cell.click_input()                   # a second click, if the first only selected
            time.sleep(0.4)
            pane = self._term_matl_pane()
        if pane is not None:
            from defauto import ids

            try:
                box = pane.child_window(auto_id=ids.LIST_TERM_MATL, control_type="List")
                box.wait("exists", timeout=2)
                items = [(i, self._text(i)) for i in box.descendants(control_type="ListItem")]
            except Exception as exc:  # noqa: BLE001
                raise AutomationError(f"the Term Matl pane opened but its list "
                                      f"{ids.LIST_TERM_MATL!r} could not be read: {exc}") from exc
            pick = next((i for i, n in items if n.strip().upper() == value.strip().upper()), None)
            if pick is None:
                raise AutomationError(f"{value!r} is not in the Term Matl list: "
                                      f"{[n for _i, n in items]}")
            pick.click_input()
            time.sleep(0.3)
            self._close_term_matl_pane()
            return

        # Any other grid. A WinForms combo column opens a ComboBox in the cell;
        # a DevExpress lookup opens a popup — its own top-level window of the
        # same process — holding the items. Look in the cell, the row, the
        # grid, then the process's windows, and take the first place whose
        # items include the value we need.
        def items_under(element):
            try:
                found = element.descendants(control_type="ListItem")
            except Exception:  # noqa: BLE001
                return []
            return [(i, self._text(i)) for i in found]

        places = [cell, rows[row], control]
        try:
            from pywinauto import Desktop  # noqa: PLC0415

            places += [w for w in Desktop(backend="uia").windows()
                       if int(w.process_id()) == pid]
        except Exception:  # noqa: BLE001
            pass
        seen_names: List[str] = []
        pick = None
        for place in places:
            for element, name in items_under(place):
                if name and name not in seen_names:
                    seen_names.append(name)
                if name.strip().upper() == value.strip().upper():
                    pick = element
                    break
            if pick is not None:
                break
        if pick is None:
            raise AutomationError(
                f"no list with {value!r} opened on {column!r} of row {row + 1}"
                + (f" — items seen: {seen_names}" if seen_names else
                   " — no list items appeared at all; take a structure snapshot "
                   "with the cell's list open"))
        pick.click_input()
        time.sleep(0.2)
        try:
            cell.type_keys("{ENTER}", set_foreground=False)
        except Exception:  # noqa: BLE001 - the click may already have committed
            pass

    def _term_matl_pane(self):
        """The material selector, if it is open right now."""
        from defauto import ids

        try:
            pane = self._root().child_window(auto_id=ids.PANE_TERM_MATL, control_type="Pane")
            pane.wait("exists visible", timeout=1.5)
            return pane
        except Exception:  # noqa: BLE001 - not open
            return None

    def _close_term_matl_pane(self) -> None:
        """Close the selector if the pick left it open; harmless if it did not."""
        from defauto import ids

        pane = self._term_matl_pane()
        if pane is None:
            return
        try:
            pane.child_window(auto_id=ids.CLOSE_TERM_MATL).click_input()
        except Exception:  # noqa: BLE001
            try:
                pane.type_keys("{ESC}", set_foreground=False)
            except Exception:  # noqa: BLE001
                pass

    def menu(self, *path: str) -> None:
        self._root().menu_select("->".join(path))

    def invoke(self, name: str, scope: str = "") -> None:
        parent = self._root() if not scope else self._find(scope)
        parent.child_window(title=name).click_input()


def describe(backend: Backend, automation_ids: Sequence[str]) -> List[tuple]:
    """``(id, found)`` for each id — what ``diagnose`` reports on."""
    return [(auto_id, backend.exists(auto_id)) for auto_id in automation_ids]
