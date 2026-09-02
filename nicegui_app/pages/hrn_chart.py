"""HRN Chart Builder — NiceGUI page over splice.hrncmp.engine.

Archetype A (converter): inputs panel with the pairing preview and one gated
primary, result panel that exists before the run. Below the grid sits the
supplier-list loop: download the shipped list, upload a modified one (used
immediately for this session's builds) which auto-files a deduplicated
supplier-update ticket, and the admin panel over those tickets.
"""

from __future__ import annotations

import io
import json
import zipfile

from nicegui import ui

from nicegui_app import components as c
from splice.hrncmp import engine, supplier_tickets

PAIR_LABELS = {"hrn": "HRN file", "harness": "Harness", "csv": "Matrix CSV",
               "cmp": "CMP", "out": "Output"}


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
        inputs, result = c.converter(
            "Drop any mix of .hrn, .csv and .cmp files. They pair by file "
            "name; every HRN with a Matrix CSV becomes one chart workbook, "
            "its CNUMs tagged with supplier prefixes from the supplier list.",
            inputs_caption="Any mix of .hrn / .csv / .cmp — they pair by file name.")

        def runnable() -> list[dict]:
            return [j for j in _pair(files) if j["csv"]]

        with inputs:
            c.upload_row("HRN / CSV / CMP files",
                         lambda n, b: (files.__setitem__(n, b), refresh_jobs.refresh()),
                         accept=".hrn,.csv,.cmp", multiple=True)

            @ui.refreshable
            def refresh_jobs() -> None:
                jobs = _pair(files)
                if not jobs:
                    c.empty("Drop files to see how they pair.", icon="join_inner")
                    return
                rows = [{
                    "hrn": j["hrn"],
                    "harness": engine.parse_hrn_filename(j["hrn"].rsplit(".", 1)[0]).family or "?",
                    "csv": j["csv"] or "— missing —",
                    "cmp": j["cmp"] or "—",
                    "out": f'{engine.output_basename(j["hrn"])}.xlsx',
                } for j in jobs]
                c.frame_table(rows, labels=PAIR_LABELS, mono=("hrn", "csv", "cmp", "out"))

            refresh_jobs()
            c.action("Build charts", lambda: build(),
                     needs=lambda: [] if runnable() else ["an HRN + Matrix CSV pair"])

        def show_results() -> None:
            def zip_all() -> bytes:
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                    for res in results:
                        zf.writestr(res.filename, res.workbook)
                return buf.getvalue()

            with result.show():
                for res in results:
                    with ui.row().classes("items-center gap-3 w-full"):
                        c.download(res.filename, lambda r=res: r.workbook)
                        notes = []
                        if res.unmatched:
                            notes.append(f"{len(res.unmatched)} unmatched connector(s)")
                        if res.invalid_prefixes:
                            notes.append(f"{len(res.invalid_prefixes)} invalid prefix(es)")
                        if notes:
                            c.chip("high", ", ".join(notes))
                        else:
                            c.chip("ok", "clean")
            with result.actions:
                if len(results) > 1:
                    c.downloads([(r.filename, lambda r=r: r.workbook) for r in results]
                                + [("hrn_charts.zip", zip_all)],
                                label=f"{len(results)} workbooks")
                else:
                    c.download(results[0].filename, lambda: results[0].workbook)

        async def build() -> None:
            jobs = runnable()

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
            if built:
                results.clear()
                results.extend(built)
                show_results()

        # ------------------------------------------------------ supplier list
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
            except Exception as exc:  # noqa: BLE001 - a failed ticket must not block the build
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
                         "it applied.").classes("sx-caption")
                for t in sorted(tickets, key=lambda x: x.get("created_at", ""),
                                reverse=True):
                    with ui.row().classes("items-center gap-3 w-full"):
                        kind = "ok" if t.get("status") == "applied" else "high"
                        c.chip(kind, t.get("status", "new"))
                        ui.label(f"{t.get('ticket_id')} · "
                                 f"{t.get('created_at', '')[:16]}") \
                            .classes("sx-caption sx-mono")
                        c.download(f"{t.get('ticket_id', 'ticket')}.json",
                                   lambda t=t: json.dumps(t, indent=2).encode())

        with c.card("Supplier list",
                    "Used to tag CNUMs with supplier prefixes (PN-111~DZ)."):
            ui.label("Missing or outdated supplier? Download, edit, and upload "
                     "— your builds use it right away, and an update ticket is "
                     "filed for the administrator automatically.") \
                .classes("sx-caption")
            with ui.row().classes("gap-3 items-start flex-wrap w-full"):
                if engine.DEFAULT_SUPPLIER_PATH.exists():
                    c.download(engine.DEFAULT_SUPPLIER_PATH.name,
                               lambda: engine.DEFAULT_SUPPLIER_PATH.read_bytes())
                c.upload_row("Override supplier list (Excel/CSV)",
                             lambda n, b: supplier_upload(n, b),
                             accept=".xlsx,.xls,.csv")
            supplier_note = ui.column().classes("gap-1")
            _admin_panel()


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
