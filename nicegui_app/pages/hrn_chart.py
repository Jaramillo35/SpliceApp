"""HRN Chart Builder — NiceGUI page over splice.hrncmp.engine."""

from __future__ import annotations

import io
import zipfile

from nicegui import ui

from nicegui_app import components as c
from splice.hrncmp import engine


def _norm_stem(name: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]", "", name.rsplit(".", 1)[0].lower())


@ui.page("/hrn-chart")
def page() -> None:
    files: dict[str, bytes] = {}
    results: list = []

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
                        files[j["cmp"]] if j["cmp"] else None)
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
