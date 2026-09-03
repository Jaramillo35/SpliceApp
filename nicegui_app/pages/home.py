"""Overview — a dashboard, not a brochure.

Continue where you left off (the activity feed the engine runners write),
what needs attention (read from the workbench stores), and the tools,
grouped the way the rail groups them. All three come from data the rest of
the app already keeps; nothing here is maintained by hand.
"""

from __future__ import annotations

import logging

from nicegui import ui

from nicegui_app import components as c
from nicegui_app import theme

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- readers
def _continue() -> list[dict]:
    from splice.common import activity
    by_route = activity.latest_by_tool()
    labels = {p.route: p for p in c.PAGES}
    rows = [dict(entry, page=labels[route])
            for route, entry in by_route.items() if route in labels]
    return sorted(rows, key=lambda r: r.get("at", ""), reverse=True)[:6]


def _attention() -> list[tuple[str, str, str, str]]:
    """(kind, text, route, envelope) — each line is one thing to do."""
    items: list[tuple[str, str, str, str]] = []
    try:
        from splice.dtxcircuits import store as ca_store
        data = ca_store.load()
        env = ca_store.envelope(data)
        stamp = f"saved by {env['by'] or 'unknown'} · {env['at'][:16]}" if env["at"] else ""
        n = len(data.get("cleanup", {}))
        if n:
            items.append(("info", f"{n} row(s) selected for Complexity Cleanup Notes, "
                                  "not yet exported", "/circuit-applicability", stamp))
    except Exception as exc:  # noqa: BLE001 — a missing store is not a finding
        logger.debug("applicability store: %s", exc)
    try:
        from nicegui_app.pages import circuit_health
        from splice.inline import health
        baseline = health.load_baseline(circuit_health.BASELINE_PATH)
        n = len(baseline.get("dispositions", {}))
        signoffs = baseline.get("signoffs", [])
        last = signoffs[-1] if signoffs else {}
        stamp = (f"last sign-off by {last.get('by', '?')} · {str(last.get('at', ''))[:16]}"
                 if last else "no sign-off yet")
        if n:
            items.append(("ok", f"{n} finding(s) dispositioned in Circuit Health",
                          "/circuit-health", stamp))
    except Exception as exc:  # noqa: BLE001
        logger.debug("health baseline: %s", exc)
    try:
        from splice.vbom import review_store
        data = review_store.load()
        n = len(data.get("resolutions", {}))
        if n:
            env = review_store.envelope(data)
            items.append(("ok", f"{n} VBOM review case(s) resolved", "/vbom",
                          f"saved by {env['by'] or 'unknown'} · {env['at'][:16]}"))
    except Exception as exc:  # noqa: BLE001 — the store arrives with the VBOM workbench
        logger.debug("vbom review store: %s", exc)
    try:
        from feedback_system import FeedbackStore
        tickets = FeedbackStore().load_tickets()
        open_ = [t for t in tickets if str(t.get("status", "open")).lower()
                 not in {"closed", "done", "applied", "resolved"}]
        if open_:
            items.append(("review", f"{len(open_)} open feedback ticket(s)",
                          "/admin", ""))
    except Exception as exc:  # noqa: BLE001
        logger.debug("tickets: %s", exc)
    return items


# ------------------------------------------------------------------ page
@ui.page("/")
def page() -> None:
    with c.frame("Overview", "Continue where you left off; what needs attention."):
        with ui.element("div").classes("w-full grid gap-6 grid-cols-1 lg:grid-cols-2 items-start"):
            with c.card("Continue", "The last run of each tool, newest first. "
                                    "Uploaded files are never kept — load the same "
                                    "ones again and each workbench applies the "
                                    "mapping and decisions it saved."):
                rows = _continue()
                if not rows:
                    c.empty("Run any tool and it appears here, with the programme "
                            "it ran on and who ran it.", icon="history")
                for r in rows:
                    page_ = r["page"]
                    with ui.link(target=page_.route).classes("no-underline w-full"):
                        with ui.row().classes("items-center gap-3 no-wrap w-full rounded px-2 py-1.5 sx-hover"):
                            ui.icon(page_.icon).classes("text-lg").style(f"color:{theme.BRAND}")
                            with ui.column().classes("gap-0 min-w-0 grow"):
                                ui.label(page_.label).classes("text-sm font-semibold") \
                                    .style(f"color:{theme.TEXT}")
                                ui.label(r.get("summary", "")).classes("sx-caption truncate")
                            with ui.column().classes("gap-0 items-end shrink-0"):
                                if r.get("context"):
                                    c.chip("info", r["context"])
                                ui.label(f"{r.get('by') or '—'} · {r.get('at', '')[:16]}") \
                                    .classes("sx-caption sx-mono")

            with c.card("Needs attention", "Open work in the workbenches, read from what they saved."):
                items = _attention()
                if not items:
                    c.empty("Nothing waiting. Dispositions, cleanup selections and "
                            "review cases show up here once a workbench saves them.",
                            icon="task_alt")
                for kind, text, route, stamp in items:
                    with ui.link(target=route).classes("no-underline w-full"):
                        # a sentence is a note, not a chip: a chip is a word,
                        # and a pill wrapping to four lines becomes a blob
                        with ui.column().classes("gap-0 w-full rounded px-2 py-1.5 sx-hover"):
                            c.note(kind, text)
                            if stamp:
                                ui.label(stamp).classes("sx-caption sx-mono pl-5")

        for family in c.FAMILIES:
            pages = c.pages_in(family)
            with ui.row().classes("items-baseline gap-2 w-full -mb-3"):
                ui.label(family).classes("sx-eyebrow")
                if c.FAMILY_HINT.get(family):
                    ui.label(c.FAMILY_HINT[family]).classes("sx-caption")
            with ui.element("div").classes(
                    "w-full grid gap-3 grid-cols-1 md:grid-cols-2 xl:grid-cols-3"):
                for page_ in pages:
                    with ui.link(target=page_.route).classes("no-underline"):
                        with ui.card().classes("sx-card sx-reveal w-full h-full gap-1 sx-hover transition-colors"):
                            with ui.row().classes("items-center gap-2 no-wrap"):
                                ui.icon(page_.icon).classes("text-xl").style(f"color:{theme.BRAND}")
                                ui.label(page_.label).classes("text-base font-semibold") \
                                    .style(f"color:{theme.TEXT}")
                            ui.label(page_.purpose).classes("sx-caption")
