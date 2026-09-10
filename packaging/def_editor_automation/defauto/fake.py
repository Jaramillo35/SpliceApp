"""A scripted DEF Editor in memory, so the automation can be run anywhere.

Everything here is invented. The programmes (2031 ZR / 2032 QX), the harness
names, the circuit and splice numbers and the sales codes are generated from a
seed and resemble no real vehicle programme; no customer, user, machine or
business data is present in this kit.

What it imitates is *behaviour*, because that is what the automation depends
on and what a static stub would not catch:

* the three combo boxes cascade — a model year that the chosen vehicle line
  does not build is not offered, and changing the line clears what was below;
* Filter is what populates the composite grid, so a workflow that forgets to
  press it reads an empty grid rather than silently passing;
* filter boxes actually filter their grid, and the two circuit checkboxes
  narrow it further, so a wrong AutomationId shows up as the wrong rows;
* quality checks write into the results box and the inline check refuses to
  sign off while any pair is still failing.

Anything the automation asks for that DEF Editor would not have raises
``ControlNotFound``, exactly as the real backend does. That is what makes a
typo in ``ids.py`` a test failure instead of a Windows-only surprise.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from defauto import ids
from defauto.backend import ControlNotFound, Grid

VEHICLE_LINES = ["2031ZR", "2032QX"]
MODEL_YEARS = {"2031ZR": ["2031"], "2032QX": ["2032", "2033"]}
PHASES = {"2031ZR": ["V1_A", "V2_A"], "2032QX": ["V1_A"]}

SALES_CODES = [f"Z{g}{n}" for g in "ABC" for n in range(1, 5)]


@dataclass
class _Harness:
    name: str
    part_number: str
    devices: List[List[str]] = field(default_factory=list)
    circuits: List[List[str]] = field(default_factory=list)
    splices: List[List[str]] = field(default_factory=list)
    sales_codes: List[List[str]] = field(default_factory=list)
    inline_pairs: List[List[str]] = field(default_factory=list)


def _programme(seed: int = 31) -> Dict[str, Dict]:
    """Composites and harnesses, deterministically invented."""
    rng = random.Random(seed)
    out: Dict[str, Dict] = {}
    for line in VEHICLE_LINES:
        for year in MODEL_YEARS[line]:
            for phase in PHASES[line]:
                composites = {}
                for index in range(1, 4):
                    name = f"{line}_{phase}_COMP{index}"
                    harnesses = {}
                    for zone in ("IP", "DASH", "BODY_LEFT", "LIFTGATE")[:2 + index % 3]:
                        harnesses[zone] = _harness(zone, rng)
                    composites[name] = harnesses
                out[f"{line}|{year}|{phase}"] = composites
    return out


def _harness(zone: str, rng: random.Random) -> _Harness:
    pn = f"98{rng.randint(100000, 999999)}AA"
    harness = _Harness(name=zone, part_number=pn)
    for i in range(1, rng.randint(6, 11)):
        harness.devices.append(
            [f"D{2000 + i}A", f"{zone} MODULE {i}", str(rng.randint(4, 24)),
             f"CN{rng.randint(1000, 9999)}"])
    # Circuit names follow the DTx convention an engineer recognises — a
    # letter block and a number, not ZK0001 — because the automation test
    # filters for one by name and a made-up naming scheme would let a filter
    # bug pass unnoticed.
    names = [f"{letter}{number}"
             for letter in "ABDMQ" for number in (0, 1, 4, 12, 34)]
    rng.shuffle(names)
    # every harness carries B4, so the test's default target always resolves
    for name in ["B4", *names[:rng.randint(9, 17)]]:
        ends = rng.choice([1, 2, 2, 2, 3])
        harness.circuits.append(
            [name, f"{zone} - FEED {name}", str(ends),
             rng.choice(["", "", rng.choice(SALES_CODES)]),
             "0.35", "TXL"])
    for i in range(1, rng.randint(2, 5)):
        harness.splices.append(
            [f"S{zone[:2]}{i:02d}", rng.choice(harness.circuits)[0],
             str(rng.randint(3, 6)), "Ultrasonic"])
    for code in rng.sample(SALES_CODES, rng.randint(3, 6)):
        harness.sales_codes.append([code, pn, rng.choice(["Used", "Available"])])
    for i in range(1, rng.randint(2, 4)):
        harness.inline_pairs.append(
            [f"X{300 + i}A", f"Y{300 + i}A", zone,
             rng.choice(["Match", "Match", "Mismatch"])])
    return harness


@dataclass
class _Combo:
    options: Callable[[], List[str]]
    on_select: Callable[[str], None]
    value: Optional[str] = None


class FakeBackend:
    """Implements ``Backend`` over the invented programme above."""

    def __init__(self, seed: int = 31) -> None:
        self.data = _programme(seed)
        self.log: List[str] = []

        self.vehicle_line: Optional[str] = None
        self.model_year: Optional[str] = None
        self.phase: Optional[str] = None
        self.composite: Optional[str] = None
        self.harness: Optional[str] = None

        #: Filter has not been pressed yet, so the composite grid is empty.
        self.filtered = False
        self.page = ids.UC_HARNESS
        self.filters: Dict[str, str] = {f: "" for f in ids.FILTERS}
        self.checks: Dict[str, bool] = {c: False for c in ids.CHECKBOXES}
        self.results = ""
        self.signed_off = False
        self.last_menu: tuple = ()

    # ------------------------------------------------------------ helpers
    def attached(self) -> bool:
        return True

    @staticmethod
    def list_windows() -> list:
        """What the picker shows in Demo mode: a desktop with DEF Editor on
        it among other things, so the flagging can be seen working."""
        from defauto.backend import WindowInfo

        out = [WindowInfo(1001, 4321, "DEF EDITOR - Master Form", "DEFEditor.exe"),
               WindowInfo(1002, 4322, "Inbox - Outlook", "OUTLOOK.EXE"),
               WindowInfo(1003, 4323, "Master Complexity.xlsx - Excel", "EXCEL.EXE"),
               WindowInfo(1004, 4324, "DEF Editor - Composite 2031ZR_V1_A_COMP1",
                          "DEFEditor.exe")]
        out.sort(key=lambda w: (not w.likely, w.title.lower()))
        return out

    def _key(self) -> str:
        return f"{self.vehicle_line}|{self.model_year}|{self.phase}"

    def _composites(self) -> Dict[str, Dict]:
        return self.data.get(self._key(), {})

    def _harnesses(self) -> Dict[str, _Harness]:
        return self._composites().get(self.composite or "", {})

    def _current(self) -> Optional[_Harness]:
        return self._harnesses().get(self.harness or "")

    def _note(self, message: str) -> None:
        self.log.append(message)

    # ------------------------------------------------------------- combos
    def _combos(self) -> Dict[str, _Combo]:
        def pick_line(value: str) -> None:
            self.vehicle_line = value
            # everything below a changed line is stale, as in the application
            self.model_year = self.phase = self.composite = self.harness = None
            self.filtered = False

        def pick_year(value: str) -> None:
            self.model_year = value
            self.phase = self.composite = self.harness = None
            self.filtered = False

        def pick_phase(value: str) -> None:
            self.phase = value
            self.composite = self.harness = None
            self.filtered = False

        return {
            ids.COMBO_VEHICLE_LINE: _Combo(
                lambda: list(VEHICLE_LINES), pick_line, self.vehicle_line),
            ids.COMBO_MODEL_YEAR: _Combo(
                lambda: MODEL_YEARS.get(self.vehicle_line or "", []),
                pick_year, self.model_year),
            ids.COMBO_PHASE: _Combo(
                lambda: PHASES.get(self.vehicle_line or "", []),
                pick_phase, self.phase),
            ids.COMBO_DELPHI_CONNECTOR: _Combo(
                lambda: sorted({row[3] for row in
                                (self._current().devices if self._current() else [])}),
                lambda value: self.filters.__setitem__(
                    ids.TEXT_FILTER_CIRCUIT, value),
                None),
        }

    # -------------------------------------------------------------- lists
    def _lists(self) -> Dict[str, List[str]]:
        return {
            ids.LIST_COMPOSITE: sorted(self._composites()),
            ids.LIST_HARNESS: sorted(self._harnesses()),
            ids.LIST_CIRCUIT_FAMILY: sorted(
                {row[0][:2] for row in (self._current().circuits
                                        if self._current() else [])}),
        }

    # -------------------------------------------------------------- grids
    def _grids(self) -> Dict[str, Grid]:
        harness = self._current()
        composite_rows = ([[name, self._key().replace("|", " "), str(len(h))]
                           for name, h in sorted(self._composites().items())]
                          if self.filtered else [])
        blank = _Harness(name="", part_number="")
        h = harness or blank
        return {
            ids.GRID_COMPOSITE: Grid(["Composite", "Programme", "Harnesses"],
                                     composite_rows),
            ids.GRID_DEVICES: Grid(["CNUM", "Device", "Cavities", "Connector PN"],
                                   list(h.devices)),
            ids.GRID_CIRCUITS: Grid(
                ["Circuit", "Function", "Ends", "Sales Code", "Gauge", "Type"],
                list(h.circuits)),
            ids.GRID_SPLICES: Grid(["Splice", "Circuit", "Cavities", "Process"],
                                   list(h.splices)),
            ids.GRID_DEVICE_COMPLEXITY: Grid(
                ["CNUM", "Harness PN", "Sales Code"],
                [[d[0], h.part_number, ""] for d in h.devices]),
            ids.GRID_CIRCUIT_COMPLEXITY: Grid(
                ["Circuit", "Harness PN", "Sales Code"],
                [[c[0], h.part_number, c[3]] for c in h.circuits]),
            ids.GRID_SALES_CODES_EDIT: Grid(["Sales Code", "Harness PN", "State"],
                                            list(h.sales_codes)),
            ids.GRID_SALES_CODES_AVAILABLE: Grid(
                ["Sales Code", "Harness PN", "State"],
                [r for r in h.sales_codes if r[2] == "Available"]),
            ids.GRID_SALES_CODES_USED: Grid(
                ["Sales Code", "Harness PN", "State"],
                [r for r in h.sales_codes if r[2] == "Used"]),
            ids.GRID_INLINE_MATCH: Grid(["Inline", "Mate", "Harness", "Result"],
                                        list(h.inline_pairs)),
        }

    #: which filter box narrows which grid
    FILTERED_BY = {
        ids.GRID_DEVICES: ids.TEXT_FILTER,
        ids.GRID_CIRCUITS: ids.TEXT_FILTER_CIRCUIT,
        ids.GRID_SPLICES: ids.TEXT_FILTER_SPLICE,
        ids.GRID_DEVICE_COMPLEXITY: ids.TEXT_FILTER,
        ids.GRID_CIRCUIT_COMPLEXITY: ids.TEXT_FILTER_CIRCUIT_COMPLEXITY,
        ids.GRID_SALES_CODES_EDIT: ids.TEXT_FILTER_HARNESS_PN,
        ids.GRID_INLINE_MATCH: ids.TEXT_FILTER_INLINE,
    }

    #: a named filter narrows its own column; index into that grid's headers
    FILTERED_ON = {
        ids.GRID_CIRCUITS: 0,                 # Circuit
        ids.GRID_SPLICES: 0,                  # Splice
        ids.GRID_CIRCUIT_COMPLEXITY: 0,       # Circuit
        ids.GRID_INLINE_MATCH: 0,             # Inline
        ids.GRID_SALES_CODES_EDIT: 1,         # Harness PN
    }

    # -------------------------------------------------------------- verbs
    def exists(self, automation_id: str, scope: str = "") -> bool:
        return (automation_id in self._combos()
                or automation_id in self._lists()
                or automation_id in self._grids()
                or automation_id in self.filters
                or automation_id in self.checks
                or automation_id in {ids.BUTTON_FILTER, ids.RICH_RESULTS,
                                     ids.PANEL_SIGN_OFF,
                                     ids.PICTURE_INLINE_SIGN_OFF,
                                     ids.TEXT_CREATE_CAV_COUNT,
                                     ids.TEXT_CIRCUIT_FAMILY,
                                     ids.TEXT_SPLICE_NUMBER,
                                     ids.TAB_SALES_CODES, ids.TAB_INLINE})

    def _require(self, automation_id: str, scope: str = "") -> None:
        if not self.exists(automation_id, scope):
            raise ControlNotFound(automation_id, scope)

    def click(self, automation_id: str, scope: str = "") -> None:
        self._require(automation_id, scope)
        self._note(f"click {automation_id}")
        if automation_id == ids.BUTTON_FILTER:
            # the grid stays empty until all three combos are set, which is
            # what the application does and what a workflow must handle
            self.filtered = all((self.vehicle_line, self.model_year, self.phase))

    def text(self, automation_id: str, scope: str = "") -> str:
        self._require(automation_id, scope)
        if automation_id == ids.RICH_RESULTS:
            return self.results
        return self.filters.get(automation_id, "")

    def set_text(self, automation_id: str, value: str, scope: str = "") -> None:
        self._require(automation_id, scope)
        self._note(f"set {automation_id} = {value!r}")
        if automation_id in self.filters:
            self.filters[automation_id] = value

    def checked(self, automation_id: str, scope: str = "") -> bool:
        self._require(automation_id, scope)
        return self.checks.get(automation_id, False)

    def set_checked(self, automation_id: str, value: bool,
                    scope: str = "") -> None:
        self._require(automation_id, scope)
        self.checks[automation_id] = value
        self._note(f"check {automation_id} = {value}")

    def options(self, automation_id: str, scope: str = "") -> List[str]:
        combos, lists = self._combos(), self._lists()
        if automation_id in combos:
            return combos[automation_id].options()
        if automation_id in lists:
            return lists[automation_id]
        raise ControlNotFound(automation_id, scope)

    def selected(self, automation_id: str, scope: str = "") -> Optional[str]:
        combos = self._combos()
        if automation_id in combos:
            return combos[automation_id].value
        if automation_id == ids.LIST_COMPOSITE:
            return self.composite
        if automation_id == ids.LIST_HARNESS:
            return self.harness
        raise ControlNotFound(automation_id, scope)

    def select(self, automation_id: str, value: str, scope: str = "") -> None:
        combos = self._combos()
        if automation_id in combos:
            if value not in combos[automation_id].options():
                raise ControlNotFound(
                    f"{automation_id}[{value}]",
                    f"offered: {combos[automation_id].options()}")
            combos[automation_id].on_select(value)
            self._note(f"select {automation_id} = {value!r}")
            return
        if automation_id == ids.LIST_COMPOSITE:
            if value not in self._composites():
                raise ControlNotFound(f"{ids.LIST_COMPOSITE}[{value}]")
            self.composite, self.harness = value, None
        elif automation_id == ids.LIST_HARNESS:
            if value not in self._harnesses():
                raise ControlNotFound(f"{ids.LIST_HARNESS}[{value}]")
            self.harness = value
        elif automation_id == ids.LIST_CIRCUIT_FAMILY:
            self.filters[ids.TEXT_FILTER_CIRCUIT] = value
        else:
            raise ControlNotFound(automation_id, scope)
        self._note(f"select {automation_id} = {value!r}")

    def grid(self, automation_id: str, scope: str = "") -> Grid:
        grids = self._grids()
        if automation_id not in grids:
            raise ControlNotFound(automation_id, scope)
        found = grids[automation_id]
        rows = found.rows

        needle = self.filters.get(self.FILTERED_BY.get(automation_id, ""), "")
        if needle:
            low = needle.lower()
            # A filter box named for a column is modelled as filtering THAT
            # column; the generic TextBox_Filter matches anywhere in the row.
            # Which of the two DEF Editor really does is unverified — it can
            # only be checked in front of the application — so the workflow
            # reports exact matches alongside the row count rather than
            # trusting either reading.
            column = self.FILTERED_ON.get(automation_id)
            if column is not None and column < len(found.headers):
                rows = [r for r in rows
                        if column < len(r) and low in str(r[column]).lower()]
            else:
                rows = [r for r in rows if any(low in str(c).lower() for c in r)]

        if automation_id == ids.GRID_CIRCUITS:
            if self.checks.get(ids.CHECK_CKT_MISSING):
                rows = [r for r in rows if not r[3]]
            if self.checks.get(ids.CHECK_CKT_SINGLE_END):
                rows = [r for r in rows if r[2] == "1"]
        return Grid(list(found.headers), [list(r) for r in rows])

    def menu(self, *path: str) -> None:
        if path and path[0] not in ids.MENUS:
            raise ControlNotFound(" -> ".join(path), "top-level menu")
        self.last_menu = tuple(path)
        self.page = {
            ids.MENU_DEVICES: ids.UC_DEVICES,
            ids.MENU_CIRCUITS: ids.UC_CIRCUITS,
            ids.MENU_SPLICES: ids.UC_SPLICES,
            ids.MENU_COMPLEXITY: ids.UC_CIRCUITS_USAGE,
            ids.MENU_QUALITY_CHECKS: ids.UC_CHECKS_CONNECTORS,
        }.get(path[0], ids.UC_HARNESS_EDIT)
        self._note(f"menu {' -> '.join(path)}")

    def invoke(self, name: str, scope: str = "") -> None:
        self._note(f"invoke {name!r}")
        harness = self._current()
        pairs = harness.inline_pairs if harness else []
        if name in (ids.ACTION_RUN_ALL_PAIRS, ids.ACTION_RUN_SELECTED_PAIR):
            bad = [p for p in pairs if p[3] != "Match"]
            self.results = (
                f"Inline check: {len(pairs) - len(bad)} of {len(pairs)} pairs "
                f"match.\n" + "\n".join(f"MISMATCH {p[0]} <-> {p[1]}" for p in bad))
        elif name == ids.ACTION_SIGN_OFF_INLINE:
            # the application will not sign off over an open mismatch, and
            # neither will this: a workflow that signs off regardless is a
            # workflow that would have signed off a real defect
            if any(p[3] != "Match" for p in pairs) \
                    and not self.checks.get(ids.CHECK_INLINE_BYPASS):
                raise ControlNotFound(
                    ids.ACTION_SIGN_OFF_INLINE,
                    "disabled while a pair is failing")
            self.signed_off = True
        else:
            raise ControlNotFound(name, scope or "invokable")

    # ------------------------------------------------- quality check hook
    def run_connector_checks(self) -> str:
        harness = self._current()
        circuits = harness.circuits if harness else []
        single = [c for c in circuits if c[2] == "1"]
        lines = [f"Circuit validation for {self.harness or '(no harness)'}",
                 f"  circuits examined: {len(circuits)}"]
        if not self.checks.get(ids.CHECK_ENDS_BYPASS):
            lines.append(f"  single-ended circuits: {len(single)}")
            lines += [f"    {c[0]}" for c in single]
        else:
            lines.append("  ends check bypassed")
        if self.checks.get(ids.CHECK_ATTRIBUTES_BYPASS):
            lines.append("  attributes check bypassed")
        self.results = "\n".join(lines)
        return self.results
