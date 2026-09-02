"""Admin — what is running, what changed, and the state of the data.

Every number on this page existed before it did; the system had all of it
and threw it away. The version was stamped nowhere, engine logs had no
handler, backups did not exist, and the feedback tickets had no reader. This
page is one surface for those, so "it broke" can come with a version and a
log excerpt, and "do I have the latest?" has an answer.

Restore is the only destructive action here and is gated by a dialog that
names the archive. It keeps the data it replaces, so it is itself undoable.
"""

from __future__ import annotations

import os
import time
import urllib.request
from pathlib import Path

from nicegui import run, ui

from nicegui_app import components as c
from nicegui_app import theme
from splice import version
from splice.common import backup
from splice.common.logging import tail
from splice.config import DATA_DIR

STARTED = time.time()
LOG_DIR = DATA_DIR / "logs"
CHANGELOG = Path(__file__).resolve().parents[2] / "CHANGELOG.md"

#: what the toolkit is made of, and where each part answers. The interface
#: probes itself on whatever port it was actually started on.
SERVICES = [
    ("This interface",
     f"http://127.0.0.1:{os.getenv('SPLICE_NICEGUI_PORT', '8504')}/", "NiceGUI"),
    ("Previous interface", "http://splice-ui:8501/_stcore/health", "Streamlit"),
    ("Engine API", "http://splice-api:8000/health", "FastAPI"),
]


def probe(url: str, timeout: float = 1.5) -> tuple[bool, str]:
    """Is something answering at ``url``? Never raises."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status < 400, f"HTTP {response.status}"
    except Exception as exc:  # noqa: BLE001 — every failure is just "not answering"
        reason = getattr(exc, "reason", None) or exc
        return False, str(reason).split(":")[0][:40]


def uptime_text(seconds: float) -> str:
    seconds = int(seconds)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def changelog_sections(limit: int = 3) -> list[tuple[str, str]]:
    """The newest ``limit`` release headings and their bodies."""
    if not CHANGELOG.exists():
        return []
    sections: list[tuple[str, list[str]]] = []
    for line in CHANGELOG.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            sections.append((line[3:].strip(), []))
        elif sections:
            sections[-1][1].append(line)
    return [(title, "\n".join(body).strip()) for title, body in sections[:limit]]


@ui.page("/admin")
async def page() -> None:
    info = version.current()

    with c.frame("Admin", "What is running, what changed, and the state of the data"):

        # ------------------------------------------------------------ version
        with c.card("Version"):
            with ui.row().classes("gap-2 flex-wrap items-center"):
                ui.label(info.label).classes("text-2xl font-bold sx-mono")
                c.chip("info" if info.source == version.FROM_BUILD else "review",
                       info.source)
                if info.dirty:
                    c.chip("review", "uncommitted changes in the working tree")
            with ui.element("div").classes("grid grid-cols-2 md:grid-cols-4 gap-3 mt-2"):
                _fact("Commit", info.sha or "—", mono=True)
                _fact("Branch", info.branch or "—", mono=True)
                _fact("Built", info.built or "—", mono=True)
                _fact("Up for", uptime_text(time.time() - STARTED))
            if info.source == version.FROM_PACKAGE:
                ui.label("No build stamp and no git checkout: this copy cannot say "
                         "which commit it is. Rebuild with the Start or Update "
                         "script, which records it.").classes("text-xs sx-muted mt-2")

        # ---------------------------------------------------------- changelog
        sections = changelog_sections()
        with c.card("What changed", "From CHANGELOG.md — the newest entries."):
            if not sections:
                c.empty("No changelog shipped with this build.", icon="history")
            for title, body in sections:
                with ui.expansion(title, value=title.startswith("Unreleased")) \
                        .classes("w-full").props("dense"):
                    ui.markdown(body).classes("text-sm")

        # ----------------------------------------------------------- services
        @ui.refreshable
        async def services_view() -> None:
            # Off the event loop, and not only for politeness: the first probe
            # is of this very server. A synchronous request from inside its
            # own loop can never be answered, so it timed out every time and
            # reported the page you were looking at as down.
            results = [(name, kind, await run.io_bound(probe, url))
                       for name, url, kind in SERVICES]
            with ui.element("div").classes("grid grid-cols-1 md:grid-cols-3 gap-3"):
                for name, kind, (ok, detail) in results:
                    with ui.element("div").classes("rounded px-3 py-2") \
                            .style(f"background:{theme.SURFACE_2};border:1px solid "
                                   f"{theme.STATUS['ok' if ok else 'blocker']}55"):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("check_circle" if ok else "error").style(
                                f"color:{theme.STATUS['ok' if ok else 'blocker']}")
                            ui.label(name).classes("font-semibold text-sm")
                        ui.label(f"{kind} · {'answering' if ok else 'not answering'}"
                                 f" · {detail}").classes("text-[10px] sx-muted sx-mono")

        with c.card("Services", "Whether each part of the toolkit answers right now."):
            await services_view()
            ui.button("Check again", icon="refresh",
                      on_click=services_view.refresh).props("outline dense")

        # --------------------------------------------------------------- data
        @ui.refreshable
        def data_view() -> None:
            backups = backup.list_backups()
            with ui.element("div").classes("grid grid-cols-2 md:grid-cols-4 gap-3"):
                _fact("Data directory", str(DATA_DIR), mono=True)
                _fact("Live data", backup.human_size(backup.data_size()))
                _fact("Backups kept", str(len(backups)))
                _fact("Last backup",
                      backups[0].created.strftime("%Y-%m-%d %H:%M") if backups else "never",
                      warn=not backups)

            if backups:
                ui.label("BACKUPS").classes("text-[10px] font-bold tracking-widest sx-muted mt-3")
                for item in backups:
                    with ui.row().classes("items-center gap-3 w-full py-1") \
                            .style(f"border-bottom:1px solid {theme.LINE}"):
                        ui.label(item.created.strftime("%Y-%m-%d %H:%M:%S")) \
                            .classes("sx-mono text-sm")
                        ui.label(item.size_text).classes("text-xs sx-muted")
                        ui.space()
                        ui.button("Download", icon="download",
                                  on_click=lambda i=item: ui.download(i.path)) \
                            .props("flat dense no-caps")
                        ui.button("Restore", icon="settings_backup_restore",
                                  on_click=lambda i=item: _confirm_restore(i)) \
                            .props("flat dense no-caps color=negative")

        async def _make_backup() -> None:
            made = await c.run_engine(backup.create, running="Backing up…",
                                      done="Backup written")
            if made:
                data_view.refresh()

        def _confirm_restore(item: backup.Backup) -> None:
            with ui.dialog() as dialog, ui.card().classes("w-[30rem] sx-card"):
                ui.label("Restore this backup?").classes("text-base font-bold")
                ui.label(f"{item.created:%Y-%m-%d %H:%M:%S} · {item.size_text}") \
                    .classes("sx-mono text-sm")
                ui.label("The current data is replaced by the archive. What is "
                         "replaced is kept in the backups folder, so this can be "
                         "undone — but anything entered since that backup will "
                         "not be visible until it is.").classes("text-sm sx-muted")
                with ui.row().classes("justify-end w-full gap-2"):
                    ui.button("Cancel", on_click=dialog.close).props("flat")

                    async def go() -> None:
                        dialog.close()
                        kept = await c.run_engine(
                            backup.restore, item.path,
                            running="Restoring…", done="Restored — reload the page")
                        if kept:
                            ui.notify(f"Previous data kept at {kept.name}",
                                      type="info", multi_line=True)
                            data_view.refresh()

                    ui.button("Restore", on_click=go).props("unelevated color=negative")
            dialog.open()

        with c.card("Data", "Everything the toolkit cannot rebuild lives here."):
            data_view()
            with ui.row().classes("gap-2 mt-2"):
                ui.button("Back up now", icon="save",
                          on_click=_make_backup).props("unelevated dense")
                ui.label(f"The newest {backup.KEEP} are kept. Backups live inside "
                         "the data directory, so they survive a rebuild — but not "
                         "a deleted volume. Download one somewhere else too.") \
                    .classes("text-[10px] sx-muted self-center")

        # --------------------------------------------------------------- logs
        @ui.refreshable
        def log_view() -> None:
            text = tail(LOG_DIR)
            ui.code(text or "(empty)", language=None) \
                .classes("w-full text-[11px]").style("max-height:24rem;overflow:auto")
            with ui.row().classes("gap-2"):
                ui.button("Refresh", icon="refresh", on_click=log_view.refresh) \
                    .props("outline dense")
                ui.button("Copy for a bug report", icon="content_copy",
                          on_click=lambda: (
                              ui.run_javascript(
                                  f"navigator.clipboard.writeText({text!r})"),
                              ui.notify("Copied", type="positive"))) \
                    .props("outline dense no-caps")

        with c.card("Logs", "The last few hundred lines. Copy them into a bug report "
                            "together with the version above."):
            log_view()

        # ----------------------------------------------------------- feedback
        with c.card("Feedback inbox", "Tickets filed from the Feedback button."):
            _feedback_table()


def _fact(label: str, value: str, mono: bool = False, warn: bool = False) -> None:
    with ui.element("div").classes("rounded px-3 py-2") \
            .style(f"background:{theme.SURFACE_2};border:1px solid "
                   f"{theme.STATUS['review'] if warn else theme.LINE}"):
        ui.label(value).classes("text-sm font-semibold break-all"
                                + (" sx-mono" if mono else ""))
        ui.label(label).classes("text-[10px] sx-muted")


def _feedback_table() -> None:
    try:
        from feedback_system import FeedbackStore
        tickets = FeedbackStore().load_tickets()
    except Exception as exc:  # noqa: BLE001 — the inbox must not break the page
        c.empty(f"Could not read tickets: {exc}", icon="inbox")
        return
    if not tickets:
        c.empty("No tickets yet.", icon="inbox")
        return
    rows = []
    for t in sorted(tickets, key=lambda t: str(t.get("created_at", "")), reverse=True)[:50]:
        rows.append({
            "when": str(t.get("created_at", ""))[:16],
            "area": t.get("area") or t.get("workflow") or "",
            "who": t.get("reported_by", ""),
            "status": t.get("status", ""),
            "text": (t.get("description") or "")[:140],
        })
    ui.table(rows=rows, columns=[
        {"name": "when", "label": "When", "field": "when", "align": "left", "sortable": True},
        {"name": "area", "label": "Area", "field": "area", "align": "left", "sortable": True},
        {"name": "who", "label": "From", "field": "who", "align": "left"},
        {"name": "status", "label": "Status", "field": "status", "align": "left"},
        {"name": "text", "label": "Description", "field": "text", "align": "left"},
    ], pagination=10).classes("w-full").props("dense flat")
    ui.label(f"{len(tickets)} ticket(s) in total").classes("text-[10px] sx-muted")

