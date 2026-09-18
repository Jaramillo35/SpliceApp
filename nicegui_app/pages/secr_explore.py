"""SECR Database · Browse — a data explorer over every stored SECR.

The old tab was one search box over a flat table whose rows could not be
opened. An engineer asking "which connectors changed, under which DTCRs,
landing on which CNUMs, for which harness families" had to open workbooks.

Three regions, top to bottom:

* **Scope.** One contains-search over everything stored for a SECR, and a
  row of toggle chips per facet — model year, program, phase, harness
  family, change type, origin — each with its SECR count. A facet with one
  value is a fact, not a choice, and is said in a line of text. Facets combine,
  and each is counted under every filter but its own, so choosing MY2028
  narrows the programs and phases yet keeps the other years one click away.
* **Results beside a preview.** A result says what it is (number, version,
  subject, scope, change count) and, when searching, *why it matched*:
  place counts and the snippets with the term marked. A snippet is a button
  that opens the preview on the object that matched.
* **Three lenses on the same changes.** By type — a paginated table, old
  value grey and new value blue, because a SECR can hold 400 changes; by
  DTCR — what each DTCR changed and why; by CNUM — everything landing on a
  connector. "Find in this SECR" filters every lens, and whatever is in it
  can be promoted to a search across all SECRs. Every DTCR and CNUM is a
  button that does exactly that.

No business value is computed here: the three calls in
``secrdb.core.secr.api`` (scope_facets, search_documents, preview_secr)
return everything shown. They are read-only and run off the event loop
through a quiet runner — ``components.run_engine`` toasts and writes an
activity-feed line per call, which is right for a run and wrong for a
keystroke.
"""

from __future__ import annotations

import html
import re

from nicegui import run, ui

from nicegui_app import components as c
from nicegui_app import theme
from secrdb.core.secr import api
from secrdb.core.secr import db as secr_db

FACETS = (("model_year", "Model year"), ("program", "Program"), ("phase", "Phase"),
          ("harness_family", "Harness family"), ("change_type", "Change type"),
          ("import_origin", "Origin"))
PLACE_WORD = {"header": "header", "change": "change", "dtcr": "DTCR matching",
              "affected item": "affected item", "file": "file name"}
LENSES = (("type", "By type"), ("dtcr", "By DTCR"), ("cnum", "By CNUM"),
          ("details", "Details"))
LIST_CAP = 200     # SECRs listed; the API's own default
LENS_CAP = 100     # DTCR / CNUM rows drawn before asking for a narrower find

CHANGE_LABELS = {"object": "Object", "action": "Action", "field": "Field",
                 "old": "Old", "new": "New", "dtcrs": "DTCRs", "cnums": "CNUMs",
                 "ends": "Ends", "comment": "SE comment"}
DETAIL_LABELS = (("filename", "File"), ("source_def_filename", "DEF-to-DEF source"),
                 ("change_type", "Change type"), ("dtcr_numbers", "DTCRs in header"),
                 ("bulletin_numbers", "Bulletins"), ("ref_secr", "Reference SECR"),
                 ("secr_author", "Author"), ("design_release_engineer", "DRE"),
                 ("old_def_source", "Old DEF"), ("new_def_source", "New DEF"),
                 ("original_issue_date", "Issued"), ("reissue_date", "Reissued"),
                 ("import_origin", "Origin"))
#: the app's colour language for a change: grey is what it was, blue what it is
OLD_INK = theme.TEXT_2
NEW_INK = theme.STATUS_TEXT["info"]


def plural(n: int, word: str, many: str = "") -> str:
    """``2 changes``, ``1 SECR``, ``2 matches`` — pass ``many`` when adding an
    's' is not the plural."""
    return f"{n:,} {word if n == 1 else (many or word + 's')}"


def marked(snippet: str, term: str) -> str:
    """The snippet as safe HTML with the search term marked.

    The text is stored data, so it is escaped first; the only markup in the
    result is the ``<mark>`` added here.
    """
    safe = html.escape(snippet or "")
    needle = html.escape((term or "").strip())
    if not needle:
        return safe
    style = (f"background:{theme.wash(theme.BRAND, '66')};color:{theme.TEXT};"
             "border-radius:2px;padding:0 1px")
    return re.sub(re.escape(needle),
                  lambda m: f'<mark style="{style}">{m.group(0)}</mark>',
                  safe, flags=re.IGNORECASE)


def scope_of(row: dict) -> str:
    families = row.get("harness_families") or []
    parts = [f"MY{row['model_year']}" if row.get("model_year") else "",
             row.get("program") or "", row.get("phase") or "",
             ", ".join(families)]
    return " · ".join(p for p in parts if p)


def matches(find: str, *values) -> bool:
    needle = (find or "").strip().lower()
    if not needle:
        return True
    for value in values:
        items = value if isinstance(value, (list, tuple)) else [value]
        if any(needle in str(item or "").lower() for item in items):
            return True
    return False


def build() -> None:
    state: dict = {"text": "", "filters": {}, "facets": None, "rows": [],
                   "error": "", "loaded": False, "selected": None,
                   "preview": None, "lens": "type", "find": ""}
    views: dict = {}

    # ------------------------------------------------------------ queries
    async def ask(fn, *args, **kwargs):
        """Read-only, off the event loop, silent on success."""
        try:
            state["error"] = ""
            return await run.io_bound(fn, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — the DB may be absent or locked; the tab says so
            state["error"] = str(exc)
            return None

    async def load() -> None:
        filters = dict(state["filters"])
        facets = await ask(api.scope_facets, **filters)
        rows = await ask(api.search_documents, state["text"], limit=LIST_CAP, **filters) \
            if facets is not None else None
        state.update(facets=facets, rows=rows or [], loaded=True)
        if state["selected"] not in {r["id"] for r in state["rows"]}:
            state.update(selected=None, preview=None)
        for name in ("scope", "list", "preview"):
            views[name].refresh()

    async def open_secr(secr_id: int, find: str = "") -> None:
        preview = await ask(api.preview_secr, secr_id)
        state.update(selected=secr_id, preview=preview, find=find, lens="type")
        views["list"].refresh()
        views["preview"].refresh()

    async def search_for(term: str) -> None:
        """Promote an identifier to a search across every SECR."""
        state["text"] = term
        box.value = term
        await load()

    async def toggle(key: str, name: str) -> None:
        if state["filters"].get(key) == name:
            state["filters"].pop(key)
        else:
            state["filters"][key] = name
        await load()

    async def clear_scope() -> None:
        state.update(filters={}, text="")
        box.value = ""
        await load()

    def set_lens(key: str) -> None:
        state["lens"] = key
        views["preview"].refresh()

    def set_find(value: str) -> None:
        state["find"] = value or ""
        views["lens"].refresh()

    # -------------------------------------------------------------- scope
    with c.card("Explore the SECRs",
                "Finds the text anywhere in a SECR — header, every change, DTCR "
                "matching, affected items, file names. Narrow with the chips; "
                "they combine."):
        with ui.row().classes("w-full items-end gap-2 no-wrap"):
            box = ui.input("Search", placeholder="a circuit, CNUM, DTCR, part number, "
                                                 "sales code, a word from a comment…") \
                .classes("flex-1").props("clearable dense")
            ui.button("Search", icon="search", on_click=lambda: run_search()) \
                .props("unelevated dense no-caps")

        async def run_search() -> None:
            state["text"] = (box.value or "").strip()
            await load()

        box.on("keydown.enter", lambda: run_search())
        box.on("clear", lambda: run_search())

        @ui.refreshable
        def scope_view() -> None:
            if state["error"]:
                c.note("blocker", f"The database could not be read: {state['error']}")
                return
            facets = state["facets"]
            if facets is None:
                return
            totals = facets["totals"]
            active = bool(state["filters"] or state["text"])
            with ui.row().classes("w-full items-center gap-3 flex-wrap"):
                ui.label(f"{plural(totals['secrs'], 'SECR')} · "
                         f"{plural(totals['changes'], 'change')}"
                         + (" in this scope" if active else "")) \
                    .classes("text-sm font-semibold")
                if active:
                    ui.button("Clear search and filters", icon="filter_alt_off",
                              on_click=lambda: clear_scope()).props("flat dense no-caps")
            # A facet with one value is a fact, not a choice: it is said in a
            # line of text. It stays a chip only while it is the filter, so
            # it can be taken off again.
            constant = [f"{label} {values[0]['name']}" for key, label in FACETS
                        for values in [facets.get(key) or []]
                        if len(values) == 1 and not values[0]["selected"]]
            if constant:
                ui.label("Every SECR here: " + " · ".join(constant)).classes("sx-caption")
            for key, label in FACETS:
                values = facets.get(key) or []
                if not values or (len(values) == 1 and not values[0]["selected"]):
                    continue
                with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                    ui.label(label).classes("sx-eyebrow w-28 shrink-0")
                    for value in values:
                        name = value["name"]
                        c.toggle_chip(str(name) or "—", bool(value["selected"]),
                                      lambda k=key, n=name: toggle(k, n),
                                      value["secrs"])

        views["scope"] = scope_view
        scope_view()

    # ---------------------------------------------------- results | preview
    with ui.splitter(value=38).classes("w-full") as split:
        with split.before:
            with ui.column().classes("w-full gap-2 pr-3"):
                @ui.refreshable
                def list_view() -> None:
                    rows = state["rows"]
                    if not state["loaded"] or state["error"]:
                        return
                    if not rows:
                        c.empty(f"No SECR contains “{state['text']}” in this scope — "
                                "clear the search or a filter." if state["text"]
                                else "No SECRs here yet — import SECR files in the "
                                     "Import tab, or create one.",
                                icon="search_off")
                        return
                    ui.label(("Matches" if state["text"] else "SECRs")
                             + f" · {len(rows)}"
                             + (f" (first {LIST_CAP})" if len(rows) >= LIST_CAP else "")) \
                        .classes("sx-eyebrow")
                    with ui.column().classes("w-full gap-2 max-h-[44rem] overflow-y-auto"):
                        for row in rows:
                            _result(row)

                views["list"] = list_view
                list_view()
        with split.after:
            with ui.column().classes("w-full gap-3 pl-3"):
                @ui.refreshable
                def preview_view() -> None:
                    p = state["preview"]
                    if p is None:
                        c.empty("Select a SECR to see what it changed — by type, by "
                                "DTCR and by CNUM.", icon="fact_check")
                        return
                    _preview(p)

                views["preview"] = preview_view
                preview_view()

    def _result(row: dict) -> None:
        active = state["selected"] == row["id"]
        with ui.column().classes("w-full gap-1 rounded p-1") \
                .style(f"background:{theme.wash(theme.BRAND) if active else theme.SURFACE_2};"
                       f"border:1px solid {theme.LINE}"):
            head = ui.button(on_click=lambda _e, i=row["id"]: open_secr(i)) \
                .props(f'flat no-caps align=left aria-pressed="{"true" if active else "false"}"') \
                .classes("w-full normal-case px-2 py-1").mark(f"result-{row['secr_number']}")
            with head:
                with ui.column().classes("w-full gap-0 items-start min-w-0"):
                    with ui.row().classes("w-full items-baseline gap-2 no-wrap"):
                        ui.label(row["secr_number"]).classes("text-sm font-semibold sx-mono") \
                            .style(f"color:{theme.TEXT}")
                        ui.label(f"v{row.get('version') or '?'}").classes("text-xs sx-muted")
                        ui.element("div").classes("grow")
                        ui.label(plural(int(row.get("change_count") or 0), "change")) \
                            .classes("text-xs sx-muted shrink-0")
                    if row.get("subject"):
                        ui.label(row["subject"]).classes("text-xs truncate w-full text-left") \
                            .style(f"color:{theme.TEXT}")
                    ui.label(scope_of(row)).classes("text-xs sx-muted truncate w-full text-left")
            if row.get("hits"):
                places = " · ".join(f"{n} {PLACE_WORD.get(place, place)}"
                                    for place, n in row["hits_by_place"].items() if n)
                ui.label(f"{plural(row['hit_count'], 'match', 'matches')} — {places}") \
                    .classes("text-xs px-2").style(f"color:{theme.BRAND}")
                for n, hit in enumerate(row["hits"]):
                    target = hit.get("object_id") or ""
                    button = ui.button(
                        on_click=lambda _e, i=row["id"], t=target: open_secr(i, t)) \
                        .props("flat dense no-caps align=left") \
                        .classes("w-full normal-case px-2").mark(f"hit-{row['secr_number']}-{n}")
                    with button:
                        with ui.column().classes("w-full gap-0 items-start min-w-0"):
                            ui.label(hit.get("label") or hit.get("where") or "") \
                                .classes("text-xs sx-muted")
                            ui.html(marked(hit.get("snippet", ""), state["text"]),
                                    sanitize=False) \
                                .classes("text-xs sx-mono text-left break-all")
                if row.get("more_hits"):
                    ui.label(f"+{row['more_hits']} more in this SECR — open it and use "
                             "Find.").classes("sx-caption px-2")

    # ------------------------------------------------------------ preview
    def _preview(p: dict) -> None:
        header, scope, totals = p["header"], p["scope"], p["totals"]
        with ui.row().classes("w-full items-baseline gap-2 flex-wrap"):
            ui.label(header["secr_number"]).classes("sx-title sx-mono")
            ui.label(f"v{header.get('version') or '?'}").classes("text-sm sx-muted")
        if header.get("subject"):
            ui.label(header["subject"]).classes("text-sm -mt-2")
        with ui.row().classes("items-center gap-2 flex-wrap"):
            if scope.get("model_year"):
                c.chip("info", f"MY{scope['model_year']}")
            for value in (scope.get("program"), scope.get("phase")):
                if value:
                    c.chip("info", str(value))
            for family in scope.get("harness_families") or []:
                c.chip("ok", family)
        with c.kpi_strip():
            c.kpi(int(totals["changes"]), "Changes")
            c.kpi(int(totals["dtcrs"]), "DTCRs")
            c.kpi(int(totals["cnums"]), "CNUMs")
        actions = " · ".join(f"{name} {n}" for name, n in (totals.get("by_action") or {}).items() if n)
        if actions:
            ui.label(f"By action: {actions}").classes("sx-caption sx-mono")
        for warning in p.get("warnings") or []:
            c.note("review", str(warning))

        with ui.row().classes("w-full items-end gap-2 flex-wrap"):
            find = ui.input("Find in this SECR", value=state["find"],
                            placeholder="an object, DTCR, CNUM, value…") \
                .props("clearable dense").classes("grow min-w-[14rem]")
            find.on_value_change(lambda e: set_find(e.value))
            ui.button("Search all SECRs for it", icon="travel_explore",
                      on_click=lambda: search_for((find.value or "").strip())) \
                .props("outline dense no-caps") \
                .bind_enabled_from(find, "value", backward=lambda v: bool((v or "").strip()))
            if p.get("source_file"):
                c.download(p["source_file"]["filename"],
                           lambda i=state["selected"]: _source_bytes(i), dress=False)
        with ui.row().classes("items-center gap-2 flex-wrap"):
            ui.label("View").classes("sx-eyebrow")
            for key, label in LENSES:
                c.toggle_chip(label, state["lens"] == key, lambda k=key: set_lens(k))

        @ui.refreshable
        def lens_view() -> None:
            {"type": _by_type, "dtcr": _by_dtcr, "cnum": _by_cnum,
             "details": _details}[state["lens"]](p)

        views["lens"] = lens_view
        lens_view()

    def _source_bytes(secr_id: int) -> bytes:
        stored = secr_db.get_source_file(secr_id)
        return bytes(stored["content"]) if stored else b""

    def _by_type(p: dict) -> None:
        find = state["find"]
        shown = 0
        for group in p["groups"]:
            rows = []
            for obj in group["objects"]:
                for change in obj["changes"]:
                    ends = "; ".join(f"{e.get('role')}: {e.get('cnum')}/{e.get('cavity') or '?'}"
                                     for e in change.get("endpoints") or [])
                    record = {"object": obj["object_id"], "action": change["action"],
                              "field": change.get("field") or "",
                              "old": change.get("old_value") or "",
                              "new": change.get("new_value") or "",
                              "dtcrs": ", ".join(change.get("dtcrs") or obj.get("dtcrs") or []),
                              "cnums": ", ".join(obj.get("cnums") or []),
                              "ends": ends, "comment": change.get("se_comment") or ""}
                    if matches(find, *record.values()):
                        rows.append(record)
            if not rows:
                continue
            shown += len(rows)
            objects = len({r["object"] for r in rows})
            ui.label(f"{group['label']} · {plural(objects, 'object')} · "
                     f"{plural(len(rows), 'change')}").classes("text-sm font-semibold mt-1")
            columns = [k for k in CHANGE_LABELS if any(r[k] for r in rows)]
            table = c.frame_table(rows, columns=columns, labels=CHANGE_LABELS,
                                  pagination=25, mono=("object", "old", "new", "dtcrs",
                                                       "cnums", "ends"))
            for field, ink in (("old", OLD_INK), ("new", NEW_INK)):
                if field in columns:
                    table.add_slot(f"body-cell-{field}",
                                   f'<q-td :props="props"><span style="color:{ink}">'
                                   "{{ props.value }}</span></q-td>")
        if not shown:
            c.empty(f"Nothing in this SECR contains “{find}”." if find
                    else "This SECR holds no change rows.", icon="filter_alt")

    def _identifier(text: str, what: str) -> None:
        ui.button(text, on_click=lambda _e, t=text: search_for(t)) \
            .props("flat dense no-caps").classes("sx-mono font-semibold px-1") \
            .tooltip(f"Search all SECRs for this {what}")

    def _row_box():
        return ui.column().classes("w-full gap-1 rounded px-3 py-2") \
            .style(f"background:{theme.SURFACE_2};border:1px solid {theme.LINE}")

    def _list_line(word: str, items: list) -> None:
        if items:
            shown = ", ".join(str(i) for i in items[:12])
            more = f" +{len(items) - 12}" if len(items) > 12 else ""
            with ui.row().classes("items-baseline gap-2 no-wrap w-full"):
                ui.label(word).classes("text-xs sx-muted w-24 shrink-0")
                ui.label(shown + more).classes("text-xs sx-mono break-all")

    def _by_dtcr(p: dict) -> None:
        find = state["find"]
        rows = [d for d in p["dtcrs"]
                if matches(find, d["dtcr_number"], d.get("reason_for_change"),
                           d.get("connectors"), d.get("circuits"), d.get("other"),
                           d.get("cnums"))]
        if not rows:
            c.empty(f"No DTCR here matches “{find}”." if find
                    else "This SECR names no DTCR.", icon="filter_alt")
            return
        ui.label(f"{plural(len(rows), 'DTCR')} — what each one changed, and why") \
            .classes("text-sm font-semibold mt-1")
        for d in rows[:LENS_CAP]:
            with _row_box():
                with ui.row().classes("items-center gap-2 flex-wrap w-full"):
                    _identifier(d["dtcr_number"], "DTCR")
                    ui.label(plural(int(d["change_count"]), "change")).classes("text-xs sx-muted")
                    if not d["change_count"]:
                        c.chip("review", "named in the header only")
                    elif d.get("in_matching_report"):
                        c.chip("ok", "in the DTCR matching report")
                    for family in d.get("harness_families") or []:
                        c.chip("info", family)
                if d.get("reason_for_change"):
                    ui.label(d["reason_for_change"]).classes("text-sm")
                _list_line("Connectors", d.get("connectors") or [])
                _list_line("Circuits", d.get("circuits") or [])
                _list_line("Other", d.get("other") or [])
                _list_line("CNUMs", d.get("cnums") or [])
        if len(rows) > LENS_CAP:
            ui.label(f"Showing {LENS_CAP} of {len(rows)} — narrow with Find.") \
                .classes("sx-caption")

    def _by_cnum(p: dict) -> None:
        find = state["find"]
        rows = [x for x in p["cnums"]
                if matches(find, x["cnum"], x.get("circuits"), x.get("dtcrs"))]
        if not rows:
            c.empty(f"No CNUM here matches “{find}”." if find
                    else "No change in this SECR lands on a connector.", icon="filter_alt")
            return
        ui.label(f"{plural(len(rows), 'CNUM')} — everything landing on each connector, "
                 "busiest first").classes("text-sm font-semibold mt-1")
        for x in rows[:LENS_CAP]:
            with _row_box():
                with ui.row().classes("items-center gap-2 flex-wrap w-full"):
                    _identifier(x["cnum"], "CNUM")
                    ui.label(f"{plural(int(x['connector_changes']), 'connector change')} · "
                             f"{plural(int(x['circuit_changes']), 'circuit change')}") \
                        .classes("text-xs sx-muted")
                _list_line("Circuits", x.get("circuits") or [])
                _list_line("DTCRs", x.get("dtcrs") or [])
        if len(rows) > LENS_CAP:
            ui.label(f"Showing {LENS_CAP} of {len(rows)} — narrow with Find.") \
                .classes("sx-caption")

    def _details(p: dict) -> None:
        header = p["header"]
        with ui.element("div").classes("w-full grid gap-x-4 gap-y-1 items-baseline") \
                .style("grid-template-columns: max-content 1fr"):
            for key, label in DETAIL_LABELS:
                value = header.get(key)
                if value not in (None, ""):
                    ui.label(label).classes("text-xs sx-muted")
                    ui.label(str(value)).classes("text-sm break-all")
        items = p.get("affected_items") or []
        if items:
            ui.label(f"Affected items · {len(items)}").classes("text-sm font-semibold mt-2")
            c.frame_table(items, labels={"category": "Kind", "action": "Action",
                                         "item": "Item"},
                          pagination=15, mono=("item",))
        stored = p.get("source_file")
        if stored:
            ui.label(f"Stored workbook: {stored['filename']} · "
                     f"{int(stored['size_bytes']):,} bytes · {stored.get('stored_at') or ''}") \
                .classes("sx-caption")

    ui.timer(0.05, load, once=True)
