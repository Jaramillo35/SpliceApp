"""Card 6 — the circuit chart: which part number carries which wire."""

from __future__ import annotations

from nicegui import ui

from nicegui_app import components as c
from nicegui_app import theme
from nicegui_app.pages.circuit_applicability.workbench import Workbench
from splice.dtxcircuits import chart as chart_mod


def build(wb: Workbench) -> None:
    state = wb.state

    @ui.refreshable
    def chart_view() -> None:
        charts = state["charts"]
        if not charts:
            return
        with c.section("6 · Circuit chart",
                    "Which part number carries which wire, per harness "
                    "family. The DTx condition flows through the whole "
                    "circuit and is restated in each harness's own codes; "
                    "a circuit reaching three or more cavities gets a "
                    "splice. Same layout as the Circuit Summary that "
                    "Circuit Health reads, so this feeds straight back.",
                 step="Chart"):
            with ui.row().classes("gap-2 flex-wrap items-center"):
                c.chip("info", f"{len(charts)} chart(s) · "
                               f"{sum(len(x.rows) for x in charts)} circuit end(s)")
                spliced = sum(len(x.splices) for x in charts)
                if spliced:
                    c.chip("review", f"{spliced} circuit(s) need a splice")
                findings = sum(x.findings for x in charts)
                c.chip("blocker" if findings else "ok",
                       f"{findings} row(s) no build carries"
                       if findings else "Every row is carried by a build")
                ui.button("Circuit_Chart.xlsx", icon="download",
                          on_click=lambda: _download_chart()) \
                    .props("outline dense no-caps")

            for chart in charts:
                with ui.expansion(
                        f"{chart.family} → {chart.harness}"
                        f"   ·  {chart.circuits} circuit(s)"
                        f"  ·  {len(chart.part_numbers)} part number(s)"
                        + (f"  ·  {len(chart.splices)} splice(s)"
                           if chart.splices else "")
                        + (f"  ·  {chart.findings} never built"
                           if chart.findings else ""),
                        value=state["chart_open"] == chart.block_title) \
                        .classes("w-full").props("dense") \
                        .on_value_change(
                            lambda e, t=chart.block_title:
                                state.update(chart_open=t if e.value else None)):
                    _chart_table(chart)

    def _chart_table(chart) -> None:
        if not chart.rows:
            c.empty("No circuit ends for this family.", icon="table_rows")
            return
        columns = [
            {"name": "circuit", "label": "Circuit", "field": "circuit",
             "align": "left", "sortable": True},
            {"name": "cnum", "label": "CNUM", "field": "cnum",
             "align": "left", "sortable": True},
            {"name": "cavity", "label": "Cav", "field": "cavity",
             "align": "center"},
            {"name": "expression", "label": "Sales code (DTx)",
             "field": "expression", "align": "left"},
            {"name": "harness_expression", "label": "…in this harness",
             "field": "harness_expression", "align": "left"},
            {"name": "other", "label": "Other end", "field": "other",
             "align": "left"},
        ] + [
            # the part number's tail is what an SE reads; the full number
            # stays in the tooltip and in the workbook
            {"name": pn, "label": pn[-6:], "field": pn, "align": "center",
             "headerStyle": f"writing-mode:vertical-rl;color:{theme.BRAND}"}
            for pn in chart.part_numbers
        ]
        rows = []
        for row in chart.rows:
            record = {"circuit": row.circuit,
                      "cnum": ("⚡ " if row.is_splice else "") + row.cnum,
                      "cavity": row.cavity,
                      "expression": row.expression or "—",
                      "harness_expression": (
                          row.harness_expression
                          or ("—" if row.expression else "")),
                      "other": _other_end(chart, row),
                      "_never": row.is_finding}
            record.update(dict(zip(chart.part_numbers,
                                   row.marks(chart.part_numbers))))
            rows.append(record)
        table = ui.table(rows=rows, columns=columns, pagination=25) \
            .classes("w-full").props("dense flat")
        # an empty row is the finding, so it must not read as an empty row
        table.add_slot("body", r"""
            <q-tr :props="props" :class="props.row._never ? 'sx-never' : ''">
              <q-td v-for="col in props.cols" :key="col.name" :props="props">
                {{ col.value }}
              </q-td>
            </q-tr>
        """)
        ui.label(f"Coverage: " + "  ".join(
            f"{pn[-6:]} {chart.coverage(pn)}/{len(chart.rows)}"
            for pn in chart.part_numbers)).classes("sx-caption sx-mono")

    def _other_end(chart, row) -> str:
        """Where the wire goes, named only as far as it needs to be."""
        if not row.other_cnum:
            return "—"
        where = f"{row.other_cnum}/{row.other_cavity or '?'}"
        # the family is worth saying only when the wire leaves this one
        return where if row.other_family == chart.family \
            else f"{where} · {row.other_family}"

    async def _download_chart() -> None:
        meta = state["dtx_meta"]
        data = await c.run_engine(
            chart_mod.build_chart_workbook, list(state["charts"]),
            meta.program if meta else "", meta.phase if meta else "",
            running="Building the circuit chart…", done="Chart ready")
        if data is not None:
            c.deliver(data, "Circuit_Chart.xlsx")

    wb.views["chart"] = chart_view
    chart_view()
