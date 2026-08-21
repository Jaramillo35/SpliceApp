"""The support panel: report a problem, export a report.

This build is being field-tested on machines nobody can log into, so the app
carries its own black box. The panel lives in the sidebar, which is visible on
every page, and does three things:

* lets the engineer describe what went wrong, in their words
* shows what the app has already recorded on its own
* exports the lot as one file to attach to an email

Nothing is transmitted. Export is a download the user chooses to send.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

import streamlit as st

from secrdb import diagnostics

try:  # pragma: no cover - import path differs across Streamlit versions
    from streamlit.runtime.scriptrunner_utils.exceptions import (
        ScriptControlException,
    )

    #: Belt and braces alongside the ``BaseException`` rule in :func:`guard`,
    #: in case a future Streamlit re-parents these under ``Exception``.
    _CONTROL_FLOW_EXCEPTIONS: tuple = (ScriptControlException,)
except Exception:  # noqa: BLE001 - the BaseException check still covers us
    _CONTROL_FLOW_EXCEPTIONS = ()


def session_id() -> str:
    """A short id tying together everything recorded in one sitting."""
    if "secrdb_session_id" not in st.session_state:
        st.session_state["secrdb_session_id"] = uuid.uuid4().hex[:8]
    return st.session_state["secrdb_session_id"]


def record_error(exc: BaseException, *, where: str, **context: Any) -> None:
    """Record an exception and tell the user it was captured."""
    issue = diagnostics.record_error(
        exc, where=where, context=context, session_id=session_id()
    )
    st.error(
        f"Something went wrong: {exc}\n\n"
        f"This was recorded as issue `{issue.issue_id}`. Use **Report a problem** "
        "in the sidebar to export it."
    )


def guard(where: str, **context: Any):
    """Record any *error* raised inside a page section, and keep rendering.

    Without this a Streamlit traceback is shown to the engineer and then lost
    when they reload — exactly the report we need most.

    **Streamlit control flow must pass straight through.** ``st.rerun()`` and
    ``st.stop()`` are implemented by raising ``RerunException`` /
    ``StopException``, which the script runner catches to do its job. Swallowing
    one cancels the rerun *and* halts the rest of the render, so a filter click
    silently blanks the page. Those classes derive from ``BaseException`` rather
    than ``Exception`` precisely because they are signals, not failures — which
    makes ``isinstance(exc, Exception)`` the version-independent test for "is
    this a real error?". The same rule correctly lets KeyboardInterrupt and
    SystemExit through.
    """

    class _Guard:
        def __enter__(self) -> "_Guard":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            if exc is None:
                return False
            if not isinstance(exc, Exception) or isinstance(
                exc, _CONTROL_FLOW_EXCEPTIONS
            ):
                return False  # control flow — let Streamlit handle it
            record_error(exc, where=where, **context)
            return True  # handled: the page keeps rendering

    return _Guard()


def render_support_panel(where: str = "") -> None:
    """The sidebar panel. Called once per page render."""
    with st.sidebar:
        st.divider()
        st.markdown("### Report a problem")
        st.caption(
            "Found a bug, or asked something the assistant could not answer? "
            "Describe it, then export the report and email it."
        )

        issues = diagnostics.load_issues()
        recorded = len(issues)
        errors = sum(1 for issue in issues if issue.get("kind") == diagnostics.KIND_ERROR)
        unanswered = sum(
            1 for issue in issues if issue.get("kind") == diagnostics.KIND_UNANSWERED
        )

        with st.form("secrdb_report_form", clear_on_submit=True):
            message = st.text_area(
                "What happened?",
                placeholder=(
                    "e.g. Imported 12 files, 3 failed with 'no Summary sheet' — "
                    "they open fine in Excel."
                ),
                height=110,
            )
            submitted = st.form_submit_button("Record it")
        if submitted:
            if message.strip():
                diagnostics.record_feedback(
                    message.strip(), where=where, session_id=session_id()
                )
                st.success("Recorded. Export below and send me the file.")
                st.rerun()
            else:
                st.warning("Add a short description first.")

        if recorded:
            summary = f"{recorded} item(s) recorded"
            details = []
            if errors:
                details.append(f"{errors} error(s)")
            if unanswered:
                details.append(f"{unanswered} unanswered question(s)")
            if details:
                summary += " — " + ", ".join(details)
            st.caption(summary)
        else:
            st.caption("Nothing recorded yet.")

        st.download_button(
            "⬇ Export issue report",
            data=diagnostics.export_bytes(session_id=session_id()),
            file_name=diagnostics.export_filename(),
            mime="application/json",
            width="stretch",
            help=(
                "One JSON file: what the app recorded, plus versions and "
                "database size. Send it to the developer."
            ),
        )

        with st.expander("What's in the report?"):
            st.markdown(
                "- Anything you wrote above\n"
                "- Errors the app caught, with their tracebacks\n"
                "- Questions the assistant could not answer\n"
                "- App/Python/library versions, OS, and how many SECRs and "
                "changes the database holds\n\n"
                "It does **not** include your SECR files or the database "
                "itself — only counts and error messages."
            )

        if recorded:
            with st.expander(f"Recorded items ({recorded})"):
                for issue in reversed(issues[-25:]):
                    kind = issue.get("kind", "?")
                    st.markdown(
                        f"**{kind}** · `{issue.get('issue_id','')}` · "
                        f"{issue.get('at','')}"
                    )
                    st.caption(issue.get("summary", ""))
                if st.button("Clear recorded items", key="secrdb_clear_issues"):
                    diagnostics.clear_issues()
                    st.rerun()


def debug_expander(title: str, payload: Dict[str, Any]) -> None:
    """A collapsed panel of raw values, for diagnosing a report after the fact."""
    with st.expander(f"🔧 {title}", expanded=False):
        st.json(payload, expanded=False)


def environment_panel() -> None:
    """Environment and database state, shown on request."""
    with st.expander("🔧 Environment & database", expanded=False):
        st.json(diagnostics.environment(), expanded=False)
