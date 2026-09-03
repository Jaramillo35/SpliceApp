"""Meeting Transcripts — NiceGUI page over splice.transcripts.recorder.

The Recorder is process-wide on purpose (recording must survive navigation);
the page is a live remote control with a 1s status timer. Because it is one
per process, the page says so: what it shows is the state of this machine's
recorder, not something shared between users of the toolkit.
"""

from __future__ import annotations

from datetime import datetime

from nicegui import ui

from nicegui_app import components as c
from splice.transcripts import recorder as rec

_recorder = rec.Recorder()  # one per process, like the Streamlit cache_resource

PER_MACHINE = ("The recorder runs on this machine only — recordings and this "
               "status are not shared with other users of the toolkit.")


@ui.page("/transcripts")
def page() -> None:
    with c.frame("Meeting Transcripts",
                 "Teams Live Captions → anonymized markdown (Speaker 1..N, "
                 "names never on disk), with built-in LLM instructions for "
                 "minutes."):

        consent_dialog = _consent_dialog(lambda cs: _start_named(cs, render))

        with c.card("Recorder"):
            c.note("info", PER_MACHINE)
            if not rec.CAPTURE_AVAILABLE:
                c.chip("info", "Capture runs on the Windows install — this "
                               "machine can browse transcripts below")
            status_row = ui.row().classes("items-center gap-3 flex-wrap")
            tail_box = ui.column().classes("w-full gap-0")

            with ui.row().classes("gap-2"):
                btn_start = ui.button("Start recording", icon="fiber_manual_record",
                                      on_click=lambda: (_recorder.start(), render())) \
                    .props("unelevated no-caps")
                btn_named = ui.button("Record with names…", icon="badge",
                                      on_click=consent_dialog.open) \
                    .props("outline dense no-caps")
                btn_pause = ui.button("Pause", icon="pause",
                                      on_click=lambda: (_recorder.pause(), render())) \
                    .props("outline dense no-caps")
                btn_resume = ui.button("Resume", icon="play_arrow",
                                       on_click=lambda: (_recorder.resume(), render())) \
                    .props("outline dense no-caps")
                btn_finish = ui.button("Finish transcript", icon="stop",
                                       on_click=lambda: (_recorder.stop(), render())) \
                    .props("outline dense no-caps")

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
                    # The mode is the privacy-relevant fact — always visible.
                    if state in ("recording", "paused", "waiting"):
                        c.chip("high" if s["record_names"] else "ok",
                               "Names recorded (attested)" if s["record_names"]
                               else "Anonymized — Speaker 1..N")
                    if state in ("recording", "paused"):
                        ui.label(f"{s['entries']} entries · {s['speakers']} speakers "
                                 f"→ {s['output'].rsplit('/', 1)[-1]}") \
                            .classes("text-sm sx-muted")
                    if state == "error":
                        c.note("blocker", s["error"])
                with tail_box:
                    for line in s["tail"][-8:]:
                        ui.label(line).classes("text-xs sx-mono sx-muted")
                running = _recorder.running
                btn_start.set_enabled(rec.CAPTURE_AVAILABLE and not running)
                btn_named.set_enabled(rec.CAPTURE_AVAILABLE and not running)
                btn_pause.set_visibility(state == "recording")
                btn_resume.set_visibility(state == "paused")
                btn_finish.set_visibility(state in ("recording", "paused", "waiting"))

            render()
            ui.timer(1.0, render)

        with c.card("Saved transcripts", f"Folder: {rec.TRANSCRIPTS_DIR}"):
            with ui.row().classes("gap-2"):
                ui.button("Open transcripts folder", icon="folder_open",
                          on_click=lambda: _open_folder()).props("outline dense no-caps")

            @ui.refreshable
            def listing() -> None:
                files = rec.list_transcripts()
                if not files:
                    c.empty("No transcripts yet. Start a recording during a "
                            "Teams meeting with Live Captions on.")
                    return
                if len(files) > 1:
                    c.downloads([(p.name, lambda p=p: p.read_bytes()) for p in files],
                                label=f"{len(files)} transcripts")
                for path in files:
                    stat = path.stat()
                    with ui.row().classes("items-center gap-3 w-full no-wrap"):
                        c.download(path.name, lambda p=path: p.read_bytes())
                        ui.label(f"{stat.st_size / 1024:.0f} KB · "
                                 f"{datetime.fromtimestamp(stat.st_mtime):%Y-%m-%d %H:%M}") \
                            .classes("sx-caption")

            listing()
            ui.timer(10.0, listing.refresh)

        with c.card("Minutes"):
            ui.label("Every transcript starts with instructions for an AI "
                     "assistant — paste the whole file into your LLM and the "
                     "minutes (summary, decisions, action points, pending "
                     "items, risks) come back directly.").classes("text-sm sx-muted")

        with c.card("Privacy",
                    "Anonymized is the default and needs no permission."):
            ui.markdown(
                "**Anonymized (default).** Speakers become Speaker 1..N and no "
                "name ever reaches the disk, so there is no personal data to "
                "protect.\n\n"
                "**With names.** Real names on disk are personal data. Use "
                "*Record with names* only after you have told the participants "
                "the meeting is being transcribed for a minute report **and** "
                "asked their permission — the dialog gives you a message to "
                "send them. Your confirmation, your name, the time, and the "
                "exact notice you sent are written into the transcript, so the "
                "file is its own compliance record. Anyone who objects is "
                "reason enough to stay anonymized.\n\n"
                "Names spoken inside a sentence are never removed in either "
                "mode — the captions give no reliable way to detect them."
            ).classes("text-sm")


def _open_folder() -> None:
    try:
        rec.open_transcripts_folder()
    except Exception as exc:  # noqa: BLE001 — no file manager is a warning, not a crash
        ui.notify(f"Could not open a file manager: {exc}", type="warning")


def _start_named(consent: rec.Consent, render) -> None:
    """Start a named recording; the engine refuses an incomplete attestation."""
    try:
        _recorder.start(record_names=True, consent=consent)
    except Exception as exc:  # noqa: BLE001 — the engine's refusal is shown, whatever it is
        ui.notify(str(exc), type="negative", multi_line=True, close_button=True)
        return
    ui.notify("Recording with participant names — the attestation is written "
              "into the transcript.", type="positive", multi_line=True)
    render()


def _consent_dialog(on_confirm) -> ui.dialog:
    """Privacy gate for named recording: send the notice, then attest to it."""
    with ui.dialog() as dialog, ui.card().classes("w-[42rem] sx-card"):
        ui.label("Record participant names").classes("sx-section")
        ui.label("Names on disk are personal data. Confirm you have told the "
                 "participants and have their permission — your confirmation "
                 "is written into the transcript as the compliance record.") \
            .classes("text-sm sx-muted")

        ui.label("1 · Send this to the participants").classes(
            "text-sm font-semibold mt-2")
        notice = ui.textarea(value=rec.PARTICIPANT_NOTICE) \
            .classes("w-full").props("outlined autogrow dense")
        ui.label("Edit it if you said something different — what you send here "
                 "is what the transcript records as the notice given.") \
            .classes("sx-caption")

        def copy_notice() -> None:
            ui.clipboard.write(notice.value or "")
            ui.notify("Message copied — paste it in the meeting chat", type="positive")

        with ui.row().classes("gap-2"):
            ui.button("Copy message", icon="content_copy", on_click=copy_notice) \
                .props("outline dense no-caps")

        ui.label("2 · Confirm what you did").classes("text-sm font-semibold mt-2")
        boxes = [ui.checkbox(text).classes("text-sm")
                 for _key, text in rec.ATTESTATIONS]
        signer = ui.input("Your name (signs the attestation)") \
            .classes("w-full").props("dense outlined")
        notes = ui.input("Notes (optional — e.g. who agreed, or who opted out)") \
            .classes("w-full").props("dense outlined")

        # the one inline error line: empty until the engine names what is missing
        blockers = ui.column().classes("w-full gap-0")

        def confirm() -> None:
            consent = rec.Consent(
                announced=boxes[0].value, permission_granted=boxes[1].value,
                notice_text=notice.value or rec.PARTICIPANT_NOTICE,
                notes=notes.value or "")
            consent.sign(signer.value or "")
            blockers.clear()
            if not consent.complete:
                with blockers:
                    c.note("blocker", "Cannot start: " + "; ".join(consent.missing) + ".")
                return
            dialog.close()
            on_confirm(consent)

        with ui.row().classes("justify-end w-full gap-2 mt-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
            ui.button("Start recording with names", icon="fiber_manual_record",
                      on_click=confirm).props("unelevated no-caps")
    return dialog
