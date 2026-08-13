"""Enhanced DTx Compare workbook — the WEAVE essence in one native-Excel file.

Builds on the V1 change comparison but produces a richer, self-updating workbook:

  * **Dashboard** — a DTCR-coverage panel and an Implementation-Progress panel (donut +
    by-family bars) in the WEAVE style, driven by native ``COUNTIFS`` so they recompute
    live as the SE fills in the Status column. A harness-family dropdown refilters the
    overall-progress donut.
  * **All Changes** — a ``Status`` column (before ``DTCR#``) with a dropdown and conditional
    formatting (Done → green, In Progress → amber, X → red).
  * **DTCR Matching**, **Yellow Connectors** (invalid connector PNs), and **PreOrder List**
    sheets — the DTCR/connector deliverables alongside the change detail.

No macros: charts reference formula cells and conditional formatting reacts to the Status
column, so everything updates in a plain ``.xlsx`` with no "enable content" prompt.

A DTCR report is **required** — the coverage panel and DTCR annotation depend on it.
"""

from __future__ import annotations

from io import BytesIO

import pandas as pd

from splice.common.text import normalize_value
from splice.dtx_compare.engine import (
    _annotate_results_with_dtcr,
    _build_dtcr_lookup_by_cnum,
    _read_dtx_report_rows,
    build_all_changes_df,
    build_family_summary_df,
    build_output_filename,
    compare_reports,
    generate_dtcr_matching_report,
    generate_preorder_generation_workbook,
    load_dtx_report,
    write_table,
)

# WEAVE implementation-status palette (X = "Needs Review").
_IMPL_STATUSES = ("Done", "In Progress", "X")
_IMPL_ROW_FILL = {"Done": "#D6EBD6", "In Progress": "#FCE4C6", "X": "#F6CCCC"}
_IMPL_CHART_COLOR = {"Done": "#2E7D32", "In Progress": "#E8833A", "X": "#C00000", "Not started": "#9DA7B3"}
_ALL_FAMILIES = "(All families)"
_INVALID_MARK = "invalid"          # the DTX 'Invalid_Contact_Connector_Enginner' placeholder


class DTCRRequiredError(ValueError):
    """Raised when a compare is requested without the (now required) DTCR report."""


# --------------------------------------------------------------------------- data
def build_yellow_connectors_df(new_rows: pd.DataFrame) -> pd.DataFrame:
    """Connectors the NEW DTx labels with an Invalid Connector PN — one row per CNUM."""
    cols = ["CNUM", "Connector PN", "Device Name", "Harness Family"]
    if new_rows is None or "Connector PN" not in new_rows.columns:
        return pd.DataFrame(columns=cols)
    mask = new_rows["Connector PN"].astype(str).str.contains(_INVALID_MARK, case=False, na=False)
    seen: dict[str, dict] = {}
    for _, r in new_rows[mask].iterrows():
        cnum = normalize_value(r.get("CNUM"))
        if cnum and cnum not in seen:
            seen[cnum] = {c: normalize_value(r.get(c)) for c in cols}
    return pd.DataFrame(sorted(seen.values(), key=lambda d: (d["Harness Family"], d["CNUM"])), columns=cols)


def generate_enhanced_dtx_report(
    old_file_bytes: bytes,
    new_file_bytes: bytes,
    old_file_name: str,
    new_file_name: str,
    dtcr_df: pd.DataFrame | None,
) -> dict[str, object]:
    """Return {'output_excel_bytes', 'output_file_name', ...}. DTCR report is required."""
    if dtcr_df is None or (isinstance(dtcr_df, pd.DataFrame) and dtcr_df.empty):
        raise DTCRRequiredError("A DTCR report is required to generate the compare.")

    old_df, old_layout = load_dtx_report(old_file_bytes, old_file_name)
    new_df, new_layout = load_dtx_report(new_file_bytes, new_file_name)

    results = _annotate_results_with_dtcr(
        compare_reports(old_df, new_df),
        _build_dtcr_lookup_by_cnum(old_df, new_df, dtcr_df),
    )
    results.update(generate_dtcr_matching_report(
        old_file_bytes=old_file_bytes, new_file_bytes=new_file_bytes,
        old_file_name=old_file_name, new_file_name=new_file_name, dtcr_df=dtcr_df))

    all_changes_df = build_all_changes_df(results)
    results["all_changes_df"] = all_changes_df
    results["harness_family_summary_df"] = build_family_summary_df(all_changes_df)
    results["yellow_connectors_df"] = build_yellow_connectors_df(
        _read_dtx_report_rows(new_file_bytes, new_file_name))
    preorder = generate_preorder_generation_workbook(
        old_file_bytes, new_file_bytes, old_file_name, new_file_name)
    results["preorder_summary_df"] = preorder.get("summary_df", pd.DataFrame())

    output = _write_workbook(old_file_name, new_file_name, results)
    return {
        **results,
        "output_excel_bytes": output,
        "output_file_name": build_output_filename(old_file_name, new_file_name),
    }


# --------------------------------------------------------------------------- workbook
def _write_workbook(old_name: str, new_name: str, results: dict) -> bytes:
    all_changes = results["all_changes_df"]
    families = sorted(f for f in all_changes["Harness Family"].dropna().unique() if str(f).strip()) \
        if not all_changes.empty else []

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        wb = writer.book
        wb.set_properties({"title": "DTx Engineering Change Report (WEAVE)",
                           "subject": f"{old_name} vs {new_name}"})
        fmt = _formats(wb)

        # Sheets are referenced by the dashboard's formulas by name, so order is free.
        _write_all_changes(writer, wb, fmt, all_changes)
        _write_dashboard(writer, wb, fmt, results, families, old_name, new_name)
        write_table(writer, "DTCR Matching", results["dtcr_matching_df"], wb, fmt)
        write_table(writer, "Yellow Connectors", results["yellow_connectors_df"], wb, fmt)
        write_table(writer, "PreOrder List", results["preorder_summary_df"], wb, fmt)
        write_table(writer, "Harness Family Summary", results["harness_family_summary_df"], wb, fmt)
        for title, key in (("Added CNUMs", "added_cnums_df"), ("Removed CNUMs", "removed_cnums_df"),
                           ("Added Circuits", "added_circuits_df"), ("Removed Circuits", "removed_circuits_df"),
                           ("Modified Circuits", "modified_circuits_df"), ("Change Log", "change_log_df"),
                           ("CNUM Summary", "cnum_summary_df")):
            df = results.get(key)
            if isinstance(df, pd.DataFrame):
                write_table(writer, title, df, wb, fmt)

        writer.sheets["Dashboard"].activate()
    buf.seek(0)
    return buf.getvalue()


def _formats(wb) -> dict:
    return {
        "title": wb.add_format({"bold": True, "font_size": 16, "font_color": "#1F4E78"}),
        "meta": wb.add_format({"italic": True, "font_color": "#595959"}),
        "header": wb.add_format({"bold": True, "bg_color": "#1F4E78", "font_color": "#FFFFFF", "border": 1}),
        "subheader": wb.add_format({"bold": True, "bg_color": "#DDEBF7", "font_color": "#1F4E78", "border": 1}),
        "section": wb.add_format({"bold": True, "font_size": 12, "font_color": "#1F4E78"}),
        "default": wb.add_format({"border": 1}),
        "num": wb.add_format({"border": 1, "num_format": "0"}),
        "pct": wb.add_format({"border": 1, "num_format": "0.0%"}),
        "sel": wb.add_format({"border": 1, "bold": True, "bg_color": "#FFF2CC"}),
        "label": wb.add_format({"bold": True}),
        "done": wb.add_format({"bg_color": _IMPL_ROW_FILL["Done"]}),
        "prog": wb.add_format({"bg_color": _IMPL_ROW_FILL["In Progress"]}),
        "x": wb.add_format({"bg_color": _IMPL_ROW_FILL["X"]}),
    }


# --------------------------------------------------------------------------- All Changes (+ Status)
def _write_all_changes(writer, wb, fmt, all_changes: pd.DataFrame) -> None:
    """All Changes with a Status column (before DTCR#), a dropdown and status row-colors."""
    df = all_changes.copy()
    if "Status" not in df.columns:
        df.insert(0, "Status", "")                     # Status is the first column, before DTCR#
    ncols = df.shape[1]
    nrows = df.shape[0]
    df.to_excel(writer, sheet_name="All Changes", index=False)
    ws = writer.sheets["All Changes"]
    ws.freeze_panes(1, 1)
    ws.set_row(0, None, fmt["header"])
    if ncols:
        ws.autofilter(0, 0, max(nrows, 1), ncols - 1)
    for i, col in enumerate(df.columns):
        vals = [str(col)] + [normalize_value(v) for v in df[col].tolist()]
        ws.set_column(i, i, min(max((len(v) for v in vals), default=8) + 2, 40))
    ws.set_column(0, 0, 13)                            # Status column width

    last = max(nrows + 1, 2)
    # Status dropdown + status-driven row coloring (Done green / In Progress amber / X red)
    ws.data_validation(1, 0, last - 1, 0, {"validate": "list", "source": list(_IMPL_STATUSES)})
    for status in _IMPL_STATUSES:
        ws.conditional_format(1, 0, last - 1, ncols - 1, {
            "type": "formula", "criteria": f'=$A2="{status}"',
            "format": wb.add_format({"bg_color": _IMPL_ROW_FILL[status]})})


# --------------------------------------------------------------------------- Dashboard
def _write_dashboard(writer, wb, fmt, results, families, old_name, new_name) -> None:
    ws = wb.add_worksheet("Dashboard")
    writer.sheets["Dashboard"] = ws
    ws.hide_gridlines(2)
    for col, w in (("A", 26), ("B", 12), ("C", 13), ("D", 13), ("E", 13), ("F", 3), ("G", 22), ("H", 12)):
        ws.set_column(f"{col}:{col}", w)

    ws.merge_range("A1:H1", "DTx Engineering Change Report", fmt["title"])
    ws.write("A2", f"OLD: {old_name}", fmt["meta"])
    ws.write("A3", f"NEW: {new_name}", fmt["meta"])

    ST = "'All Changes'!$A:$A"          # Status column
    FAM = "'All Changes'!$C:$C"         # Harness Family column (Status, DTCR#, Harness Family, …)

    # ---- Implementation Progress (harness-selectable, live via COUNTIFS) ----
    ws.merge_range("A5:E5", "IMPLEMENTATION PROGRESS", fmt["section"])
    ws.write("A6", "Harness family:", fmt["label"])
    ws.write("B6", _ALL_FAMILIES, fmt["sel"])
    # The family list is too long for an inline dropdown (Excel caps at 255 chars), so drive
    # the dropdown from a hidden range in column R and put the COUNTIFS criterion in Q1.
    ws.write(0, 17, _ALL_FAMILIES)                                       # R1
    for i, family in enumerate(families):
        ws.write(1 + i, 17, family)                                     # R2, R3, …
    ws.set_column("Q:R", None, None, {"hidden": True})
    ws.data_validation("B6", {"validate": "list", "source": f"=$R$1:$R${1 + len(families)}"})
    ws.write_formula("Q1", f'=IF($B$6="{_ALL_FAMILIES}","*",$B$6)')     # criterion helper
    crit = "$Q$1"

    ws.write("A8", "Status", fmt["subheader"]); ws.write("B8", "Count", fmt["subheader"])
    rows = [
        ("Done",        f'=COUNTIFS({ST},"Done",{FAM},{crit})',        fmt["done"]),
        ("In Progress", f'=COUNTIFS({ST},"In Progress",{FAM},{crit})', fmt["prog"]),
        ("Needs Review (X)", f'=COUNTIFS({ST},"X",{FAM},{crit})',      fmt["x"]),
        ("Not started", "=MAX(0,$B$12-$B$9-$B$10-$B$11)",              fmt["default"]),
    ]
    for i, (label, formula, cell_fmt) in enumerate(rows):
        ws.write(8 + i, 0, label, cell_fmt)
        ws.write_formula(8 + i, 1, formula, fmt["num"])
    ws.write("A13", "Total relevant", fmt["label"]); ws.write_formula("B13", f"=COUNTIF({FAM},{crit})", fmt["num"])
    ws.write("A14", "% complete", fmt["label"]);     ws.write_formula("B14", "=IF($B$13=0,0,$B$9/$B$13)", fmt["pct"])

    donut = wb.add_chart({"type": "doughnut"})
    donut.add_series({
        "name": "Implementation progress",
        "categories": ["Dashboard", 8, 0, 11, 0],
        "values": ["Dashboard", 8, 1, 11, 1],
        "points": [{"fill": {"color": _IMPL_CHART_COLOR[s]}} for s in ("Done", "In Progress", "X", "Not started")],
    })
    donut.set_title({"name": "Progress (selected harness)", "name_font": {"size": 11}})
    donut.set_legend({"position": "right"})
    ws.insert_chart("D6", donut, {"x_scale": 1.0, "y_scale": 1.0})

    # ---- Progress by harness family (all families; recomputes as Status changes) ----
    ws.merge_range("A17:E17", "PROGRESS BY HARNESS FAMILY", fmt["section"])
    hdr = ["Harness Family", "Done", "In Progress", "Needs Review", "Not started"]
    for c, h in enumerate(hdr):
        ws.write(17, c, h, fmt["subheader"])
    start = 18
    for i, family in enumerate(families):
        r = start + i
        fam_cell = f"$A${r + 1}"
        ws.write(r, 0, family, fmt["default"])
        ws.write_formula(r, 1, f'=COUNTIFS({ST},"Done",{FAM},{fam_cell})', fmt["num"])
        ws.write_formula(r, 2, f'=COUNTIFS({ST},"In Progress",{FAM},{fam_cell})', fmt["num"])
        ws.write_formula(r, 3, f'=COUNTIFS({ST},"X",{FAM},{fam_cell})', fmt["num"])
        ws.write_formula(r, 4, f'=MAX(0,COUNTIF({FAM},{fam_cell})-B{r + 1}-C{r + 1}-D{r + 1})', fmt["num"])
    last_fam = start + max(len(families), 1) - 1
    if families:
        bar = wb.add_chart({"type": "bar", "subtype": "stacked"})
        for col, name in ((1, "Done"), (2, "In Progress"), (3, "Needs Review"), (4, "Not started")):
            key = {1: "Done", 2: "In Progress", 3: "X", 4: "Not started"}[col]
            bar.add_series({
                "name": name,
                "categories": ["Dashboard", start, 0, last_fam, 0],
                "values": ["Dashboard", start, col, last_fam, col],
                "fill": {"color": _IMPL_CHART_COLOR[key]},
            })
        bar.set_title({"name": "Progress by harness family", "name_font": {"size": 11}})
        bar.set_legend({"position": "bottom"})
        bar.set_y_axis({"reverse": True})
        ws.insert_chart("G17", bar, {"x_scale": 1.6, "y_scale": 1.3})

    # ---- DTCR coverage (static — fixed at generation) ----
    dtcr = results["dtcr_matching_df"]
    method = dtcr["Match Method"].astype(str) if "Match Method" in dtcr.columns else pd.Series([], dtype=str)
    cov = [
        ("Matched — Device Control #", int((method == "Device Control Number").sum())),
        ("Matched — Device Name", int((method == "Device Name").sum())),
        ("Unmatched", int((method == "No Match").sum())),
    ]
    base = last_fam + 3
    ws.merge_range(base, 0, base, 4, "DTCR COVERAGE", fmt["section"])
    ws.write(base + 1, 0, "Match method", fmt["subheader"]); ws.write(base + 1, 1, "DTCRs", fmt["subheader"])
    for i, (label, value) in enumerate(cov):
        ws.write(base + 2 + i, 0, label, fmt["default"])
        ws.write_number(base + 2 + i, 1, value, fmt["num"])
    ws.write(base + 5, 0, "Total DTCRs", fmt["label"]); ws.write_number(base + 5, 1, int(len(dtcr)), fmt["num"])
    pie = wb.add_chart({"type": "pie"})
    pie.add_series({
        "name": "DTCR match coverage",
        "categories": ["Dashboard", base + 2, 0, base + 4, 0],
        "values": ["Dashboard", base + 2, 1, base + 4, 1],
        "points": [{"fill": {"color": c}} for c in ("#2E7D32", "#58A6FF", "#C00000")],
    })
    pie.set_title({"name": "DTCR match coverage", "name_font": {"size": 11}})
    pie.set_legend({"position": "right"})
    ws.insert_chart(base + 1, 3, pie, {"x_scale": 1.0, "y_scale": 1.0})
