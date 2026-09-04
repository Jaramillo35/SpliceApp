"""The chart engine against a generated programme, not a customer export.

The scale work behind ``fixtures_scale`` was originally validated on a real
DTx. These hold the generated stand-in to the same job: it has to survive the
actual readers, match the actual matcher, and put every shape the chart engine
cares about in front of it. A fixture that quietly stopped producing splices,
or inlines, or No Connects would make the benchmark meaningless while still
passing — so each of those is asserted, not assumed.

Timing is deliberately NOT asserted here. A test that compares durations
passes on the unfixed code often enough to prove nothing; the loop-stall
measurement lives in ``scripts/benchmark_chart.py``, where it is read rather
than gated on.
"""

from __future__ import annotations

import pytest

from splice.dtxcircuits import (
    analyze_harness, integrity, matching, read_dtx_circuits,
)
from splice.dtxcircuits import chart as chart_mod
from splice.dtxcircuits import report as report_mod
from splice.dtxcircuits.analyze import union_condition
from splice.dtxcircuits.complexity import read_harness_file
from tests import fixtures_scale as fx

FAMILIES = 12


@pytest.fixture(scope="module")
def programme():
    return fx.programme(families=FAMILIES)


@pytest.fixture(scope="module")
def loaded(programme):
    """The invented workbooks, put back through the real readers."""
    rows, meta = read_dtx_circuits(programme.dtx_bytes(), programme.dtx_name)
    harnesses, metas = {}, {}
    for family in programme.families:
        name = programme.complexity_name(family)
        harness, cmeta = read_harness_file(
            programme.complexity_bytes(family), name)
        harnesses[name], metas[name] = harness, cmeta
    return rows, meta, harnesses, metas


@pytest.fixture(scope="module")
def charts(loaded):
    rows, _, harnesses, metas = loaded
    names = sorted({r.harness_family for r in rows})
    mapping = matching.auto_map(
        names, {f: (metas[f].harness or harnesses[f].name) for f in harnesses})
    fixed = integrity.apply_fixes(rows, {})

    def conditions_by(subset, attribute):
        grouped = {}
        for row in subset:
            key = getattr(row, attribute, "")
            if key:
                grouped.setdefault(key, []).append(row)
        return {k: (union_condition(v) or "") for k, v in grouped.items()}

    entries = []
    for family, filename in sorted(mapping.items()):
        harness = harnesses[filename]
        label = metas[filename].harness or harness.name
        entries.append(report_mod.Entry(
            label=f"{family} → {label}", family=family, filename=filename,
            analysis=analyze_harness(
                [r for r in fixed if r.harness_family == family], harness,
                harness_name=label),
            original_circuit_conditions=conditions_by(
                [r for r in rows if r.harness_family == family], "circuit"),
            original_cnum_conditions=conditions_by(
                [r for r in rows if r.harness_family == family], "cnum"),
            complexity=harness))
    return entries, fixed, chart_mod.build_charts(entries, fixed)


class TestTheFixtureIsUsable:
    def test_the_dtx_survives_the_real_reader(self, programme, loaded):
        rows, meta, _, _ = loaded
        assert len(rows) == len(programme.rows)
        assert meta.program == fx.PROGRAM
        assert meta.phase == fx.PHASE

    def test_the_programme_is_deterministic(self):
        """A benchmark whose input drifts between runs measures nothing."""
        assert fx.programme(families=4).dtx_bytes() \
            == fx.programme(families=4).dtx_bytes()

    def test_every_family_matches_its_complexity_file(self, loaded):
        rows, _, harnesses, metas = loaded
        names = sorted({r.harness_family for r in rows})
        mapping = matching.auto_map(
            names,
            {f: (metas[f].harness or harnesses[f].name) for f in harnesses})
        assert len(mapping) == len(names) == FAMILIES


class TestItExercisesWhatTheChartDoes:
    def test_no_connects_are_dropped_and_counted(self, programme, charts):
        _, _, built = charts
        assert programme.no_connect_rows > 0, "the fixture must plant some"
        assert sum(c.no_connect_rows for c in built) \
            == programme.no_connect_rows
        assert not any(r.circuit == "N0" for c in built for r in c.rows)

    def test_circuits_reaching_three_cavities_get_a_splice(self, charts):
        _, _, built = charts
        assert sum(len(c.splices) for c in built) > 0
        assert any(r.is_splice for c in built for r in c.rows)

    def test_wires_find_their_far_end_inside_the_harness(self, charts):
        _, _, built = charts
        rows = [r for c in built for r in c.rows]
        wired = [r for r in rows if r.other_cnum]
        assert len(wired) > 0.9 * len(rows), \
            "nearly every end should name the end it runs to"

    def test_inlines_mate_across_the_harness_boundary(self, charts):
        """A mate is a joint to the NEXT harness, never a wire in this one."""
        _, _, built = charts
        mated = [(c, r) for c in built for r in c.rows if r.mate_cnum]
        assert mated, "the X/Y inline pairs must be found across families"
        for chart, row in mated:
            assert row.mate_family != chart.family
            assert row.cnum.startswith(("X", "Y"))
            assert row.mate_cnum.startswith(("X", "Y"))
            assert row.mate_cnum != row.cnum

    def test_part_numbers_carry_a_share_of_the_rows(self, charts):
        _, _, built = charts
        for chart in built:
            assert chart.part_numbers
            carried = [chart.coverage(pn) for pn in chart.part_numbers]
            assert max(carried) > 0, f"{chart.family} carries nothing"


class TestProgressReporting:
    def test_the_build_reports_once_per_family_and_finishes(self, charts):
        entries, rows, _ = charts
        seen = []
        chart_mod.build_charts(
            entries, rows, progress=lambda f, m: seen.append((f, m)))
        # one per family, plus the cross-harness linking pass at the end
        assert len(seen) == len(entries) + 1
        fractions = [f for f, _ in seen]
        assert fractions == sorted(fractions)
        assert fractions[0] == 0.0
        assert fractions[-1] <= 1.0

    def test_progress_is_optional(self, charts):
        """The engine is called without a callback by tests and scripts."""
        entries, rows, built = charts
        assert len(chart_mod.build_charts(entries, rows)) == len(built)
