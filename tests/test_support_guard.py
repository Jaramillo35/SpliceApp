"""Tests for the page error guard.

The guard exists to capture real failures for the issue report. It must not
capture Streamlit's control flow: ``st.rerun()`` and ``st.stop()`` are
implemented by *raising*, and swallowing one cancels the rerun and halts the
render — which is exactly the "I clicked Browse and nothing showed" bug the
first field reports contained.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from secrdb import diagnostics


@pytest.fixture(autouse=True)
def isolated_diagnostics(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(diagnostics, "DATA_DIR", tmp_path)


@pytest.fixture()
def guard(monkeypatch):
    """The guard, with Streamlit's own output stubbed out."""
    from ui import support

    monkeypatch.setattr(support.st, "error", lambda *a, **k: None)
    return support.guard


# ---------------------------------------------------------------------------
# Control flow must pass through
# ---------------------------------------------------------------------------

def test_a_rerun_is_not_swallowed(guard) -> None:
    """st.rerun() raises; the guard must let it reach the script runner."""
    from streamlit.runtime.scriptrunner_utils.exceptions import RerunException

    with pytest.raises(RerunException):
        with guard("browse"):
            raise RerunException(None)

    assert diagnostics.load_issues() == []  # not an error, so not recorded


def test_a_stop_is_not_swallowed(guard) -> None:
    from streamlit.runtime.scriptrunner_utils.exceptions import StopException

    with pytest.raises(StopException):
        with guard("browse"):
            raise StopException()

    assert diagnostics.load_issues() == []


def test_keyboard_interrupt_is_not_swallowed(guard) -> None:
    """Any BaseException is a signal, not a failure to report."""
    with pytest.raises(KeyboardInterrupt):
        with guard("browse"):
            raise KeyboardInterrupt()

    assert diagnostics.load_issues() == []


# ---------------------------------------------------------------------------
# Real errors are captured
# ---------------------------------------------------------------------------

def test_a_real_error_is_recorded_and_suppressed(guard) -> None:
    with guard("browse", table="secr"):
        raise ValueError("database is locked")

    issues = diagnostics.load_issues()
    assert len(issues) == 1
    assert "database is locked" in issues[0]["summary"]
    assert issues[0]["where"] == "browse"
    assert issues[0]["context"]["table"] == "secr"
    assert "Traceback" in issues[0]["detail"]


def test_the_page_continues_after_a_real_error(guard) -> None:
    """Suppressing is the point: one broken tab must not blank the app."""
    reached = []
    with guard("browse"):
        raise RuntimeError("boom")
    reached.append("after")

    assert reached == ["after"]


def test_nothing_is_recorded_when_nothing_fails(guard) -> None:
    with guard("browse"):
        pass
    assert diagnostics.load_issues() == []
