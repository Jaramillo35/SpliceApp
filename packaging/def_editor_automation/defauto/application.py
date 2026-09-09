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


def connect(process: Optional[int] = None, title: Optional[str] = None,
            out_dir: Path | str = "exports") -> Session:
    """Attach to a running DEF Editor. Windows only."""
    from defauto.backend import UiaBackend

    return Session(UiaBackend().connect(process=process, title=title), out_dir)


def demo(seed: int = 31, out_dir: Path | str = "exports") -> Session:
    """A session against the scripted DEF Editor — runs anywhere."""
    from defauto.fake import FakeBackend

    return Session(FakeBackend(seed), out_dir)
