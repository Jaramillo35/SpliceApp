"""The Validation layer: run DEF Editor's own checks and capture what they said.

Two checks, and they behave differently enough to be worth separating. The
connector check writes into a results box. The inline check runs pair by pair,
puts its matches in a grid, and gates a sign-off behind them.

The sign-off is the one place this kit can do real damage, so it is the one
place it refuses to be clever: ``sign_off`` will not press the button while a
pair is failing unless the caller has explicitly set the bypass, and it says
which pairs are failing when it declines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from defauto import ids
from defauto.backend import AutomationError, Backend, Grid
from defauto.navigation import Navigation


@dataclass
class CheckResult:
    name: str
    passed: bool
    text: str = ""
    rows: Grid = field(default_factory=Grid)

    @property
    def summary(self) -> str:
        verdict = "PASS" if self.passed else "FAIL"
        return f"[{verdict}] {self.name}"


class QualityChecks:
    def __init__(self, backend: Backend, navigation: Navigation) -> None:
        self.backend = backend
        self.navigation = navigation

    # -------------------------------------------------------- connectors
    def circuits(self, bypass_ends: bool = False,
                 bypass_attributes: bool = False) -> CheckResult:
        self.navigation.checks_circuits()
        self.backend.set_checked(ids.CHECK_ENDS_BYPASS, bypass_ends)
        self.backend.set_checked(ids.CHECK_ATTRIBUTES_BYPASS, bypass_attributes)
        runner = getattr(self.backend, "run_connector_checks", None)
        if runner is not None:      # the demo backend runs it in-process
            text = runner()
        else:
            self.backend.invoke("Run")
            text = self.backend.text(ids.RICH_RESULTS)
        failed = any(word in text.lower()
                     for word in ("fail", "mismatch", "error", "missing"))
        return CheckResult("Circuit and connector checks", not failed, text)

    # ------------------------------------------------------------ inline
    def inline_pairs(self, needle: str = "") -> Grid:
        self.navigation.checks_inlines()
        if needle:
            self.backend.set_text(ids.TEXT_FILTER_INLINE, needle)
        return self.backend.grid(ids.GRID_INLINE_MATCH)

    def run_inline(self, all_pairs: bool = True) -> CheckResult:
        self.navigation.checks_inlines()
        self.backend.invoke(ids.ACTION_RUN_ALL_PAIRS if all_pairs
                            else ids.ACTION_RUN_SELECTED_PAIR)
        text = self.backend.text(ids.RICH_RESULTS)
        rows = self.backend.grid(ids.GRID_INLINE_MATCH)
        failing = self.failing_pairs(rows)
        return CheckResult("Inline pair check", not failing, text, rows)

    @staticmethod
    def failing_pairs(rows: Grid) -> List[dict]:
        try:
            index = rows.index_of("Result")
        except KeyError:
            return []
        return [dict(zip(rows.headers, row)) for row in rows.rows
                if index < len(row) and row[index].strip().lower() != "match"]

    def sign_off(self, bypass: bool = False) -> CheckResult:
        """Sign off the inline check — refusing while anything is still failing.

        ``bypass`` sets the application's own bypass checkbox rather than
        working around it, so a signed-off-with-bypass record looks in DEF
        Editor exactly like one a person made.
        """
        result = self.run_inline(all_pairs=True)
        failing = self.failing_pairs(result.rows)
        if failing and not bypass:
            names = ", ".join(f"{f.get('Inline')}<->{f.get('Mate')}"
                              for f in failing)
            raise AutomationError(
                f"Refusing to sign off: {len(failing)} inline pair(s) still "
                f"failing ({names}). Fix them, or pass bypass=True to set the "
                f"application's own bypass checkbox.")
        if bypass:
            self.backend.set_checked(ids.CHECK_INLINE_BYPASS, True)
        self.backend.invoke(ids.ACTION_SIGN_OFF_INLINE)
        return CheckResult("Inline sign-off", True,
                           f"Signed off with {len(failing)} bypassed pair(s)"
                           if failing else "Signed off, all pairs matching")
