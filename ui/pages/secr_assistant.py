"""Ask the SECR database a question, in plain language.

The page is thin: it renders the backend status, sends the question to
:class:`secrdb.assistant.agent.Assistant`, and shows the answer with the records
it was built from. Every answer arrives with its evidence, because an answer
about an engineering record is only worth as much as what backs it.

When Ollama is not reachable the page explains how to start it and the rest of
the app is unaffected — the assistant is an addition to the database, not a
dependency of it.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from secrdb import diagnostics
from secrdb.assistant.agent import Assistant
from secrdb.assistant.ollama import OllamaClient
from secrdb.config import ASSISTANT_ENABLED, OLLAMA_HOST, OLLAMA_MODEL
from ui.support import render_support_panel, session_id

#: Questions that show what the assistant is for. Clicking one asks it.
EXAMPLE_QUESTIONS = [
    "When did circuit A111 change?",
    "Has connector D2784J changed before?",
    "Which harness family has the most changes?",
    "What changed in SECR D50319A?",
    "What did DTCR 50319 change?",
]

#: Columns worth showing in the evidence table, when present.
_EVIDENCE_COLUMNS = [
    ("secr_number", "SECR"),
    ("harness_family", "Harness"),
    ("program", "Program"),
    ("model_year", "MY"),
    ("action", "Type"),
    ("object_type", "Object"),
    ("object_id", "ID"),
    ("field", "Field"),
    ("old_value", "Old"),
    ("new_value", "New"),
    ("dtcr_number", "DTCR"),
]


def render() -> None:
    st.title("Ask the Database")
    st.caption(
        "Questions are answered from the SECR records themselves. The model "
        "runs on this machine — nothing is sent anywhere."
    )

    if not ASSISTANT_ENABLED:
        st.info(
            "The assistant is switched off. Set `SECRDB_ASSISTANT=1` to enable it."
        )
        render_support_panel(where="assistant")
        return

    client = OllamaClient()
    status = client.status()
    _render_status(status)

    if status.ready:
        # Start the model loading now, while the page is being read and a
        # question typed, rather than charging that wait to the first question.
        if not st.session_state.get("secrdb_warmed"):
            st.session_state["secrdb_warmed"] = True
            client.warm()
        _render_examples()
        _render_history()
        question = st.chat_input("Ask about a circuit, connector, DTCR or SECR…")
        if question:
            _ask(client, question)
            st.rerun()

    render_support_panel(where="assistant")


# ---------------------------------------------------------------------------
# Backend status
# ---------------------------------------------------------------------------

def _render_status(status) -> None:
    if status.ready:
        st.success(
            f"Local model ready — `{status.model}` on `{status.host}`", icon="✅"
        )
        return

    if not status.reachable:
        st.warning(
            f"**The assistant is unavailable.** {status.message}", icon="⚠️"
        )
        with st.expander("How to start it"):
            st.markdown(
                f"""
The assistant needs [Ollama](https://ollama.com) running on this machine (or
on an internal host set as `OLLAMA_HOST`, currently `{OLLAMA_HOST}`).

1. Install Ollama.
2. Pull the model once:
   ```
   ollama pull {OLLAMA_MODEL}
   ```
3. Ollama starts with Windows. If it isn't running, launch it and reload
   this page.

**The first question after starting Ollama is slow** — a few minutes while
the model loads from disk. Later questions in the same session answer in
seconds. Opening this page starts that load in the background, so the wait
happens while you type rather than after you ask.

Everything else in the app works without it — browsing, importing,
creating and updating SECRs are unaffected.
                """
            )
        return

    st.warning(f"**The model is not installed.** {status.message}", icon="⚠️")
    st.code(f"ollama pull {status.model}", language="bash")
    if status.installed_models:
        st.caption("Installed on this machine: " + ", ".join(status.installed_models))
        st.caption(
            "To use one of those instead, set `SECRDB_OLLAMA_MODEL` to its name."
        )


# ---------------------------------------------------------------------------
# Asking
# ---------------------------------------------------------------------------

def _history() -> List[Any]:
    return st.session_state.setdefault("secrdb_assistant_history", [])


def _render_examples() -> None:
    if _history():
        return
    st.caption("Try one of these:")
    columns = st.columns(len(EXAMPLE_QUESTIONS))
    for column, question in zip(columns, EXAMPLE_QUESTIONS):
        if column.button(question, key=f"example_{question}", width="stretch"):
            st.session_state["secrdb_pending_question"] = question
            st.rerun()


def _ask(client: OllamaClient, question: str) -> None:
    assistant = Assistant(client=client)
    with st.spinner("Reading the database…"):
        answer = assistant.ask(question, session_id=session_id())
    _history().append(answer)


def _render_history() -> None:
    pending = st.session_state.pop("secrdb_pending_question", None)
    if pending:
        _ask(OllamaClient(), pending)

    for index, answer in enumerate(_history()):
        with st.chat_message("user"):
            st.write(answer.question)
        with st.chat_message("assistant"):
            _render_answer(answer, index)


def _render_answer(answer, index: int) -> None:
    if not answer.ok:
        # A cold start is not a failure, and presenting it as one sends people
        # to reinstall Ollama. Say what is happening and what to do.
        if answer.timed_out:
            st.warning(answer.error, icon="⏳")
            st.caption(
                "The model stays loaded for a while after it finishes, so "
                "later questions in this session will be much faster."
            )
        else:
            st.error(answer.error)
        return

    st.markdown(answer.answer or "_No answer was produced._")

    if answer.fallback_used:
        st.caption(
            "⚠️ Built directly from the records below — the model's own wording "
            "could not be verified against them."
        )

    rows = answer.rows
    if rows:
        st.caption(f"Records used ({len(rows)})")
        st.dataframe(
            _evidence_frame(rows), width="stretch", hide_index=True, height=240
        )
    elif not answer.fallback_used:
        st.caption("No records matched.")

    with st.expander("How this was answered"):
        st.markdown(
            f"**Tools called:** {len(answer.tool_calls)} · "
            f"**Rounds:** {answer.rounds} · "
            f"**Time:** {answer.elapsed_seconds}s · "
            f"**Grounded:** {'yes' if answer.grounded else 'no'}"
        )
        if answer.tool_calls:
            st.dataframe(
                pd.DataFrame(answer.tool_calls), width="stretch", hide_index=True
            )
        report = answer.grounding_report
        if report and not report.grounded:
            st.markdown("**Rejected by the grounding check:**")
            st.code(", ".join(report.ungrounded))
            st.caption(
                "These appeared in the model's wording but not in any retrieved "
                "record, so the wording was discarded."
            )

    if st.button(
        "This didn't answer my question",
        key=f"secrdb_unanswered_{index}",
        help="Records it so it reaches the developer in the issue report.",
    ):
        diagnostics.record_unanswered(
            answer.question,
            reason="Marked unhelpful by the user.",
            tools_called=answer.tool_calls,
            session_id=session_id(),
        )
        st.success("Recorded — export the issue report from the sidebar.")


def _evidence_frame(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    """Show the columns an engineer reads, and only those that are present."""
    present = [
        (key, label) for key, label in _EVIDENCE_COLUMNS if any(key in row for row in rows)
    ]
    if not present:
        return pd.DataFrame(rows)
    frame = pd.DataFrame(
        [{label: row.get(key) for key, label in present} for row in rows]
    )
    return frame.astype(object).where(frame.notna(), "")


render()
