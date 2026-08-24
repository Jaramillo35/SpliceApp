"""HRN Chart Builder — NiceGUI page over splice.hrncmp.engine.

Includes the supplier-list loop: download the shipped list, upload a modified
one (used immediately for this session's builds) which auto-files a
deduplicated supplier-update ticket, and the admin panel over those tickets.
"""

from __future__ import annotations

import io
import json
import zipfile

from nicegui import ui

from nicegui_app import components as c
from splice.hrncmp import engine, supplier_tickets


def _norm_stem(name: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]", "", name.rsplit(".", 1)[0].lower())


@ui.page("/hrn-chart")
def page() -> None:
    files: dict[str, bytes] = {}
    results: list = []
    supplier: dict = {"map": None, "name": ""}

    with c.frame("HRN Chart Builder",
                 "HRN + Matrix CSV (+ CMP) → chart workbooks named "
                 "{Family}_{ModelYear}{Program}_Chart_{date}"):
        with c.card("Inputs", "Any mix of .hrn / .csv / .cmp — they pair by file name."):
            c.upload_zone("HRN / CSV / CMP files",
                          lambda n, b: (files.__setitem__(n, b), refresh_jobs.refresh()),
                          accept=".hrn,.csv,.cmp", multiple=True)

            @ui.refreshable
            def refresh_jobs() -> None:
                jobs = _pair(files)
                if not jobs:
                    return
                rows = [{
                    "hrn": j["hrn"],
                    "harness": engine.parse_hrn_filename(j["hrn"].rsplit(".", 1)[0]).family or "?",
                    "csv": j["csv"] or "— missing —",
                    "cmp": j["cmp"] or "—",
                    "out": f'{engine.output_basename(j["hrn"])}.xlsx',
                } for j in jobs]
                ui.table(rows=rows, columns=[
                    {"name": k, "label": lbl, "field": k, "align": "left"}
                    for k, lbl in [("hrn", "HRN file"), ("harness", "Harness"),
                                   ("csv", "Matrix CSV"), ("cmp", "CMP"),
                                   ("out", "Output")]]) \
                    .classes("w-full").props("dense flat")

            refresh_jobs()
            ui.button("Build charts", icon="play_arrow", on_click=lambda: build()) \
                .props("unelevated")

        def supplier_upload(name: str, blob: bytes) -> None:
            supplier_note.clear()
            uploaded = engine.load_supplier_map(blob)
            if not uploaded:
                with supplier_note:
                    c.chip("blocker", "Could not read a name/prefix mapping "
                                      "from that file")
                return
            supplier["map"], supplier["name"] = uploaded, name
            shipped = engine.default_supplier_map()
            try:
                ticket_id, diff, already = supplier_tickets.file_supplier_ticket(
                    name, uploaded, shipped)
            except Exception as exc:
                with supplier_note:
                    c.chip("high", f"Ticket could not be filed: {exc}")
                return
            with supplier_note:
                if ticket_id is None:
                    c.chip("info", "Matches the shipped list — no ticket needed")
                else:
                    n = (f"{len(diff['added'])} added, {len(diff['removed'])} "
                         f"removed, {len(diff['changed'])} changed")
                    c.chip("ok", f"Ticket {ticket_id} "
                                 f"{'already open' if already else 'filed'} ({n})")

        def _admin_panel() -> None:
            tickets = supplier_tickets.list_supplier_tickets()
            if not tickets:
                return
            open_n = sum(1 for t in tickets if t.get("status") != "applied")
            with ui.expansion(f"Supplier update tickets — {open_n} open "
                              f"({len(tickets)} total) · admin") \
                    .classes("w-full").props("dense"):
                ui.label("Hand a ticket's JSON to Claude ('apply supplier "
                         "ticket …') to regenerate the shipped list and mark "
                         "it applied.").classes("text-xs sx-muted")
                for t in sorted(tickets, key=lambda x: x.get("created_at", ""),
                                reverse=True):
                    with ui.row().classes("items-center gap-3 w-full"):
                        kind = "ok" if t.get("status") == "applied" else "high"
                        c.chip(kind, t.get("status", "new"))
                        ui.label(f"{t.get('ticket_id')} · "
                                 f"{t.get('created_at', '')[:16]}") \
                            .classes("text-sm sx-muted")
                        c.download_button(
                            f"{t.get('ticket_id', 'ticket')}.json",
                            lambda t=t: json.dumps(t, indent=2).encode())

        with ui.expansion("Supplier list").classes("w-full sx-card px-2") \
                .props("dense"):
            ui.label("Used to tag CNUMs with supplier prefixes (PN-111~DZ). "
                     "Missing or outdated supplier? Download, edit, and upload "
                     "— your builds use it right away, and an update ticket is "
                     "filed for the administrator automatically.") \
                .classes("text-sm sx-muted")
            with ui.row().classes("gap-3 items-start flex-wrap"):
                if engine.DEFAULT_SUPPLIER_PATH.exists():
                    c.download_button(engine.DEFAULT_SUPPLIER_PATH.name,
                                      lambda: engine.DEFAULT_SUPPLIER_PATH.read_bytes())
                c.upload_zone("Override supplier list (Excel/CSV)",
                              lambda n, b: supplier_upload(n, b),
                              accept=".xlsx,.xls,.csv")
            supplier_note = ui.column().classes("gap-1")
            _admin_panel()

        @ui.refreshable
        def render_results() -> None:
            if not results:
                return
            with c.card(f"{len(results)} workbook(s) built"):
                for res in results:
                    with ui.row().classes("items-center gap-3 w-full"):
                        c.download_button(res.filename, lambda r=res: r.workbook)
                        notes = []
                        if res.unmatched:
                            notes.append(f"{len(res.unmatched)} unmatched connector(s)")
                        if res.invalid_prefixes:
                            notes.append(f"{len(res.invalid_prefixes)} invalid prefix(es)")
                        if notes:
                            c.chip("high", ", ".join(notes))
                        else:
                            c.chip("ok", "clean")
                if len(results) > 1:
                    def zip_all() -> bytes:
                        buf = io.BytesIO()
                        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                            for res in results:
                                zf.writestr(res.filename, res.workbook)
                        return buf.getvalue()
                    c.download_button("hrn_charts.zip", zip_all)

        render_results()

        async def build() -> None:
            jobs = [j for j in _pair(files) if j["csv"]]
            if not jobs:
                ui.notify("No runnable HRN+CSV pair yet", type="warning")
                return

            def work():
                out, used = [], set()
                for j in jobs:
                    res = engine.build_chart(
                        j["hrn"], files[j["hrn"]], files[j["csv"]],
                        files[j["cmp"]] if j["cmp"] else None,
                        supplier_map=supplier["map"])
                    name, n = res.filename, 1
                    while name in used:
                        n += 1
                        name = res.filename.replace(".xlsx", f"_{n}.xlsx")
                    used.add(name)
                    res.filename = name
                    out.append(res)
                return out

            built = await c.run_engine(work, running=f"Building {len(jobs)} chart(s)…",
                                       done="Charts built")
            if built is not None:
                results.clear()
                results.extend(built)
                render_results.refresh()


def _pair(files: dict[str, bytes]) -> list[dict]:
    hrns = {n: _norm_stem(n) for n in files if n.lower().endswith(".hrn")}
    csvs = {_norm_stem(n): n for n in files if n.lower().endswith(".csv")}
    cmps = {_norm_stem(n): n for n in files if n.lower().endswith(".cmp")}
    jobs = [{"hrn": n, "csv": csvs.get(s), "cmp": cmps.get(s)}
            for n, s in sorted(hrns.items())]
    if len(csvs) == 1:
        only = next(iter(csvs.values()))
        for j in jobs:
            j["csv"] = j["csv"] or only
    if len(cmps) == 1:
        only = next(iter(cmps.values()))
        for j in jobs:
            j["cmp"] = j["cmp"] or only
    return jobs
