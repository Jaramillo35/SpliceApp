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
    "/circuit-applicability", "/circuit-health", "/secr", "/ask", "/transcripts", "/downloads",
    "/docs", "/admin", "/version",
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


class TestDocumentation:
    """The Markdown viewer: what it lists, what it opens on, what it renders."""

    def test_index_finds_the_shipped_docs(self):
        from nicegui_app.pages import docs
        rels = {d.rel for d in docs.repo_docs()}
        assert "README.md" in rels
        assert "docs/ARCHITECTURE.md" in rels
        assert all(r.endswith(".md") for r in rels)

    def test_index_prunes_tooling_and_hidden_trees(self):
        from nicegui_app.pages import docs
        rels = {d.rel for d in docs.repo_docs()}
        # .git/.github/.claude are instructions for tools, not for the reader;
        # a checkout with a .venv must not list the dependencies' READMEs
        assert not any(r.startswith(".") for r in rels)
        assert not any(part in docs.SKIP
                       for r in rels for part in r.split("/")[:-1])

    def test_documents_are_grouped_by_their_folder(self):
        from nicegui_app.pages import docs
        by_rel = {d.rel: d for d in docs.repo_docs()}
        assert by_rel["README.md"].group == docs.ROOT_GROUP
        assert by_rel["docs/ARCHITECTURE.md"].group == "docs"
        assert by_rel["docs/ARCHITECTURE.md"].title == "ARCHITECTURE"

    def test_root_documents_are_listed_first(self):
        from nicegui_app.pages import docs
        groups = [d.group for d in docs.repo_docs()]
        root_count = groups.count(docs.ROOT_GROUP)
        # the root block is contiguous and at the top, so the rail's first
        # heading is the README's, not "deploy"
        assert groups[:root_count] == [docs.ROOT_GROUP] * root_count
        assert docs.ROOT_GROUP not in groups[root_count:]

    def test_it_opens_on_the_readme_not_the_changelog(self):
        from nicegui_app.pages import docs
        found = docs.repo_docs()
        assert docs.opening_doc(found).rel == "README.md"
        assert docs.opening_doc([]) is None

    async def test_page_lists_and_renders(self, user):
        await user.open("/docs")
        await user.should_see("Documentation")
        # the index is grouped by folder and lists every shipped document
        await user.should_see("Project root")
        await user.should_see("ARCHITECTURE")
        # and the reader opens on the README rather than an empty panel
        await user.should_see("README")
