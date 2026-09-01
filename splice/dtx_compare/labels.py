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

#: "Jul-15-2026 12:10 AM" — the date part of an iSpeed report-date string.
_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}
_REPORT_DATE = re.compile(r"([A-Za-z]{3})-(\d{1,2})-(\d{4})")

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
    #: when iSpeed generated the export, from the title block. Two exports of
    #: the same phase are told apart by this and nothing else, so it is the
    #: one field worth printing even when programme and phase match.
    report_date: str = ""

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

    @property
    def date_slug(self) -> str:
        """``20260715`` — sortable, filename-safe. Empty if unparseable."""
        match = _REPORT_DATE.search(self.report_date or "")
        if not match:
            return ""
        month = _MONTHS.get(match.group(1).lower())
        if not month:
            return ""
        return f"{match.group(3)}{month:02d}{int(match.group(2)):02d}"

    @property
    def short_date(self) -> str:
        """``Jul-15-2026`` — the date without the clock time."""
        match = _REPORT_DATE.search(self.report_date or "")
        return match.group(0) if match else ""

    @property
    def text_with_date(self) -> str:
        """``2028RU X2_A · exported Jul-21-2026 07:53 AM``."""
        if not self.report_date:
            return self.text
        return f"{self.text} · exported {self.report_date}".strip(" ·")

    def describe(self) -> str:
        """What to print on the report: the label, its date, and its source."""
        if not self.known:
            return self.file_name or "unknown"
        head = self.text_with_date
        return f"{head}  ({self.source}: {self.file_name})" if self.file_name \
            else head


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

    report_date = getattr(meta, "report_date", "") if meta is not None else ""
    if meta is not None and (meta.program or meta.phase):
        return ReportLabel(program=meta.program, phase=meta.phase,
                           source=FROM_TITLE_BLOCK, file_name=filename or "",
                           report_date=report_date)
    # No title block: the name is all there is for programme and phase, but a
    # date read from the block is still worth keeping if one was found.
    label = from_file_name(filename)
    label.report_date = report_date
    return label


def comparison_slug(old: ReportLabel, new: ReportLabel) -> str:
    """``28RU_X1_vs_X2_A`` — the phases when both are known, else the programmes.

    When the two share a programme it is stated once, because a report named
    ``2028RU_X1_A_vs_2028RU_X2_A`` buries the one thing that differs.
    """
    if old.known and new.known:
        if old.program and old.program == new.program:
            left = old.phase or old.slug
            right = new.phase or new.slug
            # iSpeed labels successive exports of the same phase identically —
            # seen in the field on 2028WS, where both title blocks read X2_A
            # and only the report date differed. "X2_A_vs_X2_A" names nothing,
            # so where the phases match the dates become the discriminator.
            if left == right and old.date_slug and new.date_slug \
                    and old.date_slug != new.date_slug:
                left, right = f"{left}_{old.date_slug}", f"{right}_{new.date_slug}"
            return re.sub(r"[^A-Za-z0-9]+", "_",
                          f"{old.program}_{left}_vs_{right}").strip("_")
        return f"{old.slug}_vs_{new.slug}".strip("_")
    return ""


def comparison_heading(old: ReportLabel, new: ReportLabel) -> str:
    """``2028RU X1 → X2_A``, with dates when the phases are indistinguishable."""
    if not (old.known or new.known):
        return ""
    left, right = old.text, new.text
    if left == right:
        if old.short_date and new.short_date and old.short_date != new.short_date:
            left = f"{left} ({old.short_date})"
            right = f"{right} ({new.short_date})"
    return " → ".join(part for part in (left, right) if part)
