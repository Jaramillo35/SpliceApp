"""Do the DTx and the complexity files describe the same programme and phase?

Answered from what the files say about themselves — the DTx title block and
each complexity file's ``Harness PN`` info table — never from their names.
Mixing a phase is the failure that silently produces a plausible, wrong
answer, so this runs before any analysis and states what it found.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List

from splice.dtxcircuits.complexity import (
    ComplexityMeta,
    normalize_phase,
    normalize_program,
)
from splice.dtxcircuits.models import DtxMeta

OK = "ok"                 # same programme and phase
PHASE_SPELLING = "phase spelling"   # X2_A vs X2A — same phase, written differently
PHASE_MISMATCH = "phase mismatch"   # genuinely a different phase
PROGRAM_MISMATCH = "program mismatch"
UNKNOWN = "unknown"       # the file does not state its identity


@dataclass
class FileCheck:
    filename: str
    harness: str
    program: str
    phase: str
    status: str
    detail: str = ""

    @property
    def blocking(self) -> bool:
        return self.status in (PROGRAM_MISMATCH, PHASE_MISMATCH)


@dataclass
class Correspondence:
    dtx_program: str = ""
    dtx_phase: str = ""
    files: List[FileCheck] = field(default_factory=list)

    @property
    def blocking(self) -> List[FileCheck]:
        return [f for f in self.files if f.blocking]

    @property
    def warnings(self) -> List[FileCheck]:
        return [f for f in self.files
                if f.status in (PHASE_SPELLING, UNKNOWN)]

    @property
    def matched(self) -> List[FileCheck]:
        return [f for f in self.files if f.status == OK]

    @property
    def all_match(self) -> bool:
        return not self.blocking


def check(dtx: DtxMeta, metas: Iterable[ComplexityMeta]) -> Correspondence:
    """Compare each complexity file's identity against the DTx's own."""
    result = Correspondence(dtx_program=dtx.program, dtx_phase=dtx.phase)
    want_program = normalize_program(dtx.program)
    want_phase = normalize_phase(dtx.phase)

    for meta in metas:
        check = FileCheck(filename=meta.filename, harness=meta.harness,
                          program=meta.program, phase=meta.phase, status=OK)
        got_program = normalize_program(meta.program)
        got_phase = normalize_phase(meta.phase)

        if not meta.complete:
            check.status = UNKNOWN
            check.detail = ("the Harness PN sheet does not state year, vehicle "
                            "and phase — identity cannot be confirmed")
        elif want_program and got_program != want_program:
            check.status = PROGRAM_MISMATCH
            check.detail = (f"complexity is {meta.program}, the DTx is "
                            f"{dtx.program}")
        elif want_phase and got_phase != want_phase:
            # Normalisation already absorbed punctuation, so a difference that
            # survives it is a real difference of phase — X2 is NOT X2_A.
            check.status = PHASE_MISMATCH
            check.detail = (f"complexity is phase {meta.phase}, the DTx is "
                            f"phase {dtx.phase}")
        elif want_phase and meta.phase.strip() != dtx.phase.strip():
            # Same phase, typed differently (X2_A vs X2A). Worth showing so the
            # inconsistency gets fixed at source, but it blocks nothing.
            check.status = PHASE_SPELLING
            check.detail = (f"phase written '{meta.phase}', the DTx says "
                            f"'{dtx.phase}' — same phase, different spelling")
        result.files.append(check)
    return result
