"""The session: one object holding the backend and every layer above it.

``Session`` is what a script or the GUI talks to. It exists so that the wiring
— which module gets which backend, which navigation instance they share — is
written once, and so a workflow reads as the engineer's own sequence:

    session.composite.open(...)
    session.circuits.open()
    session.circuits.missing()
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from defauto import ids
from defauto.backend import Backend, describe
from defauto.circuits import Circuits
from defauto.complexity import Complexity
from defauto.composite import Composite
from defauto.devices import Devices
from defauto.harness import Harness
from defauto.navigation import Navigation
from defauto.qualitychecks import QualityChecks
from defauto.reports import Reports
from defauto.splices import Splices


class Session:
    def __init__(self, backend: Backend,
                 out_dir: Path | str = "exports") -> None:
        self.backend = backend
        self.navigation = Navigation(backend)
        self.composite = Composite(backend)
        self.harness = Harness(backend, self.navigation)
        self.devices = Devices(backend, self.navigation)
        self.circuits = Circuits(backend, self.navigation)
        self.splices = Splices(backend, self.navigation)
        self.complexity = Complexity(backend, self.navigation)
        self.quality = QualityChecks(backend, self.navigation)
        self.reports = Reports(backend, out_dir)

    # ------------------------------------------------------------ health
    def diagnose(self) -> List[Tuple[str, bool]]:
        """Which of the ids this kit depends on are present right now.

        Run it first, every time. When DEF Editor is updated, this turns "the
        automation broke" into a list of exactly which controls moved — which
        is a ten-minute fix in ``ids.py`` instead of an afternoon in a
        debugger.
        """
        return describe(self.backend, ids.ESSENTIAL)

    def healthy(self) -> bool:
        return all(found for _, found in self.diagnose())

    # --------------------------------------------------------- recording
    def recorder(self, out_dir: Path | str = "structure", redact: bool = True):
        """A structure recorder over this session's windows.

        Real session: every window of DEF Editor's process, fingerprinted by
        titles and the focused control. Demo session: an invented tree, so
        the recorder can be tried anywhere.
        """
        from defauto.observe import Recorder, signature

        backend = self.backend
        if hasattr(backend, "structure_roots") and hasattr(backend, "_root"):
            roots_of = backend.structure_roots
            fingerprint = lambda: signature(backend.structure_roots())  # noqa: E731

            def titles_of(roots):
                out = []
                for w in roots:
                    try:
                        out.append(w.window_text())
                    except Exception:  # noqa: BLE001
                        out.append("")
                return out
        else:
            roots_of = type(backend).structure_roots

            def fingerprint():
                # the invented tree never changes; the demo's fingerprint
                # changes with each page so the auto mode can be seen working
                return f"demo:{getattr(backend, 'page', '')}"

            def titles_of(roots):
                return [getattr(r, "name", "") for r in roots]
        return Recorder(roots_of, fingerprint, out_dir, redact, titles_of)


def connect(process: Optional[int] = None, title: Optional[str] = None,
            out_dir: Path | str = "exports") -> Session:
    """Attach to a running DEF Editor by title or pid. Windows only."""
    from defauto.backend import UiaBackend

    return Session(UiaBackend().connect(process=process, title=title), out_dir)


def windows() -> List:
    """The desktop's top-level windows, for the picker. Windows only; empty
    (with the reason logged by the caller) anywhere else."""
    from defauto.backend import UiaBackend

    return UiaBackend.list_windows()


def connect_window(handle: int, out_dir: Path | str = "exports") -> Session:
    """Attach to the window the user picked. Windows only."""
    from defauto.backend import UiaBackend

    return Session(UiaBackend().connect_handle(handle), out_dir)


def demo(seed: int = 31, out_dir: Path | str = "exports") -> Session:
    """A session against the scripted DEF Editor — runs anywhere."""
    from defauto.fake import FakeBackend

    return Session(FakeBackend(seed), out_dir)
