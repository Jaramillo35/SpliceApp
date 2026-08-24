"""Meeting Transcripts — NiceGUI page over splice.transcripts.recorder.

The Recorder is process-wide on purpose (recording must survive navigation);
the page is a live remote control with a 1s status timer.
"""

from __future__ import annotations

from datetime import datetime

from nicegui import ui

from nicegui_app import components as c
from splice.transcripts import recorder as rec

_recorder = rec.Recorder()  # one per process, like the Streamlit cache_resource


@ui.page("/transcripts")
def page() -> None:
    with c.frame("Meeting Transcripts",
                 "Teams Live Captions → anonymized markdown (Speaker 1..N, "
                 "names never on disk), with built-in LLM instructions for "
                 "minutes."):

        with c.card("Recorder"):
            if not rec.CAPTURE_AVAILABLE:
                c.chip("info", "Capture runs on the Windows install — this "
                               "machine can browse transcripts below")
            status_row = ui.row().classes("items-center gap-3 flex-wrap")
            tail_box = ui.column().classes("w-full gap-0")

            with ui.row().classes("gap-2"):
                btn_start = ui.button("Start recording", icon="fiber_manual_record",
                                      on_click=lambda: (_recorder.start(), render())) \
                    .props("unelevated")
                btn_pause = ui.button("Pause", icon="pause",
                                      on_click=lambda: (_recorder.pause(), render())) \
                    .props("outline")
                btn_resume = ui.button("Resume", icon="play_arrow",
                                       on_click=lambda: (_recorder.resume(), render())) \
                    .props("outline")
                btn_finish = ui.button("Finish transcript", icon="stop",
                                       on_click=lambda: (_recorder.stop(), render())) \
                    .props("outline")

            def render() -> None:
                s = _recorder.status()
                status_row.clear()
                tail_box.clear()
                state = s["state"]
                with status_row:
                    kind = {"recording": "ok", "paused": "high",
                            "waiting": "info", "error": "blocker"}.get(state, "info")
                    c.chip(kind, state.capitalize() if state != "waiting"
                           else "Waiting for a captions window")
                    if state in ("recording", "paused"):
                        ui.label(f"{s['entries']} entries · {s['speakers']} speakers "
                                 f"→ {s['output'].rsplit('/', 1)[-1]}") \
                            .classes("text-sm sx-muted")
                    if state == "error":
                        ui.label(s["error"]).classes("text-sm") \
                            .style(f"color:{c.theme.STATUS['blocker']}")
                with tail_box:
                    for line in s["tail"][-8:]:
                        ui.label(line).classes("text-xs sx-mono sx-muted")
                running = _recorder.running
                btn_start.set_enabled(rec.CAPTURE_AVAILABLE and not running)
                btn_pause.set_visibility(state == "recording")
                btn_resume.set_visibility(state == "paused")
                btn_finish.set_visibility(state in ("recording", "paused", "waiting"))

            render()
            ui.timer(1.0, render)

        with c.card("Saved transcripts", f"Folder: {rec.TRANSCRIPTS_DIR}"):
            with ui.row().classes("gap-2"):
                ui.button("Open transcripts folder", icon="folder_open",
                          on_click=lambda: _open_folder()).props("outline dense")

            @ui.refreshable
            def listing() -> None:
                files = rec.list_transcripts()
                if not files:
                    c.empty("No transcripts yet. Start a recording during a "
                            "Teams meeting with Live Captions on.")
                    return
                for path in files:
                    stat = path.stat()
                    with ui.row().classes("items-center gap-3 w-full"):
                        c.download_button(path.name, lambda p=path: p.read_bytes())
                        ui.label(f"{stat.st_size / 1024:.0f} KB · "
                                 f"{datetime.fromtimestamp(stat.st_mtime):%Y-%m-%d %H:%M}") \
                            .classes("text-xs sx-muted")

            listing()
            ui.timer(10.0, listing.refresh)

        with c.card("Minutes"):
            ui.label("Every transcript starts with instructions for an AI "
                     "assistant — paste the whole file into your LLM and the "
                     "minutes (summary, decisions, action points, pending "
                     "items, risks) come back directly.").classes("text-sm sx-muted")


def _open_folder() -> None:
    try:
        rec.open_transcripts_folder()
    except Exception as exc:
        ui.notify(f"Could not open a file manager: {exc}", type="warning")
