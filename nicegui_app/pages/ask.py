"""Ask the Database — chat over the local SECR assistant (Ollama).

Archetype C, Records. The thread survives a reload (per-user storage), every
answer lands with the records it was built from, and the page scrolls to
the newest bubble.
"""

from __future__ import annotations

import logging
import uuid

from nicegui import app, ui

from nicegui_app import components as c
from nicegui_app import theme

log = logging.getLogger(__name__)

EXAMPLES = [
    "When did a given circuit last change?",
    "Has a specific connector changed before?",
    "Which harness family has the most changes?",
]
THREAD_KEY = "ask_thread"
SESSION_KEY = "ask_session"
EVIDENCE_CAP = 50


# ------------------------------------------------------------ persistence
def _load_thread() -> list[dict]:
    """The stored thread: a list of {role, text, evidence}. Empty when there
    is no user storage (tests, or a page built outside a request)."""
    try:
        stored = app.storage.user.get(THREAD_KEY, [])
        return [dict(m) for m in stored if isinstance(m, dict)]
    except Exception:  # noqa: BLE001 — no user storage in tests
        return []


def _save_thread(thread: list[dict]) -> None:
    try:
        app.storage.user[THREAD_KEY] = thread
    except Exception as exc:  # noqa: BLE001 — no user storage in tests
        log.debug("ask thread not persisted: %s", exc)


def _session_id() -> str:
    """The assistant's conversation id, kept with the thread so a reload
    continues the same conversation on the model side."""
    try:
        sid = app.storage.user.get(SESSION_KEY)
        if not sid:
            sid = str(uuid.uuid4())[:8]
            app.storage.user[SESSION_KEY] = sid
        return str(sid)
    except Exception:  # noqa: BLE001 — no user storage in tests
        return str(uuid.uuid4())[:8]


def _scroll_to_bottom() -> None:
    try:
        ui.run_javascript("window.scrollTo(0, document.body.scrollHeight)")
    except Exception as exc:  # noqa: BLE001 — no browser in tests
        log.debug("scroll skipped: %s", exc)


# ---------------------------------------------------------------- bubbles
def _user_bubble(text: str) -> None:
    with ui.row().classes("w-full justify-end"):
        ui.label(text).classes("text-sm px-3 py-2 rounded-xl max-w-[85%]") \
            .style(f"background:{theme.wash(theme.BRAND)}")


def _assistant_bubble(text: str, evidence: list[dict]) -> None:
    with ui.column().classes("w-full items-start gap-1"):
        ui.markdown(text).classes("text-sm px-3 py-2 rounded-xl w-fit max-w-[85%]") \
            .style(f"background:{theme.SURFACE}")
        if evidence:
            with ui.expansion(f"Evidence ({len(evidence)})").classes("w-full").props("dense"):
                c.frame_table(evidence, cap=EVIDENCE_CAP)


def _render(message: dict) -> None:
    if message.get("role") == "user":
        _user_bubble(str(message.get("text", "")))
    elif message.get("role") == "note":
        c.note("high", str(message.get("text", "")))
    else:
        _assistant_bubble(str(message.get("text", "")), list(message.get("evidence") or []))


def _evidence_rows(answer) -> list[dict]:
    rows = getattr(answer, "rows", None) or []
    return [{str(k): ("" if v is None else str(v)) for k, v in dict(r).items()}
            for r in rows[:EVIDENCE_CAP]]


# ------------------------------------------------------------------- page
@ui.page("/ask")
def page() -> None:
    with c.frame("Ask the Database",
                 "Plain-language questions over the SECR history; every answer "
                 "arrives with the records it was built from."):
        from secrdb.config import ASSISTANT_ENABLED, OLLAMA_HOST, OLLAMA_MODEL

        with c.card("Ask"):
            if not ASSISTANT_ENABLED:
                c.note("info", "The assistant is disabled by configuration "
                               "(SECRDB_ASSISTANT). Browse and search still "
                               "work from the SECR Database page.")
                return
            with ui.row().classes("w-full items-center justify-between no-wrap"):
                ui.label(f"Model {OLLAMA_MODEL} via {OLLAMA_HOST} — runs entirely "
                         "on-premises.").classes("sx-caption")
                ui.button("Clear thread", icon="delete_sweep",
                          on_click=lambda: clear()).props("flat dense no-caps")
            thread_view = ui.column().classes("w-full gap-2")
            with ui.row().classes("w-full gap-2 items-end no-wrap"):
                box = ui.input("Ask about SECRs, circuits, connectors or harnesses",
                               placeholder="e.g. when did circuit A937 last change?") \
                    .classes("flex-1").props("dense")
                ui.button("Ask", icon="send", on_click=lambda: ask()).props("unelevated no-caps")
            box.on("keydown.enter", lambda: ask())
            with ui.row().classes("gap-2 flex-wrap"):
                for q in EXAMPLES:
                    ui.button(q, on_click=lambda q=q: (box.set_value(q), ask())) \
                        .props("outline dense no-caps")

        thread: list[dict] = _load_thread()
        session = _session_id()

        with thread_view:
            for message in thread:
                _render(message)

        def remember(message: dict) -> None:
            thread.append(message)
            _save_thread(thread)

        def clear() -> None:
            thread.clear()
            _save_thread(thread)
            thread_view.clear()

        async def ask() -> None:
            question = (box.value or "").strip()
            if not question:
                return
            box.value = ""
            remember({"role": "user", "text": question, "evidence": []})
            with thread_view:
                _user_bubble(question)
                placeholder = ui.spinner(size="sm")

            def work():
                from secrdb.assistant.agent import Assistant
                from secrdb.assistant.ollama import OllamaClient
                assistant = Assistant(client=OllamaClient())
                return assistant.ask(question, session_id=session)

            answer = await c.run_engine(work, running="Asking the local model…",
                                        done="Answered")
            placeholder.delete()
            if answer is None:
                message = {"role": "note", "evidence": [],
                           "text": "The assistant is unreachable — is Ollama "
                                   "running? The rest of the app is unaffected."}
            elif getattr(answer, "timed_out", False):
                message = {"role": "note", "evidence": [],
                           "text": "The model did not answer in time — usually a "
                                   "cold start. Ask again in a moment."}
            elif getattr(answer, "error", ""):
                message = {"role": "note", "evidence": [],
                           "text": f"The assistant could not answer: {answer.error}"}
            else:
                message = {"role": "assistant",
                           "text": str(getattr(answer, "answer", "") or ""),
                           "evidence": _evidence_rows(answer)}
            remember(message)
            with thread_view:
                _render(message)
            _scroll_to_bottom()
