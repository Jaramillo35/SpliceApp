"""Test plugins for the NiceGUI pages.

``nicegui.testing.user_plugin`` provides the ``user`` fixture: a simulated
client that opens a page, finds elements and clicks, with no browser. It is
what makes a page refactor provable.

One thing it needs from us. Between tests NiceGUI resets its route table,
then re-runs the main file with ``runpy`` to register the pages again. But
``main.py`` registers pages by *importing* ``nicegui_app.pages.*`` — and
those modules are already in ``sys.modules`` when any earlier test imported
the app, so the ``@ui.page`` decorators do not run again and every page is
a 404. In isolation the page tests passed; in the full suite all ten failed
the same way. The fixture below evicts the app's modules before each
simulated-user test so the re-run really re-registers them.
"""

from __future__ import annotations

import sys

import pytest

pytest_plugins = ["nicegui.testing.user_plugin"]


@pytest.fixture(autouse=True)
def _fresh_pages_for_simulated_user(request):
    if "user" in request.fixturenames:
        for name in list(sys.modules):
            if name == "nicegui_app.main" or name.startswith("nicegui_app.pages"):
                del sys.modules[name]
    yield


@pytest.fixture(autouse=True)
def _activity_feed_in_tmp(tmp_path, monkeypatch):
    """The engine runners append every completed run to data/activity.jsonl;
    a test run must not land in the engineer's Overview."""
    from splice.common import activity
    monkeypatch.setattr(activity, "ACTIVITY_PATH", tmp_path / "activity.jsonl")
    yield
