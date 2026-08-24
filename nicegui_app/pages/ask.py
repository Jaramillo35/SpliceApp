"""Ask the Database — chat over the local SECR assistant (Ollama)."""

from __future__ import annotations

import uuid

from nicegui import ui

from nicegui_app import components as c
from nicegui_app import theme

EXAMPLES = [
    "When did circuit A111 change?",
    "Has connector D2784J changed before?",
    "Which harness family has the most changes?",
]


@ui.page("/ask")
def page() -> None:
    session = str(uuid.uuid4())[:8]

    with c.frame("Ask the Database",
                 "Plain-language questions over the SECR history; every answer "
                 "arrives with the records it was built from."):
        from secrdb.config import ASSISTANT_ENABLED, OLLAMA_HOST, OLLAMA_MODEL

        with c.card():
            if not ASSISTANT_ENABLED:
                c.chip("info", "Assistant disabled by configuration")
                return
            ui.label(f"Model {OLLAMA_MODEL} via {OLLAMA_HOST} — runs entirely "
                     "on-premises.").classes("text-xs sx-muted")
            thread = ui.column().classes("w-full gap-2")
            with ui.row().classes("w-full gap-2 items-end"):
                box = ui.input(placeholder="Ask about any SECR, circuit, "
                                           "connector, or harness…") \
                    .classes("flex-1").props("dense")
                ui.button("Ask", icon="send", on_click=lambda: ask()).props("unelevated")
            with ui.row().classes("gap-2 flex-wrap"):
                for q in EXAMPLES:
                    ui.button(q, on_click=lambda q=q: (box.set_value(q), ask())) \
                        .props("outline dense no-caps")

        async def ask() -> None:
            question = (box.value or "").strip()
            if not question:
                return
            box.value = ""
            with thread:
                with ui.row().classes("w-full justify-end"):
                    ui.label(question).classes("text-sm px-3 py-2 rounded-xl") \
                        .style(f"background:{theme.BRAND}33")
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
                with thread:
                    ui.label("The assistant is unreachable — is Ollama running? "
                             "The rest of the app is unaffected.") \
                        .classes("text-sm").style(f"color:{theme.STATUS['high']}")
                return
            with thread:
                with ui.column().classes("w-full items-start gap-1"):
                    ui.markdown(str(getattr(answer, "text", answer))) \
                        .classes("text-sm px-3 py-2 rounded-xl w-fit max-w-[85%]") \
                        .style(f"background:{theme.SURFACE}")
                    evidence = getattr(answer, "records", None) or \
                        getattr(answer, "evidence", None)
                    if evidence:
                        with ui.expansion(f"Evidence ({len(evidence)})") \
                                .classes("w-full").props("dense"):
                            rows = [{k: str(v) for k, v in dict(r).items()}
                                    for r in evidence[:50]]
                            if rows:
                                ui.table(rows=rows, columns=[
                                    {"name": k, "label": k, "field": k,
                                     "align": "left"} for k in rows[0]]) \
                                    .classes("w-full").props("dense flat")
