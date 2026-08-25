"""The SECR Database workspace: browse, create, update, import, dashboard.

Instead of opening a folder of Excel files and searching them by hand, an
engineer searches here and gets the SECR, the change, the old value and the
new value.

The page is thin by design. It reads through :mod:`splice.secr.api` (the
read-only query surface) and writes only through :mod:`splice.secr.importer`
and the two explicit database calls behind the delete button. No SQL is
written here, so the same workflow can be lifted onto a different UI later.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date
from typing import Any, Dict, List

import altair as alt
import pandas as pd
import streamlit as st

from secrdb.core.common.errors import SpliceError
from ui.support import guard, render_support_panel
from secrdb.core.dtcr import library
from secrdb.core.secr import api, batch, db as secr_db, generation, identity
from secrdb.core.secr.enrich import load_dtcr_matching_report
from secrdb.core.secr.importer import import_secr_files

NS = "secrdb_"

#: Columns shown in the browser table, in engineering reading order.
_BROWSER_COLUMNS = [
    ("secr_number", "SECR"),
    ("version", "Ver"),
    ("program", "Program"),
    ("model_year", "MY"),
    ("bulletin_numbers", "Bulletin"),
    ("harness_family", "Harness"),
    ("dtcr_numbers", "DTCR"),
    ("change_count", "Changes"),
    ("phase", "Phase"),
    ("original_issue_date", "Issued"),
]

_CHANGE_COLUMNS = [
    ("action", "Type"),
    ("object_type", "Object"),
    ("object_id", "ID"),
    ("field", "Field"),
    ("old_value", "Old"),
    ("new_value", "New"),
    ("dtcr_number", "DTCR"),
    ("sales_code", "Sales code"),
    ("se_comment", "SE comment"),
    ("source_sheet", "Sheet"),
    ("source_row", "Row"),
]


def _k(name: str) -> str:
    return f"{NS}{name}"


# ---------------------------------------------------------------------------
# Chart layer
# ---------------------------------------------------------------------------
#
# Every chart here answers a magnitude question about nominal categories
# ("which CNUM changed most"), so each is a horizontal bar chart with **one**
# colour — a value-ramp across nominal categories would double-encode bar
# length as hue and buy nothing. Colour instead carries *selection state*:
# the filtered category keeps the accent hue and the rest recede to grey, so
# the chart shows what is filtered without a separate legend.
#
# Steps come from the validated palette (sequential blue slot 1) with a step
# chosen per theme, because the app renders on both a light and a dark surface.
#
# Validator results for the accent/muted pair (scripts/validate_palette.js):
# CVD separation PASS (ΔE 26.2 light / 22.1 dark, target >= 8) and normal-vision
# PASS (29.5 / 22.8, floor 15) — the two are unambiguously distinguishable,
# colour vision deficiency included. The muted step warns below 3:1 against the
# surface, which is deliberate (a de-emphasis colour that competed with the
# accent would defeat the point) and carries the required relief: every bar is
# direct-labelled on the category axis and the same rows appear in the change
# table below. The validator's lightness/chroma FAILs are its categorical-series
# checks and do not apply to a de-emphasis grey.

_PALETTE = {
    "light": {
        "accent": "#2a78d6",
        "muted": "#c3c2b7",
        "grid": "#e1e0d9",
        "text": "#52514e",
    },
    "dark": {
        "accent": "#3987e5",
        "muted": "#5a5a56",
        "grid": "#2c2c2a",
        "text": "#c3c2b7",
    },
}

#: Status is a *state*, not a series, so it gets the reserved status steps and
#: never a categorical hue. Always rendered with its label and count beside it —
#: colour is the secondary signal here, never the only one.
_STATUS_COLORS = {
    "light": {"good": "#3d8b52", "critical": "#c0392b", "neutral": "#8a8981"},
    "dark": {"good": "#5aa870", "critical": "#e05f52", "neutral": "#8a8981"},
}

#: Which status step a value earns. Anything unrecognised stays neutral rather
#: than being guessed into "good".
_STATUS_KIND = {
    "COMPLETE": "good",
    "REJECTED": "critical",
    "DELETED": "neutral",
}

#: The charts, in reading order: what changed, then where, then who asked.
_FACET_CHARTS = [
    ("action", "Change type", "Changes by type"),
    ("object_type", "Object", "What was changed"),
    ("harness_family", "Harness family", "Most affected harness families"),
    ("connectors", "CNUM", "Most changed connectors"),
    ("circuits", "Circuit", "Most changed circuits"),
    ("dtcr_number", "DTCR #", "Most active DTCRs"),
]

#: Facet name -> the filter key a click on that chart sets.
_FACET_FILTER = {
    "action": "action",
    "object_type": "object_type",
    "harness_family": "harness_family",
    "connectors": "cnum",
    "circuits": "circuit",
    "dtcr_number": "dtcr_number",
    "program": "program",
    "model_year": "model_year",
}

_FILTER_LABELS = {
    "query": "Search",
    "action": "Change type",
    "object_type": "Object",
    "harness_family": "Harness",
    "object_id": "Object ID",
    "cnum": "CNUM",
    "circuit": "Circuit",
    "dtcr_number": "DTCR #",
    "program": "Program",
    "model_year": "Model Year",
    "phase": "Phase",
    "bulletin": "Bulletin",
}


def _colors() -> Dict[str, str]:
    """Palette steps for the surface the chart actually renders on."""
    theme = getattr(st.context, "theme", None)
    mode = "dark" if getattr(theme, "type", "light") == "dark" else "light"
    return _PALETTE[mode]


def _filters() -> Dict[str, str]:
    return st.session_state.setdefault(_k("filters"), {})


def _apply_selection(chart_key: str, filter_key: str, picked: Any) -> None:
    """Mirror a chart's selection into the filters, once per actual change.

    A chart's selection lives in widget state and is replayed on every rerun,
    so acting on it unconditionally would re-apply (and with toggle logic,
    undo) the filter on the rerun that the click itself triggered. Comparing
    against the last value seen for this chart makes a click act exactly once.
    Deselecting in the chart clears that filter.
    """
    memo_key = _k(f"last_{chart_key}")
    if picked == st.session_state.get(memo_key):
        return
    st.session_state[memo_key] = picked
    filters = _filters()
    if picked is None:
        filters.pop(filter_key, None)
    else:
        filters[filter_key] = picked
    st.rerun()


def _reset_chart_selections() -> None:
    """Forget every chart's selection so the next click registers immediately.

    Used when a filter is removed from outside the charts (a chip, Clear all);
    without it a chart still holds the old selection and the first click on
    that same bar only deselects it.
    """
    for state_key in list(st.session_state.keys()):
        if state_key.startswith(_k("chart_")) or state_key.startswith(_k("last_")):
            del st.session_state[state_key]


#: Name of the Vega selection parameter; Streamlit keys the event payload on it.
_PICK = "pick"


def _bar_chart(
    rows: List[Dict[str, Any]],
    *,
    label: str,
    filter_key: str = "",
    selected: str = "",
    key: str = "",
) -> None:
    """One horizontal bar chart. Clicking a bar sets (or clears) its filter.

    Passing no ``filter_key`` renders it read-only (the overview tab).
    """
    if not rows:
        st.caption("No data.")
        return

    colors = _colors()
    frame = pd.DataFrame(rows)
    frame["name"] = frame["name"].astype(str)
    # No filter on this facet -> every bar is "selected", so the chart reads as
    # a plain magnitude comparison rather than an all-grey one.
    frame["selected"] = (
        frame["name"] == selected if selected else True
    )

    chart = (
        alt.Chart(frame)
        .mark_bar(cornerRadiusEnd=4, height=14)
        .encode(
            y=alt.Y(
                "name:N",
                sort=alt.SortField("n", order="descending"),
                title=None,
                axis=alt.Axis(
                    labelColor=colors["text"],
                    labelFontSize=12,
                    domain=False,
                    ticks=False,
                    labelLimit=150,
                    # Vega drops labels that would collide; with one label per
                    # bar there is nothing to thin out, and a half-labelled
                    # category axis is unreadable.
                    labelOverlap=False,
                ),
            ),
            x=alt.X(
                "n:Q",
                title=None,
                axis=alt.Axis(
                    labelColor=colors["text"],
                    labelFontSize=11,
                    gridColor=colors["grid"],
                    gridWidth=1,
                    domain=False,
                    ticks=False,
                    tickCount=4,
                ),
            ),
            color=alt.condition(
                alt.datum.selected,
                alt.value(colors["accent"]),
                alt.value(colors["muted"]),
            ),
            tooltip=[
                alt.Tooltip("name:N", title=label),
                alt.Tooltip("n:Q", title="Changes", format=","),
            ],
        )
        .properties(height=alt.Step(23))
    )

    if not filter_key:
        st.altair_chart(
            chart.configure_view(strokeWidth=0), width="stretch"
        )
        return

    chart = chart.add_params(
        alt.selection_point(fields=["name"], name=_PICK, empty=False)
    ).configure_view(strokeWidth=0)

    event = st.altair_chart(chart, width="stretch", on_select="rerun", key=key)
    _apply_selection(key, filter_key, _picked_value(event))


def _picked_value(event) -> Any:
    """The category a click landed on, or ``None`` if the click missed."""
    selection = getattr(event, "selection", None)
    if selection is None and isinstance(event, dict):
        selection = event.get("selection")
    points = (selection or {}).get(_PICK) or []
    if not points:
        return None
    value = points[0].get("name")
    return str(value) if value is not None else None


def _as_frame(rows: List[Dict[str, Any]], columns) -> pd.DataFrame:
    """Project dict rows onto labelled columns, preserving strings as strings."""
    if not rows:
        return pd.DataFrame(columns=[label for _, label in columns])
    frame = pd.DataFrame(
        [{label: row.get(key) for key, label in columns} for row in rows]
    )
    return frame.astype(object).where(frame.notna(), "")


def render() -> None:
    """Render the SECR Database page."""
    st.title("SECR Database")
    st.caption(
        "Every SECR generated here or imported from a file, searchable by SECR #, "
        "DTCR, CNUM, circuit, connector part number, program, or harness family."
    )

    tab_browse, tab_create, tab_update, tab_import, tab_dashboard = st.tabs(
        [
            "Browse",
            "Create SECR",
            "Update SECR",
            "Import SECR files",
            "DTCR Reports",
        ]
    )
    with tab_browse:
        with guard("browse"):
            _browse()
    with tab_create:
        with guard("create_secr"):
            _create_secr()
    with tab_update:
        with guard("update_secr"):
            _update_secr()
    with tab_import:
        with guard("import"):
            _import()
    with tab_dashboard:
        with guard("dashboard"):
            _dashboard()

    render_support_panel(where="database")


# ---------------------------------------------------------------------------
# Browse + search + filters
# ---------------------------------------------------------------------------

def _browse() -> None:
    """Four things, in reading order: how many SECRs, which harnesses carry the
    most change, the SECRs themselves, and the changes of the one you pick.

    The harness chart doubles as the filter — one click narrows the count and
    the table, one click on its chip clears it. Picking a SECR is a click on
    its row.
    """
    filters = _filters()

    search = st.text_input(
        "Search",
        value=filters.get("query", ""),
        key=_k("query_input"),
        placeholder="CNUM, circuit, connector PN, DTCR, SECR #, or harness family…",
        help=(
            "Matches a CNUM, circuit, connector part number, DTCR, SECR #, "
            "bulletin, harness family, or any old/new value."
        ),
    )
    if search.strip() != filters.get("query", ""):
        if search.strip():
            filters["query"] = search.strip()
        else:
            filters.pop("query", None)
        st.rerun()

    _filter_chips()

    try:
        facets = secr_db.change_facets(top_n=10, **filters)
        secrs = _matching_secrs(filters)
    except Exception as exc:  # noqa: BLE001 - a broken DB must not blank the page
        st.error(f"Could not read the SECR database: {exc}")
        return

    if not secrs:
        st.info(
            "No SECRs match. Clear a filter above, or import SECR files in "
            "the **Import SECR files** tab."
        )
        return

    col_count, col_chart = st.columns([1, 3])
    with col_count:
        st.metric("SECRs", f"{len(secrs):,}")
    with col_chart:
        st.markdown("**Most affected harness families**")
        _bar_chart(
            facets["harness_family"],
            label="Harness family",
            filter_key="harness_family",
            selected=filters.get("harness_family", ""),
            key=_k("chart_harness_family"),
        )
        st.caption("Click a bar to filter · use the ✕ chip above to clear")

    _dimension_filters()
    _secr_table(secrs)


#: The database's own dimensions, as dropdowns under the chart. Each writes the
#: same filter key the chart and the chips use, so the three stay in step.
_DIMENSION_FILTERS = [
    ("program", "Program"),
    ("phase", "Phase"),
    ("model_year", "Model Year"),
    ("harness_family", "Harness"),
]


def _dimension_filters() -> None:
    """Program / Phase / Model Year / Harness, straight from the database.

    Options are the values actually present, so a filter can never select an
    empty result. Selecting a harness here and clicking its bar on the chart
    are the same action — both set ``harness_family``.
    """
    filters = _filters()
    columns = st.columns(len(_DIMENSION_FILTERS))
    for column, (key, label) in zip(columns, _DIMENSION_FILTERS):
        try:
            options = ["All"] + secr_db.distinct_values(key)
        except Exception:  # noqa: BLE001 - a bad column must not blank the page
            options = ["All"]
        current = filters.get(key, "")
        # The index is derived from the filter dict rather than held in widget
        # state, so a value set by clicking the chart shows up here too.
        index = options.index(current) if current in options else 0
        choice = column.selectbox(label, options, index=index)
        chosen = "" if choice == "All" else choice
        if chosen != current:
            if chosen:
                filters[key] = chosen
            else:
                filters.pop(key, None)
            _reset_chart_selections()
            st.rerun()


def _matching_secrs(filters: Dict[str, str]) -> List[Dict[str, Any]]:
    """The SECRs behind the current filters, newest first.

    Derived from the change records so the list always agrees with the chart
    above it: a SECR appears because one of its changes matched.
    """
    rows = secr_db.find_changes(limit=100_000, **filters)
    by_id: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        record = by_id.setdefault(
            row["secr_id"],
            {
                "id": row["secr_id"],
                "secr_number": row["secr_number"],
                "version": row["version"],
                "program": row["program"],
                "model_year": row["model_year"],
                "bulletin_numbers": row["bulletin_numbers"],
                "harness_family": row["harness_family"],
                "phase": row["phase"],
                "change_count": 0,
            },
        )
        record["change_count"] += 1
    return sorted(by_id.values(), key=lambda r: -r["id"])


#: The SECR list. One row per SECR, with how many changes matched.
_SECR_TABLE_COLUMNS = [
    ("secr_number", "SECR"),
    ("version", "Ver"),
    ("program", "Program"),
    ("model_year", "MY"),
    ("phase", "Phase"),
    ("harness_family", "Harness"),
    ("bulletin_numbers", "Bulletin"),
    ("change_count", "Changes"),
]


def _secr_table(secrs: List[Dict[str, Any]]) -> None:
    """The SECRs in the database. Selecting a row opens its changes."""
    st.markdown(f"**SECRs** ({len(secrs):,})")
    event = st.dataframe(
        _as_frame(secrs, _SECR_TABLE_COLUMNS),
        width="stretch",
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=_k("secr_rows"),
    )

    selected = list(getattr(event, "selection", {}).get("rows") or [])
    if not selected:
        st.caption("Select a SECR row to see its changes.")
        return
    index = selected[0]
    if index < len(secrs):
        _detail(secrs[index]["id"])


def _filter_chips() -> None:
    """Always-visible active filters, each one click from being removed."""
    filters = _filters()
    if not filters:
        st.caption("Showing every change in the database.")
        return

    columns = st.columns(len(filters) + 1)
    for column, (key, value) in zip(columns, list(filters.items())):
        label = _FILTER_LABELS.get(key, key)
        if column.button(
            f"✕  {label}: {value}",
            key=_k(f"chip_{key}"),
            help=f"Remove the {label} filter",
        ):
            filters.pop(key, None)
            _reset_chart_selections()
            st.rerun()
    if columns[-1].button("Clear all", key=_k("clear_all")):
        filters.clear()
        _reset_chart_selections()
        st.rerun()


# ---------------------------------------------------------------------------
# Detail view
# ---------------------------------------------------------------------------

def _detail(secr_id: int) -> None:
    record = secr_db.get_secr(secr_id)
    if record is None:
        st.warning("That SECR is no longer in the database.")
        return

    st.divider()
    st.subheader(f"SECR {record['secr_number']} · version {record['version']}")

    col1, col2, col3, col4 = st.columns(4)
    col1.markdown(f"**Program**\n\n{record.get('program') or '—'}")
    col2.markdown(f"**Model Year**\n\n{record.get('model_year') or '—'}")
    col3.markdown(f"**Phase**\n\n{record.get('phase') or '—'}")
    col4.markdown(f"**Harness Family**\n\n{record.get('harness_family') or '—'}")

    col5, col6, col7, col8 = st.columns(4)
    col5.markdown(f"**Bulletin #**\n\n{record.get('bulletin_numbers') or '—'}")
    col6.markdown(f"**DTCR #**\n\n{record.get('dtcr_numbers') or '—'}")
    col7.markdown(f"**Author**\n\n{record.get('secr_author') or '—'}")
    col8.markdown(f"**Issued**\n\n{record.get('original_issue_date') or '—'}")

    if record.get("subject"):
        st.markdown(f"**Subject** — {record['subject']}")

    origin = record.get("import_origin") or "generated"
    source = record.get("source_file")
    provenance = f"Origin: {origin}"
    if record.get("source_def_filename"):
        provenance += f" · from DEF `{record['source_def_filename']}`"
    if source:
        provenance += (
            f" · original file `{source['filename']}` "
            f"({source['size_bytes'] // 1024} KB, sha256 {source['sha256'][:12]}…)"
        )
    st.caption(provenance)

    if record.get("warnings"):
        with st.expander(
            f"⚠️ {len(record['warnings'])} data-quality note(s) on this SECR",
            expanded=False,
        ):
            for warning in record["warnings"]:
                st.write(f"- {warning}")

    _detail_changes(record)
    _detail_dtcrs(record)
    _detail_actions(record)


def _detail_changes(record: Dict[str, Any]) -> None:
    changes = record.get("changes") or []
    st.markdown(f"#### Changes ({len(changes)})")
    if not changes:
        st.info(
            "No change records were stored for this SECR. If it was saved before "
            "change tracking existed, re-import the original file to populate them."
        )
        return

    col1, col2 = st.columns(2)
    object_types = sorted({c["object_type"] for c in changes})
    actions = sorted({c["action"] for c in changes})
    object_filter = col1.multiselect(
        "Object type", object_types, default=object_types, key=_k("d_objects")
    )
    action_filter = col2.multiselect(
        "Change type", actions, default=actions, key=_k("d_actions")
    )
    shown = [
        c
        for c in changes
        if c["object_type"] in object_filter and c["action"] in action_filter
    ]
    st.dataframe(
        _as_frame(shown, _CHANGE_COLUMNS), width="stretch", hide_index=True
    )
    st.caption(
        f"Showing {len(shown)} of {len(changes)} change records. "
        "Sheet/Row point back to the exact row of the source workbook."
    )


def _detail_dtcrs(record: Dict[str, Any]) -> None:
    dtcrs = record.get("dtcrs") or []
    if not dtcrs:
        return
    with st.expander(f"DTCR detail ({len(dtcrs)} row(s))", expanded=False):
        st.dataframe(pd.DataFrame(dtcrs), width="stretch", hide_index=True)


def _detail_actions(record: Dict[str, Any]) -> None:
    col_download, col_delete = st.columns(2)

    with col_download:
        stored = secr_db.get_source_file(record["id"])
        if stored and stored.get("content"):
            st.download_button(
                "Download original SECR file",
                data=stored["content"],
                file_name=stored["filename"],
                mime=(
                    "application/vnd.openxmlformats-officedocument"
                    ".spreadsheetml.sheet"
                ),
                key=_k(f"dl_{record['id']}"),
            )
        else:
            st.caption("No original file stored for this record.")

    with col_delete:
        confirm_key = _k(f"confirm_delete_{record['id']}")
        if st.session_state.get(confirm_key):
            change_count = len(record.get("changes") or [])
            st.warning(
                f"Delete SECR {record['secr_number']} version {record['version']}?\n\n"
                f"This removes the SECR and its {change_count} change record(s) "
                "from the database. The deletion is written to the audit log."
            )
            cancel, delete = st.columns(2)
            if cancel.button("Cancel", key=_k(f"cancel_{record['id']}")):
                st.session_state[confirm_key] = False
                st.rerun()
            if delete.button(
                "Delete", type="primary", key=_k(f"do_delete_{record['id']}")
            ):
                try:
                    deleted = secr_db.delete_secr(record["id"])
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Could not delete the record: {exc}")
                    return
                st.session_state[confirm_key] = False
                if deleted:
                    st.success(f"Deleted SECR {record['secr_number']}.")
                else:
                    st.info("That record had already been removed.")
                st.rerun()
        elif st.button("Delete this SECR…", key=_k(f"ask_delete_{record['id']}")):
            st.session_state[confirm_key] = True
            st.rerun()


# ---------------------------------------------------------------------------
# Create New SECR (DEF -> DEF)
# ---------------------------------------------------------------------------

def _metadata_table(metadata, sources: Dict[str, str]) -> pd.DataFrame:
    labels = {
        "harness_family": "Harness Family",
        "model_year": "Model Year",
        "phase": "Phase",
        "program": "Program",
    }
    return pd.DataFrame(
        [
            {
                "Field": label,
                "Value": getattr(metadata, name) or "—",
                "Source": sources.get(name, "not found"),
            }
            for name, label in labels.items()
        ]
    )


def _dtcr_report_input(
    prefix: str, scope: identity.SecrMetadata | None = None
) -> bytes | None:
    """The DTCR Matching Report for this SECR — from the library, or uploaded.

    When a report is already filed for the SECR's program, model year and
    phase it is used without being asked for: that is the whole point of the
    library. The uploader stays available to override it for one generation,
    which is how you try a corrected report before filing it.
    """
    st.markdown("#### DTCR Matching Report")

    filed = None
    if scope is not None:
        try:
            filed = library.find_report_for_scope(
                scope.program, scope.model_year, scope.phase
            )
        except Exception as exc:  # noqa: BLE001 - never block generation
            st.caption(f"Could not read the report library: {exc}")

    if filed:
        st.success(
            f"Using **{filed['filename']}** from the library — "
            f"MY{filed['model_year']} · {filed['program']} · {filed['phase']}, "
            f"{filed['row_count']} DTCRs.",
            icon="📚",
        )
        override = st.checkbox(
            "Use a different report just for this SECR",
            key=_k(f"{prefix}_dtcr_override"),
            help="The library is not changed. File a replacement on the "
                 "Dashboard tab.",
        )
        if not override:
            payload = library.report_bytes(int(filed["id"]))
            if payload:
                return _preview_dtcr_report(payload)
            st.warning(
                "The filed report has no stored workbook; upload one below."
            )
    else:
        st.caption(
            "Fills Reason for Change, DTCR # and Bulletin # from the report, "
            "and assigns each DTCR to the CNUM it was matched to. File one on "
            "the **Dashboard** tab and it will be used here automatically."
        )

    upload = st.file_uploader(
        "DTCR Matching Report (.xlsx / .xlsm)",
        type=["xlsx", "xlsm"],
        key=_k(f"{prefix}_dtcr_report"),
    )
    if upload is None:
        st.caption("No report — the SECR will be generated without enrichment.")
        return None
    return _preview_dtcr_report(upload.getvalue())


def _preview_dtcr_report(payload: bytes) -> bytes | None:
    """Show what the report will contribute, then hand the bytes back."""
    try:
        mapping_df = load_dtcr_matching_report(payload)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not read the DTCR Matching Report: {exc}")
        return None

    usable = mapping_df[
        mapping_df["Status"].astype(str).str.strip().isin(["Complete", "Draft"])
    ]
    cnum_map = generation.build_cnum_dtcr_map(usable)

    col1, col2, col3 = st.columns(3)
    col1.metric("DTCR rows", len(mapping_df))
    col2.metric("Complete / Draft", len(usable))
    col3.metric("CNUMs mapped", len(cnum_map))

    if cnum_map:
        with st.expander(f"DTCR ↔ CNUM assignments ({len(cnum_map)} CNUMs)"):
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "CNUM": cnum,
                            "DTCR #": ", ".join(
                                e["dtcr_number"] for e in entries
                            ),
                            "Harness Family": entries[0]["harness_family"],
                        }
                        for cnum, entries in sorted(cnum_map.items())
                    ]
                ),
                width="stretch",
                hide_index=True,
            )
        st.caption(
            "A change row that already names a DTCR in its SE comment keeps "
            "that one; the rest are assigned from this table."
        )
    else:
        st.warning(
            "No CNUMs in this report, so no DTCR can be assigned to a "
            "connector. Reason for Change, DTCR # and Bulletin # are still "
            "filled. The CNUM column is populated when the matching report is "
            "built against the OLD and NEW DTx reports."
        )
    return payload


def _show_dtcr_assignments(result) -> None:
    if not result.enriched:
        return
    st.caption(
        f"Enriched from the DTCR Matching Report · "
        f"{len(result.dtcr_assignments)} CNUM(s) assigned a DTCR across "
        f"{result.assigned_change_count} change record(s)."
    )
    if result.dtcr_assignments:
        with st.expander("DTCR assignments applied"):
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "CNUM": a.cnum,
                            "DTCR #": a.dtcr_number,
                            "Harness Family": a.harness_family,
                            "Changes": a.change_count,
                            "Source": a.source,
                        }
                        for a in result.dtcr_assignments
                    ]
                ),
                width="stretch",
                hide_index=True,
            )
    if result.enrichment_summary is not None:
        with st.expander("Enrichment summary"):
            st.dataframe(
                result.enrichment_summary, width="stretch", hide_index=True
            )


def _create_secr() -> None:
    st.markdown(
        "Build **new SECRs** from DEF-to-DEF compares. Harness Family, Model "
        "Year, Phase and Program are read from each DEF — you only choose the "
        "change type. Each SECR number is issued from the sequence for its "
        "**Model Year + Phase**, starting at 1000. Upload several compares to "
        "generate a set in one pass; they share the details you enter below."
    )

    uploads = st.file_uploader(
        "DEF-to-DEF compare file(s)",
        type=["xlsx", "xls", "xlsm"],
        accept_multiple_files=True,
        key=_k("create_def"),
    )
    if not uploads:
        st.info("Upload one or more DEF-to-DEF compare files to continue.")
        return

    change_type = st.radio(
        "Change Type",
        list(identity.CHANGE_TYPES),
        key=_k("create_change_type"),
        horizontal=True,
        help="Design Change issues a 'D' SECR number; Miscellaneous issues 'M'.",
    )

    files = [(item.name, item.getvalue()) for item in uploads]
    _forget_stale_result(
        _k("created"),
        batch.signature_for(files, change_type),
    )

    plans = batch.plan_batch(files, change_type)
    ready = [entry for entry in plans if entry.ready]
    blocked = [entry for entry in plans if not entry.ready]

    _render_batch_preview(plans, ready)
    if not ready:
        return

    scope = ready[0].metadata
    if len({(e.metadata.program, e.metadata.model_year, e.metadata.phase)
            for e in ready}) > 1:
        st.caption(
            "The compares span more than one scope; the DTCR report below is "
            "matched to the first, and each SECR still enriches from the "
            "report filed for its own scope."
        )
    mapping_bytes = _dtcr_report_input("create", scope)

    shared = _shared_secr_details("create")
    label = (
        "Generate SECR" if len(ready) == 1 else f"Generate {len(ready)} SECRs"
    )
    if st.button(label, type="primary", key=_k("create_go")):
        if st.session_state.get(_k("created")):
            st.warning(
                "These compares already produced the SECRs below. Change the "
                "uploads first — generating again would issue new numbers for "
                "the same work.",
                icon="⚠️",
            )
        else:
            progress = st.progress(0.0, text="Generating…")
            st.session_state[_k("created")] = batch.generate_batch(
                ready,
                shared,
                mapping_bytes,
                on_progress=lambda fraction, name: progress.progress(
                    fraction, text=f"Generating {name}…"
                ),
            )
            progress.empty()

    _offer_batch(_k("created"), blocked_count=len(blocked))


def _render_batch_preview(plans, ready) -> None:
    """One row per compare: what it is, what it will be called, or why not."""
    rows = []
    for entry in plans:
        metadata = entry.metadata
        rows.append({
            "File": entry.name,
            "Harness": metadata.harness_family or "—",
            "Scope": (
                f"MY{metadata.model_year_2}/{metadata.phase}"
                if entry.ready else "—"
            ),
            "Number": entry.number or "—",
            "Status": "Ready" if entry.ready else "Blocked",
        })
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    for entry in plans:
        if not entry.ready:
            st.error(f"**{entry.name}** — {'; '.join(entry.plan.problems)}")
        for warning in entry.plan.warnings:
            st.warning(f"{entry.name}: {warning}", icon="⚠️")

    if not ready:
        st.info(
            "Nothing can be generated yet. Nothing is guessed and no number is "
            "reserved until a compare carries its metadata."
        )
        return
    st.caption(
        f"{len(ready)} SECR(s) will be issued. Previewing does not reserve a "
        "number — they are issued when you press Generate."
    )


def _shared_secr_details(prefix: str) -> Dict[str, str]:
    """The fields every SECR in a batch shares, entered once.

    Deliberately not inside a ``st.form``: the "today" checkbox has to take
    effect as it is ticked, and a form would defer it until submit.
    """
    st.markdown("#### Details for every SECR")
    left, right = st.columns(2)
    with left:
        subject = st.text_area(
            "Subject / Reason for Change", height=100, key=_k(f"{prefix}_subject")
        )
        author = st.text_input("SECR Author", key=_k(f"{prefix}_author"))
        dre = st.text_input(
            "Design Release Engineer", key=_k(f"{prefix}_dre")
        )
    with right:
        crb = st.text_input("Change Requested By", key=_k(f"{prefix}_crb"))
        phase_impl = st.text_input(
            "Phase Implemented", key=_k(f"{prefix}_phase_impl")
        )
        pull_ahead = st.selectbox(
            "Pull Ahead", ["", "N", "Y"], key=_k(f"{prefix}_pull_ahead")
        )
        use_today = st.checkbox(
            "Use today's date", value=True, key=_k(f"{prefix}_today")
        )
        issue_date = st.text_input(
            "Original Issue Date (MM/DD/YYYY)",
            value=date.today().strftime("%m/%d/%Y") if use_today else "",
            disabled=use_today,
            key=_k(f"{prefix}_issue_date_today" if use_today else f"{prefix}_issue_date"),
        )
    return {
        "reason_for_change": subject,
        "secr_author": author,
        "design_release_engineer": dre,
        "change_requested_by": crb,
        "original_issue_date": issue_date,
        "phase_implemented": phase_impl,
        "pull_ahead": pull_ahead,
    }


def _offer_batch(state_key: str, blocked_count: int = 0) -> None:
    """Show what was generated, with each workbook and a zip of the set."""
    stored = st.session_state.get(state_key)
    if not stored:
        return
    results, failures = stored.results, stored.failures

    for name, error in failures:
        st.error(f"**{name}** — {error}")
    if not results:
        return

    st.success(
        f"{len(results)} SECR(s) created."
        + (f" {blocked_count} compare(s) were blocked." if blocked_count else "")
    )
    st.dataframe(
        pd.DataFrame([
            {
                "SECR": result.secr_number,
                "Ver": f"V{result.version_number}",
                "Harness": result.metadata.harness_family,
                "Changes": result.change_count,
                "File": result.filename,
            }
            for result in results
        ]),
        width="stretch",
        hide_index=True,
    )

    if len(results) > 1:
        st.download_button(
            f"Download all {len(results)} as .zip",
            data=batch.zip_results(results),
            file_name=f"SECRs_{date.today().strftime('%m%d%Y')}.zip",
            mime="application/zip",
            type="primary",
            key=f"{state_key}_zip",
        )

    for index, result in enumerate(results):
        with st.expander(
            f"{result.secr_number} — {result.metadata.harness_family} "
            f"({result.change_count} changes)"
        ):
            if result.warnings:
                for warning in result.warnings:
                    st.write(f"- {warning}")
            _show_dtcr_assignments(result)
            st.download_button(
                "Download SECR (.xlsx)",
                data=result.secr_bytes,
                file_name=result.filename,
                mime=(
                    "application/vnd.openxmlformats-officedocument"
                    ".spreadsheetml.sheet"
                ),
                key=f"{state_key}_download_{index}",
            )




def _forget_stale_result(state_key: str, signature: str) -> None:
    """Drop a previous result once the inputs it came from have changed.

    Without this the success panel — and its download button — survive a new
    upload, so uploading a second DEF looks like the app did nothing and the
    file offered is still the previous SECR's. Reported from the field as
    "not updating when uploading a new def to def", after which pressing
    Generate again issued 1005, 1006, 1007 for one compare.
    """
    marker = f"{state_key}_signature"
    if st.session_state.get(marker) != signature:
        st.session_state.pop(state_key, None)
        st.session_state[marker] = signature


def _offer_generated(state_key: str, headline: str) -> None:
    result = st.session_state.get(state_key)
    if result is None:
        return
    st.success(
        f"{headline}: **{result.secr_number}** V{result.version_number} — "
        f"{result.change_count} change record(s) stored as #{result.secr_id}."
    )
    st.caption(f"Identity: {result.identity} · file `{result.filename}`")
    if result.warnings:
        with st.expander(f"{len(result.warnings)} data-quality note(s)"):
            for warning in result.warnings:
                st.write(f"- {warning}")
    _show_dtcr_assignments(result)
    st.download_button(
        "Download SECR (.xlsx)",
        data=result.secr_bytes,
        file_name=result.filename,
        mime=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        key=f"{state_key}_download",
    )


# ---------------------------------------------------------------------------
# Update Existing SECR (existing SECR + new DEF -> DEF)
# ---------------------------------------------------------------------------

def _update_secr() -> None:
    st.markdown(
        "Revise a SECR that was **generated here** against a new DEF-to-DEF "
        "compare. The SECR number stays the same and the version advances. "
        "Imported SECRs are not renumbered or renamed, so they are not listed."
    )

    try:
        candidates = secr_db.list_generated_secrs()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not read the SECR database: {exc}")
        return

    if not candidates:
        st.info(
            "No generated SECRs yet. Create one in the **Create SECR** tab first."
        )
        return

    labels = {
        f"MY{r['scope_model_year']} / {r['scope_phase']} / "
        f"{r['secr_sequence_number']} · {r['secr_number']} "
        f"(current V{r['version_number']})": r["id"]
        for r in candidates
    }
    picked = st.selectbox("SECR to update", list(labels), key=_k("update_pick"))
    secr_id = labels[picked]
    record = secr_db.get_secr(secr_id)
    if record is None:
        st.warning("That SECR is no longer in the database.")
        return

    st.caption(
        f"Current version V{record.get('version_number')} · "
        f"`{record.get('filename')}`"
    )

    upload = st.file_uploader(
        "New DEF-to-DEF compare file",
        type=["xlsx", "xls", "xlsm"],
        key=_k("update_def"),
    )
    if upload is None:
        st.info("Upload the new DEF-to-DEF compare file to continue.")
        return

    def_bytes = upload.getvalue()
    try:
        plan = generation.plan_secr_update(secr_id, def_bytes, upload.name)
    except SpliceError as exc:
        st.error(str(exc))
        return
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not read the DEF compare file: {exc}")
        return

    st.markdown("#### Metadata validation")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Field": difference.label,
                    "Existing": difference.existing or "—",
                    "New Input": difference.new or "—",
                    "": "← changed" if difference.changed else "",
                }
                for difference in plan.differences
            ]
        ),
        width="stretch",
        hide_index=True,
    )
    for note in plan.notes:
        st.caption(f"ℹ️ {note}")

    if plan.problems:
        st.error("**Metadata incomplete — the update is blocked**")
        for problem in plan.problems:
            st.write(f"- {problem}")
        return

    for warning in plan.warnings:
        st.warning(warning, icon="⚠️")

    if plan.scope_changed:
        changed = ", ".join(
            f"{d.label} {d.existing} → {d.new}" for d in plan.changed
        )
        st.error(
            f"**SECR scope changed** — {changed}.\n\n"
            f"Existing SECR: {plan.identity}. A change of Harness Family, Model "
            "Year, Phase or Program normally requires a **new SECR**, because "
            "the number belongs to its Model Year + Phase scope. This update is "
            "blocked."
        )
        st.info(
            "Take this DEF to the **Create SECR** tab. It will be issued the "
            "next number in its own scope, starting at "
            f"{identity.FIRST_SEQUENCE_NUMBER} if that scope has never been used."
        )
        return

    st.success("Metadata validation: **PASSED**")
    col1, col2 = st.columns(2)
    col1.metric("Current Version", f"V{plan.current_version}")
    col2.metric("Proposed Version", f"V{plan.next_version}")
    st.code(plan.filename, language=None)

    stored = secr_db.get_source_file(secr_id)
    if not stored or not stored.get("content"):
        st.error(
            "The original workbook for this SECR is not stored, so the update "
            "engine has no baseline to carry comments forward from. Re-import "
            "or re-generate it with source storage enabled."
        )
        return

    update_mapping_bytes = _dtcr_report_input("update", plan.existing_metadata)

    with st.form(_k("update_form")):
        left, right = st.columns(2)
        with left:
            subject = st.text_area(
                "Subject / Reason for Change", height=100, key=_k("update_subject")
            )
            author = st.text_input("SECR Author", key=_k("update_author"))
            dre = st.text_input("Design Release Engineer", key=_k("update_dre"))
        with right:
            crb = st.text_input("Change Requested By", key=_k("update_crb"))
            phase_impl = st.text_input(
                "Phase Implemented", key=_k("update_phase_impl")
            )
            pull_ahead = st.selectbox(
                "Pull Ahead", ["", "N", "Y"], key=_k("update_pull_ahead")
            )
            reissue = st.text_input(
                "ReIssue Date (MM/DD/YYYY)", key=_k("update_reissue")
            )
        submitted = st.form_submit_button(
            f"Generate V{plan.next_version}", type="primary"
        )

    if submitted:
        try:
            result = generation.generate_secr_update(
                def_bytes,
                upload.name,
                stored["content"],
                plan,
                subject=subject,
                secr_author=author,
                design_release_engineer=dre,
                change_requested_by=crb,
                reissue_date=reissue,
                phase_implemented=phase_impl,
                pull_ahead=pull_ahead,
                dtcr_matching_bytes=update_mapping_bytes,
            )
        except generation.SecrScopeChanged as exc:
            st.error(str(exc))
            return
        except SpliceError as exc:
            st.error(f"Could not generate the update: {exc}")
            return
        except Exception as exc:  # noqa: BLE001
            st.error(f"Unexpected error while generating the update: {exc}")
            return
        st.session_state[_k("updated")] = result

    _offer_generated(_k("updated"), "New version created")

    versions = secr_db.get_versions(
        plan.identity.model_year,
        plan.identity.phase,
        plan.identity.sequence_number,
    )
    if len(versions) > 1:
        with st.expander(f"Version history ({len(versions)} versions)"):
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Version": f"V{v['version_number']}",
                            "Generated": v.get("generation_date") or "",
                            "Filename": v.get("filename") or "",
                            "Changes": v.get("change_count", 0),
                        }
                        for v in versions
                    ]
                ),
                width="stretch",
                hide_index=True,
            )


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def _import() -> None:
    st.markdown(
        "Drop one or more **SECR workbooks** here. Each file is parsed, "
        "validated and inserted with its change records. Nothing is imported "
        "twice, and nothing is discarded silently — every file appears in the "
        "report below."
    )

    uploads = st.file_uploader(
        "Drop SECR files here (.xlsx / .xlsm)",
        type=["xlsx", "xlsm"],
        accept_multiple_files=True,
        key=_k("uploads"),
    )

    col1, col2 = st.columns(2)
    policy_label = col1.radio(
        "If a SECR is already in the database",
        ["Skip (keep the stored record)", "Replace the stored record"],
        key=_k("policy"),
        help=(
            "Skip is the safe default: an import can never overwrite "
            "engineering history that is already recorded."
        ),
    )
    store_source = col2.checkbox(
        "Keep a copy of each original file in the database",
        value=True,
        key=_k("store_source"),
        help=(
            "Preserves traceability from the record back to the workbook it "
            "came from. Adds roughly the file's own size to the database."
        ),
    )
    on_conflict = (
        secr_db.CONFLICT_SKIP
        if policy_label.startswith("Skip")
        else secr_db.CONFLICT_REPLACE
    )

    if not uploads:
        st.info("No files selected yet.")
        _show_last_summary()
        return

    if st.button(
        f"Import {len(uploads)} file(s)", type="primary", key=_k("run_import")
    ):
        files = [(upload.name, upload.getvalue()) for upload in uploads]
        progress = st.progress(0.0, text="Starting import…")

        def _on_progress(done: int, total: int, filename: str) -> None:
            progress.progress(done / total, text=f"{done}/{total} · {filename}")

        try:
            summary = import_secr_files(
                files, on_conflict=on_conflict, store_source=store_source,
                progress=_on_progress,
            )
        except Exception as exc:  # noqa: BLE001
            progress.empty()
            st.error(f"The import could not run: {exc}")
            return
        progress.empty()
        st.session_state[_k("last_summary")] = summary

    _show_last_summary()


def _show_last_summary() -> None:
    summary = st.session_state.get(_k("last_summary"))
    if summary is None:
        return

    st.success(f"Import complete — {summary.headline()}")
    counts = summary.counts()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Imported", counts["imported"])
    col2.metric("Replaced", counts["replaced"])
    col3.metric("Already existed", counts["duplicate"])
    col4.metric("Failed", counts["failed"])
    st.caption(f"{summary.total_changes} change record(s) stored.")

    if summary.failed:
        st.error(f"{len(summary.failed)} file(s) could not be imported.")
        st.dataframe(
            pd.DataFrame(
                [
                    {"File": r.filename, "Reason": r.message}
                    for r in summary.failed
                ]
            ),
            width="stretch",
            hide_index=True,
        )

    if summary.duplicates:
        with st.expander(
            f"{len(summary.duplicates)} file(s) were already in the database"
        ):
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "File": r.filename,
                            "SECR": r.secr_number,
                            "Version": r.version,
                            "Detail": r.message,
                        }
                        for r in summary.duplicates
                    ]
                ),
                width="stretch",
                hide_index=True,
            )

    if summary.with_warnings:
        with st.expander(
            f"{len(summary.with_warnings)} file(s) imported with data-quality notes"
        ):
            for result in summary.with_warnings:
                st.markdown(f"**{result.filename}** — {result.secr_number}")
                for warning in result.warnings:
                    st.write(f"- {warning}")

    ok = summary.imported + summary.replaced
    if ok:
        with st.expander(f"{len(ok)} file(s) imported successfully"):
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "File": r.filename,
                            "SECR": r.secr_number,
                            "Version": r.version,
                            "Changes": r.change_count,
                        }
                        for r in ok
                    ]
                ),
                width="stretch",
                hide_index=True,
            )


# ---------------------------------------------------------------------------
# DTCR Matching Report library and dashboard
# ---------------------------------------------------------------------------

def _as_bars(rows: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    """Adapt the library's ``{<key>: …, "count": n}`` rows to the chart shape."""
    return [{"name": row[key], "n": row["count"]} for row in rows]


def _scope_label(report: Dict[str, Any]) -> str:
    return (
        f"MY{report['model_year']} · {report['program']} · {report['phase']}"
        f"  ({report['row_count']} DTCRs)"
    )


def _dashboard() -> None:
    """The DTCR Matching Report library, and the report you pick, in charts."""
    try:
        reports = library.list_reports()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not read the report library: {exc}")
        return

    _report_uploader(reports)

    if not reports:
        st.info(
            "No DTCR Matching Report has been filed yet. Upload one above and "
            "it will be reused by every SECR you create in its program, model "
            "year and phase."
        )
        return

    labels = {_scope_label(report): report for report in reports}
    chosen = st.selectbox(
        "Report",
        list(labels),
        key=_k("dash_report"),
        help="Reports are filed one per program + model year + phase.",
    )
    report = labels[chosen]
    stats = library.report_statistics(int(report["id"]))
    if not stats.total:
        st.warning("This report has no DTCR rows.")
        return

    _report_header(report, stats)
    st.divider()
    _report_charts(stats)


def _report_header(report: Dict[str, Any], stats) -> None:
    """The five numbers that describe a report, then its status breakdown."""
    columns = st.columns(5)
    columns[0].metric("DTCRs", f"{stats.total:,}")
    columns[1].metric("Harness families", f"{len(stats.by_harness_family):,}")
    columns[2].metric(
        "With a CNUM",
        f"{stats.with_cnum:,}",
        delta=f"{stats.cnum_rate:.0f}% of the report",
        delta_color="off",
    )
    columns[3].metric("With a bulletin", f"{stats.with_bulletin:,}")
    columns[4].metric(
        "No harness family",
        f"{stats.unmatched:,}",
        delta="needs attention" if stats.unmatched else "all assigned",
        delta_color="inverse" if stats.unmatched else "off",
    )

    # 75 / 1 / 1 is not a chart — one bar would fill the axis and the two that
    # matter would be invisible. Counts read directly.
    palette = _STATUS_COLORS["dark" if _colors() is _PALETTE["dark"] else "light"]
    chips = " &nbsp;·&nbsp; ".join(
        f"<span style='color:{palette[_STATUS_KIND.get(str(row['status']).upper(), 'neutral')]}'>"
        f"●</span> <b>{row['count']}</b> {row['status']}"
        for row in stats.by_status
    )
    st.markdown(
        f"<div style='margin-top:.5rem'>Status: {chips}</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        f"{report['filename']} · uploaded {report['uploaded_at']}"
        + (f" by {report['uploaded_by']}" if report["uploaded_by"] else "")
    )


def _report_charts(stats) -> None:
    """Where the work lands, how it was matched, and what is still open."""
    left, right = st.columns([3, 2])

    with left:
        st.markdown("**DTCRs per harness family**")
        st.caption(
            f"{stats.multi_family} of {stats.total} DTCRs name more than one "
            "family, so the bars sum to more than the DTCR count."
            if stats.multi_family
            else "Each DTCR names one harness family."
        )
        _bar_chart(
            _as_bars(stats.by_harness_family[:15], "harness_family"),
            label="Harness family",
        )

    with right:
        st.markdown("**How each DTCR was matched**")
        st.caption("How the harness family was determined — a data-quality view.")
        _bar_chart(
            _as_bars(stats.by_match_method, "match_method"), label="Match method"
        )

    lower_left, lower_right = st.columns([3, 2])
    with lower_left:
        st.markdown("**DTCRs per bulletin**")
        if stats.by_bulletin:
            st.caption(
                f"{stats.with_bulletin} of {stats.total} DTCRs cite a bulletin."
            )
            _bar_chart(_as_bars(stats.by_bulletin, "bulletin"), label="Bulletin")
        else:
            st.caption("No bulletin is cited in this report.")

    with lower_right:
        st.markdown("**Unassigned DTCRs**")
        if stats.unmatched_rows:
            st.caption(
                "No harness family, so no SECR will pick these up. Resolve them "
                "in SECR Management → DTCR Matching and re-upload."
            )
            st.dataframe(
                pd.DataFrame(stats.unmatched_rows)[
                    ["dtcr_number", "status", "match_method", "device_transmittal"]
                ].rename(
                    columns={
                        "dtcr_number": "DTCR",
                        "status": "Status",
                        "match_method": "Match Method",
                        "device_transmittal": "Device Transmittal",
                    }
                ),
                width="stretch",
                hide_index=True,
                height=220,
            )
        else:
            st.success("Every DTCR in this report has a harness family.", icon="✅")

    with st.expander("All rows in this report"):
        rows = library.report_rows(int(stats.report["id"]))
        st.dataframe(pd.DataFrame(rows).drop(columns=["id", "report_id"]),
                     width="stretch", hide_index=True)


def _report_uploader(reports: List[Dict[str, Any]]) -> None:
    """File a report against a scope, so no SECR has to carry it again."""
    with st.expander(
        "⬆ Upload a DTCR Matching Report", expanded=not reports
    ):
        st.caption(
            "Filed by **program + model year + phase**. Every SECR created in "
            "that scope enriches from it automatically — no need to attach the "
            "file each time. Re-uploading a scope replaces its report."
        )
        upload = st.file_uploader(
            "DTCR Matching Report (.xlsx / .xlsm)",
            type=["xlsx", "xlsm"],
            key=_k("library_upload"),
        )
        if upload is None:
            return

        # The filename usually carries the scope (…_<program>_<oldrev>_vs_<newrev>…); offer it
        # rather than making the engineer retype what is already written down.
        guess = library.parse_scope_from_filename(upload.name)
        left, middle, right = st.columns(3)
        program = left.text_input(
            "Program", value=guess.program, key=_k("library_program")
        )
        model_year = middle.text_input(
            "Model Year", value=guess.model_year, key=_k("library_my"),
            help="Two or four digits; stored as two.",
        )
        phase = right.text_input(
            "Phase", value=guess.phase, key=_k("library_phase")
        )
        if guess.is_complete:
            st.caption(
                f"Read from the filename: **{guess}**. A report built from a "
                "phase compare is filed under the *later* phase — change it "
                "here if that is not what you intend."
            )

        existing = library.find_report_for_scope(program, model_year, phase)
        if existing:
            st.warning(
                f"**{existing['filename']}** is already filed for this scope "
                f"({existing['row_count']} DTCRs, uploaded "
                f"{existing['uploaded_at']}). Saving replaces it.",
                icon="⚠️",
            )

        if st.button("Save to the library", type="primary", key=_k("library_save")):
            try:
                library.save_report(
                    upload.getvalue(),
                    upload.name,
                    program=program,
                    model_year=model_year,
                    phase=phase,
                )
            except SpliceError as exc:
                st.error(str(exc))
                return
            except Exception as exc:  # noqa: BLE001
                st.error(f"Could not store the report: {exc}")
                return
            st.success(f"Filed for MY{model_year} · {program} · {phase}.")
            st.rerun()


render()
