"""SECR creation engine — Streamlit-compatible (BytesIO, no file paths)."""
from __future__ import annotations

import copy
import datetime
import io
from pathlib import Path
from typing import Any, Dict, Tuple

import openpyxl
from openpyxl.cell import MergedCell

TEMPLATE_PATH = Path(__file__).resolve().parent / "assets" / "SECR_TEMPLATE.xlsx"

SUMMARY_SHEET = "Summary"
DEF_DEF_SUMMARY_SHEET = "DEF_DEF_Summary"
CONNECTOR_SHEET = "Connector"
CIRCUIT_SHEET = "Circuit"


# ---------------------------------------------------------------------------
# Sheet copying helpers
# ---------------------------------------------------------------------------

def _copy_cell_style(source_cell, target_cell) -> None:
    try:
        if source_cell.has_style:
            target_cell.font = copy.copy(source_cell.font)
            target_cell.fill = copy.copy(source_cell.fill)
            target_cell.border = copy.copy(source_cell.border)
            target_cell.alignment = copy.copy(source_cell.alignment)
            target_cell.number_format = copy.copy(source_cell.number_format)
            target_cell.protection = copy.copy(source_cell.protection)
        if source_cell.hyperlink:
            target_cell._hyperlink = copy.copy(source_cell.hyperlink)
        if source_cell.comment:
            target_cell.comment = copy.copy(source_cell.comment)
    except Exception:
        pass


def _copy_sheet(source_ws, target_wb) -> None:
    target_ws = target_wb.create_sheet(title=source_ws.title)
    max_row = source_ws.max_row or 0
    max_col = source_ws.max_column or 0
    if max_row > 0 and max_col > 0:
        for row in source_ws.iter_rows():
            if row is None:
                continue
            for cell in row:
                if cell is None or isinstance(cell, MergedCell):
                    continue
                new_cell = target_ws.cell(row=cell.row, column=cell.column, value=cell.value)
                _copy_cell_style(cell, new_cell)
    if hasattr(source_ws, "column_dimensions"):
        for col_letter, dim in source_ws.column_dimensions.items():
            target_ws.column_dimensions[col_letter].width = dim.width
    if hasattr(source_ws, "row_dimensions"):
        for row_idx, dim in source_ws.row_dimensions.items():
            target_ws.row_dimensions[row_idx].height = dim.height
    if hasattr(source_ws, "merged_cells") and source_ws.merged_cells:
        for merged_range in source_ws.merged_cells.ranges:
            target_ws.merge_cells(str(merged_range))
    target_ws.sheet_format.defaultColWidth = source_ws.sheet_format.defaultColWidth
    target_ws.sheet_format.defaultRowHeight = source_ws.sheet_format.defaultRowHeight
    target_ws.freeze_panes = source_ws.freeze_panes


# ---------------------------------------------------------------------------
# Action-column lookup (find by header name, not by position)
# ---------------------------------------------------------------------------

def _find_action_col(ws, header_row: int = 3) -> int:
    """Return the 1-based column index whose header equals 'Action' (case-insensitive).
    Falls back to the first non-empty column in that row if not found."""
    for c in range(1, (ws.max_column or 1) + 1):
        val = ws.cell(row=header_row, column=c).value
        if val and str(val).strip().lower() == "action":
            return c
    return 1  # fallback


# ---------------------------------------------------------------------------
# DEF sheet processors — update Summary from copied DEF sheets
# ---------------------------------------------------------------------------

def _process_def_def_summary(wb_secr, ws_summary) -> None:
    if DEF_DEF_SUMMARY_SHEET not in wb_secr.sheetnames:
        return
    ws = wb_secr[DEF_DEF_SUMMARY_SHEET]

    ws.insert_cols(1)
    ws.cell(row=3, column=1, value="Content")

    action_col = _find_action_col(ws, header_row=3)
    # The value column was originally 3 positions after Action (col D when Action=col A)
    value_col = action_col + 3

    delete_values, chg_values, add_values = [], [], []
    for row_idx in range(4, (ws.max_row or 3) + 1):
        action = ws.cell(row=row_idx, column=action_col).value
        value = ws.cell(row=row_idx, column=value_col).value
        if value is not None:
            s = str(value)
            if action == "DELETE":
                delete_values.append(s)
            elif action == "CHG":
                chg_values.append(s)
            elif action == "ADD":
                add_values.append(s)

    ws_summary["C32"] = ", ".join(delete_values) if delete_values else ""
    ws_summary["C31"] = ", ".join(chg_values) if chg_values else ""
    ws_summary["C30"] = ", ".join(add_values) if add_values else ""


def _process_connector_sheet(wb_secr, ws_summary) -> None:
    if CONNECTOR_SHEET not in wb_secr.sheetnames:
        return
    ws = wb_secr[CONNECTOR_SHEET]

    ws.insert_cols(1)
    ws.cell(row=3, column=1, value="Comments")

    action_col = _find_action_col(ws, header_row=3)
    connector_col = action_col + 1

    delete_vals, chg_vals, add_vals = [], [], []
    for row_idx in range(4, (ws.max_row or 3) + 1):
        action = ws.cell(row=row_idx, column=action_col).value
        connector = ws.cell(row=row_idx, column=connector_col).value
        if connector is not None:
            s = str(connector)
            if action == "DELETE":
                delete_vals.append(s)
            elif action in ("COMP CHG", "CHG"):
                chg_vals.append(s)
            elif action == "ADD":
                add_vals.append(s)

    delete_set, add_set = set(delete_vals), set(add_vals)
    common = delete_set & add_set
    if common:
        chg_vals.extend(common)
        delete_vals = list(delete_set - common)
        add_vals = list(add_set - common)

    ws_summary["C22"] = ", ".join(sorted(set(delete_vals))) if delete_vals else ""
    combined_chg_add = sorted(set(chg_vals + add_vals))
    ws_summary["C21"] = ", ".join(combined_chg_add) if combined_chg_add else ""


def _process_circuit_sheet(wb_secr, ws_summary) -> None:
    if CIRCUIT_SHEET not in wb_secr.sheetnames:
        return
    ws = wb_secr[CIRCUIT_SHEET]

    ws.insert_cols(1)
    ws.cell(row=3, column=1, value="Comments")

    action_col = _find_action_col(ws, header_row=3)
    val_b_col = action_col + 1
    val_c_col = action_col + 2

    delete_vals, chg_vals, add_vals = [], [], []
    for row_idx in range(4, (ws.max_row or 3) + 1):
        action = ws.cell(row=row_idx, column=action_col).value
        b = ws.cell(row=row_idx, column=val_b_col).value
        c = ws.cell(row=row_idx, column=val_c_col).value
        combined = (
            (str(b) if b is not None else "") + (str(c) if c is not None else "")
        ).strip()
        if combined:
            if action == "DELETE":
                delete_vals.append(combined)
            elif action in ("CHG", "COMP CHG", "COMP CHG "):
                chg_vals.append(combined)
            elif action == "ADD":
                add_vals.append(combined)

    delete_set, add_set = set(delete_vals), set(add_vals)
    common = delete_set & add_set
    if common:
        chg_vals.extend(common)
        delete_vals = list(delete_set - common)
        add_vals = list(add_set - common)

    ws_summary["C27"] = ", ".join(sorted(set(delete_vals))) if delete_vals else ""
    ws_summary["C25"] = ", ".join(sorted(set(add_vals))) if add_vals else ""
    ws_summary["C26"] = ", ".join(sorted(set(chg_vals))) if chg_vals else ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_secr_bytes(
    def_bytes: bytes,
    def_filename: str,
    reason_for_change: str,
    secr_author: str,
    design_release_engineer: str,
    change_requested_by: str,
    original_issue_date: str,
    reissue_date: str,
    version: str,
    phase_implemented: str,
    pull_ahead: str,
    m_code_suffix: int = 1,
) -> Tuple[bytes, Dict[str, Any]]:
    """Create a SECR workbook from DEF compare bytes.

    Parameters mirror the original GUI dialog fields. Returns (excel_bytes, metadata).
    """
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"SECR template not found: {TEMPLATE_PATH}")

    # Parse metadata from DEF filename
    stem = Path(def_filename).stem
    parts = stem.split("_")
    if len(parts) < 5:
        raise ValueError(
            "DEF filename must have at least 5 underscore-separated parts "
            "(e.g. 2027_RU_X2_A_vs_2026_RU_X2_A_IP_DEF_DEF_Compare_...)."
        )

    my_full = parts[0]
    vehicle_line = parts[1]
    code1 = parts[2]
    code2 = parts[3]

    idx_def = next((i for i, p in enumerate(parts) if p == "DEF"), None)
    if idx_def is None or idx_def == 0:
        raise ValueError("Could not find 'DEF' segment in the filename.")

    pre_def_string = parts[idx_def - 1]
    c10_value = my_full
    c11_value = vehicle_line
    f10_value = f"{code1}_{code2}"
    c12_value = pre_def_string
    my_two = c10_value[-2:]
    m_code = f"M{my_two}{m_code_suffix:03d}"

    wb_template = openpyxl.load_workbook(str(TEMPLATE_PATH))
    wb_def = openpyxl.load_workbook(io.BytesIO(def_bytes), data_only=False)

    if SUMMARY_SHEET not in wb_template.sheetnames:
        raise ValueError("SECR template has no 'Summary' sheet.")

    ws_summary = wb_template[SUMMARY_SHEET]

    # Fill Summary from filename metadata
    ws_summary["C10"] = int(c10_value) if c10_value.isdigit() else c10_value
    ws_summary["C11"] = c11_value
    ws_summary["F10"] = f10_value
    ws_summary["C12"] = c12_value
    ws_summary["I2"] = m_code

    # Copy all DEF sheets into the template workbook
    for ws in wb_def.worksheets:
        _copy_sheet(ws, wb_template)
    wb_def.close()

    # Reorder: Summary first
    summary_ws = next(
        (ws for ws in wb_template.worksheets if ws.title == SUMMARY_SHEET), None
    )
    if summary_ws:
        others = [ws for ws in wb_template.worksheets if ws is not summary_ws]
        wb_template._sheets = [summary_ws] + others

    # Fill user-provided details into Summary
    ws_summary["C7"] = reason_for_change
    ws_summary["I10"] = secr_author
    ws_summary["I11"] = design_release_engineer
    ws_summary["I12"] = change_requested_by
    ws_summary["I3"] = version
    ws_summary["F11"] = phase_implemented
    ws_summary["F12"] = pull_ahead
    if original_issue_date:
        ws_summary["I4"] = original_issue_date
    if reissue_date:
        ws_summary["I5"] = reissue_date

    # Process copied DEF sheets → populate Summary circuit/connector blocks
    _process_def_def_summary(wb_template, ws_summary)
    _process_connector_sheet(wb_template, ws_summary)
    _process_circuit_sheet(wb_template, ws_summary)

    # Unprotect all sheets so the user can edit the output
    for ws in wb_template.worksheets:
        ws.protection.disable()
    if hasattr(wb_template, "security") and wb_template.security is not None:
        wb_template.security.lockStructure = False
        wb_template.security.lockWindows = False
        wb_template.security.lockRevision = False

    creation_date = datetime.date.today().strftime("%m%d%Y")
    secr_filename = (
        f"SECR_{my_two}{c11_value}_{f10_value}_{c12_value}_{m_code}_{creation_date}.xlsx"
    )

    buf = io.BytesIO()
    wb_template.save(buf)
    wb_template.close()
    buf.seek(0)

    return buf.read(), {
        "C10": c10_value,
        "C11": c11_value,
        "F10": f10_value,
        "C12": c12_value,
        "I2": m_code,
        "filename": secr_filename,
    }
