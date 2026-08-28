"""The showcase dataset must actually work in every engine it claims to.

A demo pack that fails in front of an audience is worse than none, so these
regenerate the files and push them through the real readers — asserting not
just that they load, but that each planted defect is still found. If an engine
changes shape, this fails here rather than live.
"""

from __future__ import annotations

import tempfile
import warnings
from pathlib import Path

import pytest

from demo import showcase

warnings.filterwarnings("ignore")


class _Upload:
    """The .name/.getbuffer() surface the VBOM workflow expects."""

    def __init__(self, path: Path):
        self.name = path.name
        self._data = path.read_bytes()

    def getbuffer(self):
        return self._data

    def getvalue(self):
        return self._data

    def read(self):
        return self._data


@pytest.fixture(scope="module")
def built() -> Path:
    with tempfile.TemporaryDirectory(prefix="showcase_") as td:
        out = Path(td)
        showcase.build(out)
        yield out


class TestNoCustomerData:
    def test_programme_is_invented(self):
        # the real programmes are RU/DT/KM/WS/EJ/KX — none may appear
        assert showcase.VEHICLE not in {"RU", "DT", "KM", "WS", "EJ", "KX"}

    def test_part_numbers_are_a_reserved_range(self):
        for builds in showcase.BUILDS.values():
            for build in builds:
                assert build.pn.startswith("99"), build.pn

    def test_every_sales_code_is_documented(self):
        used = {c for circuits in showcase.CIRCUITS.values() for x in circuits
                for c in x.condition.replace("-", " ").replace("&", " ")
                .replace("/", " ").replace("(", " ").replace(")", " ").split()}
        assert used <= set(showcase.SALES_CODES), used - set(showcase.SALES_CODES)


class TestCircuitApplicability:
    def test_dtx_declares_its_own_programme_and_phase(self, built):
        from splice.dtxcircuits import read_dtx_circuits
        path = next((built / "1_circuit_applicability").glob("DetailedDTx*.xlsx"))
        rows, meta = read_dtx_circuits(path.read_bytes(), path.name)
        assert meta.program == showcase.PROGRAM
        assert meta.phase == showcase.PHASE
        assert len(rows) > 20

    def test_planted_never_built_circuit_is_found(self, built):
        from splice.dtxcircuits import analyze_harness, read_dtx_circuits
        from splice.dtxcircuits.complexity import read_harness_file
        d = built / "1_circuit_applicability"
        rows, _meta = read_dtx_circuits(
            next(d.glob("DetailedDTx*.xlsx")).read_bytes(), "dtx")
        harness, _cm = read_harness_file(
            next(d.glob("*_IP_*.xlsx")).read_bytes(), "ip")
        analysis = analyze_harness([r for r in rows if r.harness_family == "IP"],
                                   harness, harness_name="IP")
        # QA1&QA2 — the two roof codes never ship together
        assert [c.circuit for c in analysis.findings] == ["QK107"]

    def test_planted_code_gap_is_found(self, built):
        from splice.dtxcircuits import analyze_harness, read_dtx_circuits
        from splice.dtxcircuits.complexity import read_harness_file
        d = built / "1_circuit_applicability"
        rows, _meta = read_dtx_circuits(
            next(d.glob("DetailedDTx*.xlsx")).read_bytes(), "dtx")
        harness, _cm = read_harness_file(
            next(d.glob("*_IP_*.xlsx")).read_bytes(), "ip")
        analysis = analyze_harness([r for r in rows if r.harness_family == "IP"],
                                   harness, harness_name="IP")
        assert [g.code for g in analysis.code_gaps] == ["QZ9"]

    def test_a_family_has_no_complexity_file(self, built):
        # HEADLINER exists in the DTx only, so the mapping demo has a red row
        from splice.dtxcircuits import read_dtx_circuits
        d = built / "1_circuit_applicability"
        rows, _meta = read_dtx_circuits(
            next(d.glob("DetailedDTx*.xlsx")).read_bytes(), "dtx")
        assert "HEADLINER" in {r.harness_family for r in rows}
        assert not list(d.glob("*HEADLINER*"))

    def test_one_file_does_not_auto_match_its_family(self, built):
        from splice.dtxcircuits import matching
        d = built / "1_circuit_applicability"
        assert list(d.glob("*DOOR_FRONT_LEFT_MAIN*")), "the near-miss file is gone"
        mapping = matching.auto_map(["DOOR_FRONT_LEFT"],
                                    {"f": "DOOR_FRONT_LEFT_MAIN"})
        assert mapping == {}, "it must stay a candidate, not auto-connect"
        assert matching.suggest(["DOOR_FRONT_LEFT"],
                                {"f": "DOOR_FRONT_LEFT_MAIN"})["DOOR_FRONT_LEFT"]


class TestVbom:
    def test_workflow_runs_and_fills_the_review_gate(self, built):
        from splice.vbom import run_vbom_workflow
        d = built / "2_vbom_risk_matrix"
        with tempfile.TemporaryDirectory() as td:
            result = run_vbom_workflow(
                my="30", program="QX", source_type="BuildSpec",
                input_upload=_Upload(next(d.glob("*BuildSpec*.xlsx"))),
                complexity_uploads=[_Upload(p) for p in
                                    sorted(d.glob("2.- Harness*.xlsx"))],
                output_dir=Path(td))
            assert len(result["vin_matrix_df"]) == len(showcase.VINS)
            assert result["review_case_count"] > 0, \
                "the demo must have something to resolve"
            assert Path(result["review_path"]).is_file()


class TestHarnessComplexity:
    def test_master_yields_a_reviewable_matrix(self, built):
        from splice.harnesscx import adapters
        d = built / "3_harness_complexity"
        crossref = adapters.load_crossref(
            (d / "Harness_Family_CrossRef.xlsx").read_bytes())
        frames = adapters.read_dtx_frames(
            [("dtx", next(d.glob("DTx_SalesCodes*.xlsx")).read_bytes())])
        universe = adapters.dtx_sales_code_universe(frames)
        assert universe, "the flat DTx must supply the sales-code universe"
        matrix = adapters.extract_family_matrix(
            next(d.glob("*_NEW.xlsx")).read_bytes(), "IP", universe, "IP")
        assert matrix.sales_codes and matrix.rows
        assert matrix.year == showcase.YEAR and matrix.phase == showcase.PHASE
        # the planted review material
        assert matrix.excluded_count == 1, "the DELETE row"
        assert any(r.current_class.value == "inferred" for r in matrix.rows), \
            "the C/O carryover"
        exprs = {c.original_expr for c in matrix.combined_exprs}
        assert "QB1+(QA1/QA2)" in exprs and "QA1=QA2" in exprs

    def test_old_master_is_missing_a_code_so_compare_has_a_delta(self, built):
        from splice.harnesscx import adapters, compare
        d = built / "3_harness_complexity"
        crossref = adapters.load_crossref(
            (d / "Harness_Family_CrossRef.xlsx").read_bytes())
        frames = adapters.read_dtx_frames(
            [("dtx", next(d.glob("DTx_SalesCodes*.xlsx")).read_bytes())])
        universe = adapters.dtx_sales_code_universe(frames)
        changes = compare.compare_complexity(
            next(d.glob("*_OLD.xlsx")).read_bytes(),
            next(d.glob("*_NEW.xlsx")).read_bytes(), crossref, universe)
        assert any("QF1" in c.added_codes for c in changes)


class TestCircuitHealth:
    def test_the_planted_inline_defect_is_found(self, built):
        from splice.inline import health
        from splice.inline.complexity import read_complexity
        from splice.inline.pairing import resolve
        from splice.inline.summary import read_circuit_summary
        d = built / "6_circuit_health"
        harnesses, ends = read_circuit_summary(
            next(d.glob("Circuit_Summary*.xlsx")).read_bytes(), "cs")
        complexity = {}
        for path in d.glob("2.- Harness*.xlsx"):
            cx = read_complexity(path.read_bytes(), path.name)
            if cx.def_id in harnesses:
                complexity[cx.def_id] = cx
        pairs, unmated = resolve(ends, set(harnesses))
        assert pairs, "X350/Y350 must pair, or there is nothing to check"
        result = health.analyze(harnesses, ends, complexity, pairs, unmated)
        blockers = [f for f in result.findings if f.severity == health.SEV_BLOCKER]
        assert blockers, "the planted cavity-2 defect vanished"
        assert blockers[0].cavity == "2"


class TestOtherSections:
    def test_splice_generation_workbook_loads(self, built):
        from splice.splice_gen.processor import (
            load_complexity_matrix, load_option_per_circuit)
        path = next((built / "5_splice_generation").glob("*.xlsx"))
        harness_map, _df = load_complexity_matrix(path)
        options = load_option_per_circuit(path)
        assert harness_map and len(options) > 5

    def test_hrn_filename_parses_to_the_family(self, built):
        from splice.hrncmp.engine import parse_hrn_filename
        path = next((built / "7_hrn_chart_builder").glob("*.hrn"))
        info = parse_hrn_filename(path.stem)
        assert info.family == "IP"
        assert info.model_year == "2030" and info.program == "QX"

    def test_the_hrn_triple_is_complete(self, built):
        d = built / "7_hrn_chart_builder"
        assert len(list(d.glob("*.hrn"))) == 1
        assert len(list(d.glob("*.csv"))) == 1
        assert len(list(d.glob("*.cmp"))) == 1

    def test_dtx_compare_pair_differs(self, built):
        from splice.dtxcircuits import read_dtx_circuits
        d = built / "4_dtx_compare"
        old, _m1 = read_dtx_circuits(next(d.glob("*_OLD.xlsx")).read_bytes(), "o")
        new, _m2 = read_dtx_circuits(next(d.glob("*_NEW.xlsx")).read_bytes(), "n")
        added = {r.circuit for r in new} - {r.circuit for r in old}
        assert added == {"QK106", "QK702"}
