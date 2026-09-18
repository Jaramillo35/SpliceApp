"""Ask the Assistant — one chat over the SECR history and the engineer's files.

The assistant used to know the SECR database only. It is now general: the
same local model also has read-only tools that work on workbooks the
engineer puts in a **workspace** — describe a DTx export, find a circuit or a
connector in it, compare two exports, match a DTCR report. Nothing leaves
the machine.

Two panels:

* **Workspace** (left, sticky). What the assistant can read, said plainly:
  only the files listed, and they stay here. Add, remove, remove all. Each
  file says what it *looks like* — a guess from its name, shown and never
  relied on. The model only ever sees file names.
* **Conversation** (right). Under every answer, *what it did*: one block per
  tool call — the tool in the engineer's words, its arguments, the row
  count, truncation, and a tool error verbatim. Evidence is per call, not
  one merged table, because rows from different tools share no columns:
  whole numbers become figures, text becomes a facts line, row sets become
  tables. A compare or a DTCR match links to DTx Compare, where a person
  presses the button that writes a file — the chat never generates one.

Honest about the model: a quiet status check at load, Ask gated with the
reason when it is not ready, a note when the wording was rebuilt from the
records, and the seconds each answer took.

Seams for tests: ``build_assistant`` and ``model_status``.
"""

from __future__ import annotations

import logging
import uuid

from nicegui import app, run, ui

from nicegui_app import components as c
from nicegui_app import theme

log = logging.getLogger(__name__)

THREAD_KEY = "ask_thread"
SESSION_KEY = "ask_session"
EVIDENCE_CAP = 50

STARTERS_FILES = [
    "What changed between the two exports on BODY_LEFT?",
    "Where does circuit QK106 land?",
    "Which DTCRs did not match?",
]
STARTERS_HISTORY = [
    "Has connector D2784J changed before?",
    "Which harness family has the most changes?",
]

#: the file tools — everything else reads the SECR history
FILE_TOOLS = {"list_workspace_files", "describe_dtx", "find_circuit", "find_connector",
              "compare_dtx_exports", "match_dtcrs"}
#: tools whose result a person would turn into a deliverable on DTx Compare
LEADS_TO_COMPARE = {"compare_dtx_exports", "match_dtcrs"}

TOOL_WORDS = {
    "list_workspace_files": "Listed the workspace files",
    "describe_dtx": "Read what a DTx export contains",
    "find_circuit": "Found where a circuit lands in a DTx export",
    "find_connector": "Read everything at a connector in a DTx export",
    "compare_dtx_exports": "Compared two DTx exports",
    "match_dtcrs": "Matched a DTCR report to connectors and families",
    "list_known_values": "Listed the values the database holds",
    "search_secrs": "Searched the SECRs",
    "get_secr_summary": "Read a SECR's header",
    "get_changes_by_secr": "Read every change in a SECR",
    "get_changes_by_circuit": "Looked up a circuit in the SECR history",
    "get_changes_by_cnum": "Looked up a connector in the SECR history",
    "get_changes_by_endpoint": "Looked up what is wired to a connector",
    "get_connector_changes": "Looked up a connector part number",
    "get_changes_by_dtcr": "Looked up what a DTCR changed",
    "get_changes_by_harness": "Read the changes on a harness family",
    "get_change_counts": "Counted changes",
    "get_program_summary": "Summarised a program",
    "get_model_year_summary": "Summarised a model year",
    "get_revision_chain": "Read a SECR's version history",
    "get_database_summary": "Summarised the database",
}
ARG_WORDS = {"old_file": "old", "new_file": "new", "dtcr_file": "DTCR report",
             "file": "file", "cnum": "CNUM", "dtcr_number": "DTCR",
             "secr_number": "SECR", "connector_pn": "connector PN"}
FIGURE_WORDS = {
    "added_cnum_count": "Added CNUMs", "removed_cnum_count": "Removed CNUMs",
    "added_circuit_count": "Added circuits", "removed_circuit_count": "Removed circuits",
    "modified_circuit_count": "Modified circuits", "changes_total": "Changes",
    "dtcrs": "DTCRs", "matched": "Matched", "unmatched": "Unmatched",
    "circuit_rows": "Circuit rows", "circuits": "Circuits", "connectors": "Connectors",
}
#: a non-zero value here is worth a second look
WATCH = {"unmatched"}


# ------------------------------------------------------------------ seams
def build_assistant():
    """The general assistant over the app's database and workspace."""
    from secrdb.assistant.general import general_assistant
    from secrdb.assistant.ollama import OllamaClient
    return general_assistant(client=OllamaClient())


def model_status():
    """Whether the local model can answer, without raising."""
    from secrdb.assistant.ollama import OllamaClient
    return OllamaClient().status()


# ------------------------------------------------------------ persistence
def _load_thread() -> list[dict]:
    """The stored thread. Empty when there is no user storage (tests, or a
    page built outside a request)."""
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


# ------------------------------------------------- a tool call, for display
def words(key: str) -> str:
    return str(key).replace("_", " ").strip().capitalize()


def _plain(value):
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    return value


def _rows(items: list) -> list[dict]:
    return [{str(k): _plain(v) for k, v in dict(r).items()}
            for r in items[:EVIDENCE_CAP] if isinstance(r, dict)]


def pack_call(result) -> dict:
    """One ToolResult as plain, capped, JSON-safe display data.

    Restructured for reading, never recomputed: whole numbers become
    ``figures``, text becomes ``facts``, lists of records become ``tables``.
    A value that only repeats an argument is dropped.
    """
    arguments = {str(k): _plain(v) for k, v in dict(result.arguments or {}).items()
                 if v not in (None, "")}
    call = {"name": result.name, "arguments": arguments,
            "row_count": int(result.row_count or 0),
            "truncated": bool(result.truncated), "error": str(result.error or ""),
            "facts": {}, "figures": {}, "tables": []}
    data = result.data
    if isinstance(data, list):
        call["tables"].append({"title": "Rows", "rows": _rows(data), "total": len(data)})
    elif isinstance(data, dict):
        said = {str(v) for v in arguments.values()}
        for key, value in data.items():
            if isinstance(value, bool) or value is None:
                continue
            if isinstance(value, int):
                call["figures"][str(key)] = value
            elif isinstance(value, (str, float)):
                if str(value) and str(value) not in said:
                    call["facts"][str(key)] = str(value)
            elif isinstance(value, dict):
                for k, v in value.items():
                    if isinstance(v, int) and not isinstance(v, bool):
                        call["figures"][str(k)] = v
            elif isinstance(value, list) and value:
                if isinstance(value[0], dict):
                    call["tables"].append({"title": words(key), "rows": _rows(value),
                                           "total": len(value)})
                else:
                    call["facts"][str(key)] = ", ".join(str(v) for v in value[:20])
    return call


def _arguments(arguments: dict) -> str:
    return " · ".join(f"{ARG_WORDS.get(k, words(k).lower())} {v}"
                      for k, v in arguments.items())


def _call_block(call: dict) -> None:
    name = call.get("name", "")
    from_files = name in FILE_TOOLS
    with ui.column().classes("w-full gap-2 rounded px-3 py-2") \
            .style(f"background:{theme.SURFACE_2};border:1px solid {theme.LINE}"):
        with ui.row().classes("w-full items-center gap-2 flex-wrap"):
            ui.icon("description" if from_files else "storage").classes("text-base") \
                .style(f"color:{theme.TEXT_3}")
            ui.label(TOOL_WORDS.get(name, words(name) or "Evidence")) \
                .classes("text-sm font-semibold")
            ui.label("your files" if from_files else "SECR history").classes("sx-eyebrow")
            ui.element("div").classes("grow")
            if not call.get("error"):
                ui.label(f"{int(call.get('row_count') or 0):,} row(s)").classes("sx-caption")
            if call.get("truncated"):
                c.chip("review", "truncated — narrow the question")
        if call.get("arguments"):
            ui.label(_arguments(call["arguments"])).classes("text-xs sx-mono sx-muted break-all")
        if call.get("error"):
            c.note("blocker", call["error"])
            return
        if call.get("facts"):
            ui.label(" · ".join(f"{words(k)}: {v}" for k, v in call["facts"].items())) \
                .classes("sx-caption")
        if call.get("figures"):
            with c.kpi_strip():
                for key, value in call["figures"].items():
                    kind = ("review" if value else "ok") if key in WATCH else None
                    c.kpi(int(value), FIGURE_WORDS.get(key, words(key)), kind)
        for table in call.get("tables") or []:
            rows, total = table.get("rows") or [], int(table.get("total") or 0)
            if not rows:
                continue
            with ui.expansion(f"{table.get('title') or 'Rows'} · {total:,}") \
                    .classes("w-full").props("dense"):
                c.frame_table(rows)
                if total > len(rows):
                    ui.label(f"Showing {len(rows)} of {total:,} — ask a narrower question "
                             "to see the rest.").classes("sx-caption")
        if name in LEADS_TO_COMPARE:
            with ui.row().classes("items-center gap-1"):
                ui.label("To write the workbook for this, use").classes("sx-caption")
                ui.link("DTx Compare", "/dtx-compare").classes("text-xs")


# ---------------------------------------------------------------- bubbles
def _user_bubble(text: str) -> None:
    with ui.row().classes("w-full justify-end"):
        ui.label(text).classes("text-sm px-3 py-2 rounded-xl max-w-[85%]") \
            .style(f"background:{theme.wash(theme.BRAND)}")


def _assistant_message(message: dict) -> None:
    calls = list(message.get("calls") or [])
    legacy = list(message.get("evidence") or [])      # threads stored before the trail
    if legacy and not calls:
        calls = [{"name": "", "arguments": {}, "row_count": len(legacy), "truncated": False,
                  "error": "", "facts": {}, "figures": {},
                  "tables": [{"title": "Rows", "rows": legacy, "total": len(legacy)}]}]
    with ui.column().classes("w-full items-start gap-2"):
        ui.markdown(str(message.get("text", ""))) \
            .classes("text-sm px-3 py-2 rounded-xl w-fit max-w-[85%]") \
            .style(f"background:{theme.SURFACE}")
        if message.get("fallback"):
            c.note("review", "The model's wording could not be checked against what it "
                             "retrieved, so this answer was written from the records "
                             "themselves.")
        if message.get("found_nothing"):
            c.note("info", "The tools ran and found nothing for this question.")
        if calls:
            seconds = message.get("seconds")
            ui.label(f"What it did · {len(calls)} tool call(s)"
                     + (f" · answered in {float(seconds):.0f} s" if seconds and seconds >= 1 else "")) \
                .classes("sx-eyebrow mt-1")
            for call in calls:
                _call_block(call)


def _render(message: dict) -> None:
    role = message.get("role")
    if role == "user":
        _user_bubble(str(message.get("text", "")))
    elif role == "note":
        c.note("high", str(message.get("text", "")))
    else:
        _assistant_message(message)


# ------------------------------------------------------------------- page
@ui.page("/ask")
def page() -> None:
    with c.frame("Ask the Assistant",
                 "Questions over the SECR history and the files in your workspace — "
                 "answered by the local model, with what it looked at."):
        from secrdb.assistant import workspace
        from secrdb.config import ASSISTANT_ENABLED, OLLAMA_HOST, OLLAMA_MODEL

        if not ASSISTANT_ENABLED:
            with c.card("Ask"):
                c.note("info", "The assistant is disabled by configuration "
                               "(SECRDB_ASSISTANT). Browse and search still "
                               "work from the SECR Database page.")
            return

        state: dict = {"status": None, "busy": False, "upload_notes": []}
        file_starters: list = []

        with ui.element("div").classes(
                "w-full grid gap-6 items-start grid-cols-1 lg:grid-cols-[22rem_minmax(0,1fr)]"):
            # ------------------------------------------------ workspace
            with ui.card().classes("sx-card sx-reveal w-full gap-3 lg:sticky lg:top-20"):
                ui.label("Workspace").classes("sx-section")
                ui.label("The assistant can only read the files listed here. They stay "
                         "on this machine; the model is given their names, never a path.") \
                    .classes("sx-caption -mt-1")

                def add_file(name: str, data: bytes) -> None:
                    try:
                        workspace.save_file(name, data)
                    except workspace.WorkspaceError as exc:
                        state["upload_notes"].append(str(exc))     # said as written
                    files_view.refresh()

                c.upload_row("Add workbooks (.xls, .xlsx, .xlsm)", add_file,
                             accept=".xls,.xlsx,.xlsm", multiple=True)

                @ui.refreshable
                def files_view() -> None:
                    for text in state["upload_notes"]:
                        c.note("blocker", text)
                    state["upload_notes"] = []
                    files = workspace.list_files()
                    for button in file_starters:
                        button.set_enabled(bool(files))
                    if not files:
                        c.empty("No files yet. Add DTx exports or a DTCR report to ask "
                                "about them — questions about the SECR history need "
                                "none.", icon="folder_open")
                        return
                    with ui.row().classes("w-full items-center justify-between no-wrap"):
                        ui.label(f"Files · {len(files)}").classes("sx-eyebrow")
                        ui.button("Remove all", on_click=lambda: remove_all()) \
                            .props("flat dense no-caps")
                    for f in files:
                        with ui.row().classes("w-full items-center gap-2 no-wrap rounded px-2 py-1") \
                                .style(f"background:{theme.SURFACE_2};border:1px solid {theme.LINE}"):
                            with ui.column().classes("gap-0 min-w-0 grow"):
                                ui.label(f["file"]).classes("text-xs sx-mono break-all")
                                ui.label(f"looks like: {f['kind']} · {f['size_kb']} KB · "
                                         f"added {f['added']}").classes("sx-caption")
                            ui.button(icon="close",
                                      on_click=lambda _e, n=f["file"]: remove(n)) \
                                .props(f'flat dense round size=sm aria-label="Remove {f["file"]}"') \
                                .tooltip("Remove from the workspace")

                def remove(name: str) -> None:
                    workspace.delete_file(name)
                    files_view.refresh()

                def remove_all() -> None:
                    workspace.clear()
                    files_view.refresh()

                files_view()

            # --------------------------------------------- conversation
            with ui.card().classes("sx-card sx-reveal w-full gap-3"):
                with ui.row().classes("w-full items-center justify-between no-wrap"):
                    ui.label("Conversation").classes("sx-section")
                    ui.button("Clear thread", icon="delete_sweep",
                              on_click=lambda: clear()).props("flat dense no-caps")
                ui.label(f"Model {OLLAMA_MODEL} via {OLLAMA_HOST} — runs entirely on this "
                         "machine. An answer takes about 10 to 30 seconds; the first one "
                         "after a pause can take longer, and comparing workbooks adds a "
                         "few seconds.").classes("sx-caption -mt-1")

                @ui.refreshable
                def status_view() -> None:
                    status = state["status"]
                    if status is None:
                        return
                    if getattr(status, "ready", False):
                        c.chip("ok", "model ready")
                    else:
                        c.note("high", getattr(status, "message", "")
                               or "The local model is not reachable — is Ollama running? "
                                  "The rest of the app is unaffected.")

                status_view()
                thread_view = ui.column().classes("w-full gap-3")

                def not_ready() -> list[str]:
                    status = state["status"]
                    if status is not None and not getattr(status, "ready", False):
                        return ["the local model (see above)"]
                    return []

                with ui.row().classes("w-full gap-2 items-start no-wrap"):
                    box = ui.input("Ask about your files or the SECR history",
                                   placeholder="e.g. where does circuit QK106 land?") \
                        .classes("flex-1").props("dense")
                    ask_action = c.action("Ask", lambda: ask(), needs=not_ready, icon="send")
                box.on("keydown.enter", lambda: ask())

                for title, starters, needs_files in (
                        ("About your files", STARTERS_FILES, True),
                        ("About the SECR history", STARTERS_HISTORY, False)):
                    with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                        ui.label(title).classes("sx-eyebrow w-44 shrink-0")
                        for q in starters:
                            button = ui.button(q, on_click=lambda q=q: ask_starter(q)) \
                                .props("outline dense no-caps")
                            if needs_files:
                                file_starters.append(button)
                files_view.refresh()          # the file starters exist now; gate them

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

        async def check_status() -> None:
            try:
                state["status"] = await run.io_bound(model_status)
            except Exception as exc:  # noqa: BLE001 — a status check must never break the page
                log.debug("model status not read: %s", exc)
                return
            status_view.refresh()
            ask_action.check()

        async def ask_starter(question: str) -> None:
            box.set_value(question)
            await ask()

        async def ask() -> None:
            question = (box.value or "").strip()
            if not question or state["busy"] or not_ready():
                return
            state["busy"] = True
            box.value = ""
            remember({"role": "user", "text": question})
            with thread_view:
                _user_bubble(question)
                with ui.row().classes("items-center gap-2") as waiting:
                    ui.spinner(size="sm")
                    ui.label("Asking the local model — usually 10 to 30 seconds.") \
                        .classes("sx-caption")

            def work():
                return build_assistant().ask(question, session_id=session)

            answer = await c.run_engine(work, running="Asking the local model…",
                                        done="Answered")
            waiting.delete()
            state["busy"] = False
            if answer is None:
                message = {"role": "note",
                           "text": "The assistant is unreachable — is Ollama "
                                   "running? The rest of the app is unaffected."}
            elif getattr(answer, "timed_out", False):
                message = {"role": "note",
                           "text": "The model did not answer in time — usually a "
                                   "cold start. Ask again in a moment."}
            elif getattr(answer, "error", ""):
                message = {"role": "note",
                           "text": f"The assistant could not answer: {answer.error}"}
            else:
                message = {"role": "assistant",
                           "text": str(getattr(answer, "answer", "") or ""),
                           "calls": [pack_call(r) for r in getattr(answer, "evidence", [])],
                           "fallback": bool(getattr(answer, "fallback_used", False)),
                           "found_nothing": bool(getattr(answer, "found_nothing", False)),
                           "seconds": float(getattr(answer, "elapsed_seconds", 0) or 0)}
            remember(message)
            with thread_view:
                _render(message)
            _scroll_to_bottom()

        ui.timer(0.1, check_status, once=True)
