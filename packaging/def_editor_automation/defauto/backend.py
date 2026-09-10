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

from dataclasses import dataclass, field
from typing import List, Optional, Protocol, Sequence


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

    def grid(self, automation_id: str, scope: str = "") -> Grid: ...

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
        try:
            control = parent.child_window(auto_id=automation_id)
            control.wait("exists", timeout=self.timeout)
            return control
        except Exception as exc:  # noqa: BLE001
            raise ControlNotFound(automation_id, scope) from exc

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
        return list(self._find(automation_id, scope).texts()[1:])

    def selected(self, automation_id: str, scope: str = "") -> Optional[str]:
        value = self._find(automation_id, scope).selected_text()
        return value or None

    def select(self, automation_id: str, value: str, scope: str = "") -> None:
        self._find(automation_id, scope).select(value)

    def grid(self, automation_id: str, scope: str = "") -> Grid:
        control = self._find(automation_id, scope)
        headers = [str(h) for h in control.column_headers()] \
            if hasattr(control, "column_headers") else []
        rows: List[List[str]] = []
        for item in control.items():
            texts = [str(cell.window_text()) for cell in item.descendants()] \
                if hasattr(item, "descendants") else [str(item.window_text())]
            rows.append(texts)
        return Grid(headers=headers, rows=rows)

    def menu(self, *path: str) -> None:
        self._root().menu_select("->".join(path))

    def invoke(self, name: str, scope: str = "") -> None:
        parent = self._root() if not scope else self._find(scope)
        parent.child_window(title=name).click_input()


def describe(backend: Backend, automation_ids: Sequence[str]) -> List[tuple]:
    """``(id, found)`` for each id — what ``diagnose`` reports on."""
    return [(auto_id, backend.exists(auto_id)) for auto_id in automation_ids]
