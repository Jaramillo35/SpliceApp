"""Shared shell and components — every page is built from these.

The interaction canon (docs/NICEGUI_DESIGN.md): inputs card -> primary action
-> results; refreshable sections instead of page rebuilds; dialogs for
judgment calls; one download convention; empty states that teach.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from nicegui import run, ui

from nicegui_app import theme

ASSETS = Path(__file__).resolve().parents[1] / "assets"

NAV = [
    ("Workflows", [
        ("Splice Generation", "cable", "/splice-generation"),
        ("DTx Compare", "difference", "/dtx-compare"),
        ("Harness Complexity", "table_view", "/harness-complexity"),
        ("HRN Chart Builder", "stacked_bar_chart", "/hrn-chart"),
        ("VBOM Risk Matrix", "grid_on", "/vbom"),
        ("Circuit Health", "monitor_heart", "/circuit-health"),
    ]),
    ("Data", [
        ("SECR Database", "storage", "/secr"),
        ("Ask the Database", "forum", "/ask"),
    ]),
    ("Tools", [
        ("Meeting Transcripts", "graphic_eq", "/transcripts"),
        ("Downloads", "download", "/downloads"),
    ]),
]


def _feedback_dialog() -> ui.dialog:
    with ui.dialog() as dialog, ui.card().classes("w-[28rem] sx-card"):
        ui.label("Report a problem or idea").classes("text-base font-bold")
        area = ui.select(
            ["General", "Splice Generation", "DTx Compare", "Harness Complexity",
             "HRN Chart Builder", "VBOM Risk Matrix", "Circuit Health",
             "SECR Database", "Transcripts"],
            value="General", label="Area").classes("w-full")
        text = ui.textarea("What happened, or what would help?").classes("w-full")
        name = ui.input("Your name (optional)").classes("w-full")

        def submit() -> None:
            body = (text.value or "").strip()
            if not body:
                ui.notify("Describe the problem first", type="warning")
                return
            from feedback_system import FeedbackStore
            ticket_id = FeedbackStore().submit_ticket(
                reported_by=name.value or "Anonymous", workflow=area.value,
                area=area.value, description=body, category="feedback")
            dialog.close()
            text.value = ""
            ui.notify(f"Ticket {ticket_id} filed — thank you", type="positive")

        with ui.row().classes("justify-end w-full gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
            ui.button("Send", on_click=submit).props("unelevated")
    return dialog


@contextmanager
def frame(title: str, caption: str = ""):
    """App shell: left rail + header + content column. Yields the content."""
    theme.apply()
    dialog = _feedback_dialog()

    with ui.left_drawer(value=True, fixed=True).props("width=230 breakpoint=800") \
            .classes("p-3").style(f"background:{theme.SURFACE_2};border-right:1px solid {theme.LINE}"):
        # Brand block drawn in UI tokens (the JPG logo carries a white box
        # that fights the dark drawer — field report, 2026-08-24).
        with ui.row().classes("items-center gap-2 px-2 pt-1 pb-3"):
            with ui.element("div").classes(
                    "w-8 h-8 rounded-lg flex items-center justify-center") \
                    .style(f"background:{theme.BRAND}"):
                ui.icon("electrical_services").classes("text-xl text-white")
            with ui.column().classes("gap-0"):
                ui.label("Versigent").classes(
                    "text-base font-bold leading-none tracking-tight")
                ui.label("System Engineer Toolkit").classes(
                    "text-[10px] sx-muted leading-none")
        with ui.link(target="/").classes("no-underline"):
            _nav_row("Home", "home", title == "Home")
        for section, items in NAV:
            ui.label(section.upper()).classes(
                "text-[10px] font-bold tracking-widest sx-muted px-2 mt-3 mb-1")
            for label, icon, route in items:
                with ui.link(target=route).classes("no-underline"):
                    _nav_row(label, icon, label == title)

    with ui.header().classes("items-center justify-between px-5 py-2") \
            .style(f"background:{theme.SURFACE_2};border-bottom:1px solid {theme.LINE}"):
        with ui.column().classes("gap-0"):
            ui.label(title).classes("text-lg font-bold tracking-tight")
            if caption:
                ui.label(caption).classes("text-xs sx-muted")
        ui.button("Feedback", icon="rate_review", on_click=dialog.open) \
            .props("outline dense")

    with ui.column().classes("w-full max-w-6xl mx-auto p-5 gap-4") as content:
        yield content


def _nav_row(label: str, icon: str, active: bool) -> None:
    base = "items-center gap-2 px-2 py-1.5 rounded-lg w-full cursor-pointer"
    with ui.row().classes(base).style(
            f"background:{theme.BRAND}26;color:{theme.BRAND}" if active
            else f"color:{theme.TEXT}"):
        ui.icon(icon).classes("text-base")
        ui.label(label).classes("text-sm")


@contextmanager
def card(title: str = "", caption: str = ""):
    with ui.card().classes("w-full sx-card sx-reveal") as c:
        if title:
            ui.label(title).classes("text-base font-bold")
        if caption:
            ui.label(caption).classes("text-sm sx-muted -mt-1")
        yield c


def chip(kind: str, label: str) -> None:
    color = theme.STATUS.get(kind, theme.STATUS["info"])
    icon = {"blocker": "report", "high": "warning", "review": "help_outline",
            "ok": "check_circle", "info": "info"}.get(kind, "info")
    with ui.row().classes("items-center gap-1 px-2 py-0.5 rounded-full border inline-flex") \
            .style(f"border-color:{color}55;background:{color}22;color:{color}"):
        ui.icon(icon).classes("text-sm")
        ui.label(label).classes("text-xs font-semibold")


def upload_zone(label: str, on_file: Callable[[str, bytes], None],
                accept: str = "", multiple: bool = False) -> None:
    """Upload that reads bytes immediately and confirms with a chip row."""
    with ui.column().classes("flex-1 gap-1 min-w-[16rem]"):
        received: list[str] = []

        async def handle(e) -> None:
            # NiceGUI 3.x: the event carries a FileUpload at e.file
            # (e.content/e.name was the pre-3.0 API and fails silently here).
            data = await e.file.read()
            on_file(e.file.name, data)
            received.append(e.file.name)
            # one summary chip, not one per file — 17 complexity files must
            # not become a page of chips (field report, 2026-08-24)
            text = received[0] if len(received) == 1 \
                else f"{len(received)} files received"
            confirm.set_text(f"✓ {text}")
            confirm.set_visibility(True)

        ui.upload(label=label, on_upload=handle, multiple=multiple, auto_upload=True) \
            .props(f'accept="{accept}" color=primary flat bordered') \
            .classes("w-full").style("max-height: 14rem")
        confirm = ui.label("").classes("text-xs px-2 py-0.5 rounded-full w-fit") \
            .style(f"background:{theme.STATUS['ok']}22;color:{theme.STATUS['ok']}")
        confirm.set_visibility(False)


async def run_engine(fn: Callable, *args, running: str, done: str = "Done"):
    """Run an engine call off the UI thread with progress + completion toasts.

    Returns the result, or None after notifying the error.
    """
    note = ui.notification(running, spinner=True, timeout=None)
    try:
        result = await run.io_bound(fn, *args)
        ui.notify(done, type="positive")
        return result
    except Exception as exc:  # noqa: BLE001 - engine errors surface to the user
        ui.notify(f"{exc}", type="negative", multi_line=True, close_button=True)
        return None
    finally:
        note.dismiss()


def download_button(filename: str, data_getter: Callable[[], bytes]):
    return ui.button(filename, icon="download",
                     on_click=lambda: ui.download(data_getter(), filename)) \
        .props("outline dense no-caps")


def empty(message: str, icon: str = "upload_file") -> None:
    with ui.column().classes("items-center w-full py-8 gap-1 sx-muted"):
        ui.icon(icon).classes("text-4xl opacity-40")
        ui.label(message).classes("text-sm text-center")
