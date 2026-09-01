"""Programme and build phase for a DTx export, for labelling the comparison.

The export's own title block is authoritative — "Vehicle Program - 2028RU",
"Build Phase - X2_A" in the rows above the header. But not every file has one:
an export that has been re-saved or trimmed can start straight at the header
row, and those are common enough in practice that a comparison must still be
labelled sensibly. So the file name is the fallback, and the label records
which of the two it came from rather than pretending they are equivalent.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

FROM_TITLE_BLOCK = "title block"
FROM_FILE_NAME = "file name"
UNKNOWN = "unknown"

#: "28 RU X1", "28_RU_X2", "2028WS_X2_A", "(28_RU_X0)" — year, programme, phase.
#: The phase suffix must be attached ("X2_A", "X1A"), never separated by a
#: space: "28 RU X1 DetailedDTx…" would otherwise read the D of "Detailed" as
#: the suffix. The trailing guard stops a phase running into the next word.
_FROM_NAME = re.compile(
    r"(?:20)?(?P<year>\d{2})[\s_\-()]*"
    r"(?P<program>[A-Z]{2})[\s_\-()]*"
    r"(?P<phase>[XV]\d(?:_?[A-Z])?)(?![A-Za-z])",
    re.I)


@dataclass
class ReportLabel:
    program: str = ""
    phase: str = ""
    source: str = UNKNOWN
    file_name: str = ""

    @property
    def text(self) -> str:
        """``2028RU X2_A``, or as much of it as is known."""
        return " ".join(part for part in (self.program, self.phase) if part)

    @property
    def slug(self) -> str:
        """Filename-safe form: ``2028RU_X2_A``."""
        return re.sub(r"[^A-Za-z0-9]+", "_",
                      "_".join(p for p in (self.program, self.phase) if p)).strip("_")

    @property
    def known(self) -> bool:
        return bool(self.program or self.phase)

    def describe(self) -> str:
        """What to print on the report: the label, and where it came from."""
        if not self.known:
            return self.file_name or "unknown"
        return f"{self.text}  ({self.source}: {self.file_name})" if self.file_name \
            else self.text


def from_file_name(filename: str) -> ReportLabel:
    stem = Path(filename or "").stem
    match = _FROM_NAME.search(stem)
    if not match:
        return ReportLabel(source=UNKNOWN, file_name=filename or "")
    year, program, phase = (match.group("year"), match.group("program").upper(),
                            match.group("phase").upper())
    return ReportLabel(program=f"20{year}{program}", phase=phase,
                       source=FROM_FILE_NAME, file_name=filename or "")


def resolve(payload, filename: str = "") -> ReportLabel:
    """The label for one DTx: its title block if it has one, else its name."""
    try:
        from splice.dtxcircuits.dtx import read_dtx_meta
        meta = read_dtx_meta(payload, filename)
    except Exception as exc:  # noqa: BLE001 — a label must never break a report
        logger.info("Title block unreadable for %s: %s", filename, exc)
        meta = None

    if meta is not None and (meta.program or meta.phase):
        return ReportLabel(program=meta.program, phase=meta.phase,
                           source=FROM_TITLE_BLOCK, file_name=filename or "")
    return from_file_name(filename)


def comparison_slug(old: ReportLabel, new: ReportLabel) -> str:
    """``28RU_X1_vs_X2_A`` — the phases when both are known, else the programmes.

    When the two share a programme it is stated once, because a report named
    ``2028RU_X1_A_vs_2028RU_X2_A`` buries the one thing that differs.
    """
    if old.known and new.known:
        if old.program and old.program == new.program:
            left = old.phase or old.slug
            right = new.phase or new.slug
            return re.sub(r"[^A-Za-z0-9]+", "_",
                          f"{old.program}_{left}_vs_{right}").strip("_")
        return f"{old.slug}_vs_{new.slug}".strip("_")
    return ""
