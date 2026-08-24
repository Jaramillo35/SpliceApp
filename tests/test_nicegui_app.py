"""The NiceGUI surface registers every route and builds every page tree.

The engines have their own suites; this guards the wiring — a page module
that fails to import or register would otherwise only fail at runtime.
"""

from __future__ import annotations

import pytest

nicegui = pytest.importorskip("nicegui")

EXPECTED_ROUTES = {
    "/", "/splice-generation", "/dtx-compare", "/hrn-chart", "/vbom",
    "/circuit-health", "/secr", "/ask", "/transcripts", "/downloads",
}


def test_every_route_is_registered():
    import nicegui_app.main  # noqa: F401  (importing registers the routes)
    from nicegui import app

    paths = {getattr(r, "path", None) for r in app.routes}
    missing = EXPECTED_ROUTES - paths
    assert not missing, f"unregistered routes: {sorted(missing)}"
