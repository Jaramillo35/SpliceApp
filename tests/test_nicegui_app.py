"""The NiceGUI surface registers every route and builds every page tree.

The engines have their own suites; this guards the wiring — a page module
that fails to import or register would otherwise only fail at runtime.
"""

from __future__ import annotations

import pytest

nicegui = pytest.importorskip("nicegui")

EXPECTED_ROUTES = {
    "/", "/splice-generation", "/dtx-compare", "/harness-complexity",
    "/hrn-chart", "/vbom",
    "/circuit-health", "/secr", "/ask", "/transcripts", "/downloads",
}


def test_every_route_is_registered():
    import nicegui_app.main  # noqa: F401  (importing registers the routes)
    from nicegui import app

    paths = {getattr(r, "path", None) for r in app.routes}
    missing = EXPECTED_ROUTES - paths
    assert not missing, f"unregistered routes: {sorted(missing)}"


class TestWorkbenchHelpers:
    """Pure logic behind the Circuit Health workbench charts and filters."""

    def _result(self):
        from tests.test_inline_health import _analyze, LEFT_BUILDS, RIGHT_BUILDS
        return _analyze(
            [{"circuit": "R732", "cnum": "X10A", "cav": "8", "sc": "CG3"},
             {"circuit": "A960", "cnum": "X20A", "cav": "1", "sc": "CYF/CY3"},
             {"circuit": "A960", "cnum": "X21A", "cav": "1", "sc": "CYF"}],
            [{"circuit": "R732", "cnum": "Y10A", "cav": "8", "sc": "CG3&(CYC/CYF)"},
             {"circuit": "A960", "cnum": "Y20A", "cav": "1", "sc": "CYF/CY3"},
             {"circuit": "A960", "cnum": "Y21A", "cav": "1", "sc": "CYF"}],
            LEFT_BUILDS, RIGHT_BUILDS)

    def test_matrix_charts_and_filters(self):
        from nicegui_app.pages import circuit_health as ch
        r = self._result()
        m = ch.matrix_data(r.findings)
        assert set(m["names"]) == {"Left", "Right"}
        assert all("pair" in cell for cell in m["data"])
        assert ch.matrix_options(r.findings)["series"][0]["data"]
        assert ch.kind_bar_options(r.findings)["series"][0]["data"]

    def test_filters_compose(self):
        from nicegui_app.pages import circuit_health as ch
        r = self._result()
        blockers = ch.filter_findings(
            r.findings, {"severities": {"Blocker"}, "kind": None,
                         "pair": None, "query": ""})
        assert blockers and all(f.severity == "Blocker" for f in blockers)
        by_query = ch.filter_findings(
            r.findings, {"severities": set(), "kind": None,
                         "pair": None, "query": "a960"})
        assert by_query and all("A960" in f.circuit for f in by_query)

    def test_progress_segments_sum_to_one(self):
        from nicegui_app.pages import circuit_health as ch
        r = self._result()
        segments = ch.progress_segments(r, {"dispositions": {}})
        assert abs(sum(s[1] for s in segments) - 1.0) < 1e-6
