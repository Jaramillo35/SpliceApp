"""Exploring the SECR database: preview one SECR, search every document, facet the scope.

Three read-only queries that the Browse tab is built on. They exist because
the browser could list SECRs but not open one: an engineer could not see what
a SECR changed, which DTCRs drove it, which connectors (CNUMs) and harness
families it touched, or find a SECR by a word in an SE comment.

``secr_preview``      one SECR, its changes grouped connector / circuit / part
                      number / harness, and the same changes rolled up by DTCR,
                      by CNUM and by harness family.
``search_documents``  a *contains* search over every text the database holds
                      for a SECR — header, file names, every change column,
                      DTCR rows, affected items — returning per SECR where it
                      hit and a snippet, so a result explains itself.
``scope_facets``      model years, programs, phases, harness families, change
                      types and origins with SECR counts, under the current
                      filters; a facet never filters itself, so its siblings
                      stay visible and selectable.

Nothing here writes. All three go through the same tables as the assistant's
tools, so the page and the assistant cannot disagree.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from secrdb.core.secr import db as secr_db

#: the order change groups are shown in, and what each is called
OBJECT_TYPES: Tuple[Tuple[str, str], ...] = (
    ("connector", "Connector changes"),
    ("circuit", "Circuit changes"),
    ("part_number", "Part number changes"),
    ("harness", "Harness changes"),
)

#: the endpoint columns of a circuit change, as ``(role, connector, cavity)``
_ENDPOINTS = (
    ("from", "from_dnum", "from_cav"),
    ("to", "to_dnum", "to_cav"),
    ("from (old)", "from_dnum_old", "from_cav_old"),
    ("to (old)", "to_dnum_old", "to_cav_old"),
)

_HEADER_FIELDS = (
    ("secr_number", "SECR #"), ("subject", "Subject"), ("filename", "File name"),
    ("source_def_filename", "DEF compare file"), ("harness_family", "Harness family"),
    ("program", "Program"), ("model_year", "Model year"), ("phase", "Phase"),
    ("phase_implemented", "Phase implemented"), ("change_type", "Change type"),
    ("dtcr_numbers", "DTCR #"), ("bulletin_numbers", "Bulletin #"),
    ("ref_secr", "Reference SECR"), ("secr_author", "SECR author"),
    ("design_release_engineer", "Design release engineer"),
    ("change_requested_by", "Change requested by"),
    ("old_def_source", "Old DEF"), ("new_def_source", "New DEF"),
)

_CHANGE_LABELS = {
    "object_id": "object", "action": "action", "field": "field",
    "old_value": "old value", "new_value": "new value", "dtcr_number": "DTCR",
    "harness_pn": "harness PN", "sales_code": "sales code",
    "se_comment": "SE comment", "source_sheet": "sheet",
}


#: what a search row carries: enough to list and scope a SECR. The preview
#: holds the rest; shipping all ~40 ``secr`` columns per row was payload the
#: list never read (asked for by the UI/UX session, 2026-09-18).
LIST_COLUMNS = ("id", "secr_number", "version", "subject", "model_year", "program",
                "phase", "harness_family", "change_type", "import_origin", "filename",
                "dtcr_numbers", "bulletin_numbers", "created_at", "change_count")


def _split(value: Any) -> List[str]:
    """``"50315, 50317"`` → ``["50315", "50317"]`` — order kept, blanks dropped."""
    out: List[str] = []
    for part in re.split(r"[,;/\n]+", str(value or "")):
        part = part.strip()
        if part and part not in out:
            out.append(part)
    return out


def _add(target: List[str], values: Iterable[str]) -> None:
    for value in values:
        if value and value not in target:
            target.append(value)


# ------------------------------------------------------------------ preview
def secr_preview(secr_id: int, db_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Everything needed to show one SECR without opening its workbook."""
    record = secr_db.get_secr(int(secr_id), db_path=db_path)
    if record is None:
        return None
    changes = record.pop("changes", [])
    dtcr_rows = record.pop("dtcrs", [])

    groups: Dict[str, Dict[str, Dict[str, Any]]] = {}
    by_dtcr: Dict[str, Dict[str, Any]] = {}
    by_cnum: Dict[str, Dict[str, Any]] = {}
    by_action: Dict[str, int] = {}

    def cnum_entry(cnum: str) -> Dict[str, Any]:
        return by_cnum.setdefault(cnum, {"cnum": cnum, "connector_changes": 0,
                                         "circuit_changes": 0, "circuits": [],
                                         "dtcrs": []})

    def dtcr_entry(number: str) -> Dict[str, Any]:
        return by_dtcr.setdefault(number, {
            "dtcr_number": number, "change_count": 0, "connectors": [],
            "circuits": [], "other": [], "cnums": [], "reason_for_change": "",
            "status": "", "device_transmittal": "", "match_method": "",
            "harness_families": [], "in_matching_report": False})

    for change in changes:
        kind = change.get("object_type") or "other"
        object_id = str(change.get("object_id") or "")
        by_action[change["action"]] = by_action.get(change["action"], 0) + 1
        dtcrs = _split(change.get("dtcr_number"))

        # the connectors this change touches: itself, or a circuit's ends
        cnums: List[str] = []
        endpoints: List[Dict[str, str]] = []
        if kind == "connector":
            cnums.append(object_id)
        for role, dnum_col, cav_col in _ENDPOINTS:
            dnum = str(change.get(dnum_col) or "").strip()
            if dnum:
                endpoints.append({"role": role, "cnum": dnum,
                                  "cavity": str(change.get(cav_col) or "").strip()})
                _add(cnums, [dnum])

        entry = groups.setdefault(kind, {}).setdefault(object_id, {
            "object_id": object_id, "actions": [], "dtcrs": [], "cnums": [],
            "harness_pns": [], "sales_codes": [], "changes": []})
        _add(entry["actions"], [change["action"]])
        _add(entry["dtcrs"], dtcrs)
        _add(entry["cnums"], cnums)
        _add(entry["harness_pns"], _split(change.get("harness_pn")))
        _add(entry["sales_codes"], _split(change.get("sales_code")))
        entry["changes"].append({
            "action": change["action"], "field": change.get("field") or "",
            "old_value": change.get("old_value") or "",
            "new_value": change.get("new_value") or "",
            "dtcrs": dtcrs, "se_comment": change.get("se_comment") or "",
            "endpoints": endpoints, "source_sheet": change.get("source_sheet") or "",
            "source_row": change.get("source_row")})

        for cnum in cnums:
            slot = cnum_entry(cnum)
            if kind == "connector":
                slot["connector_changes"] += 1
            else:
                slot["circuit_changes"] += 1
                _add(slot["circuits"], [object_id])
            _add(slot["dtcrs"], dtcrs)
        for number in dtcrs:
            slot = dtcr_entry(number)
            slot["change_count"] += 1
            bucket = {"connector": "connectors", "circuit": "circuits"}.get(kind, "other")
            _add(slot[bucket], [object_id])
            _add(slot["cnums"], cnums)

    # what the DTCR Matching Report said about each DTCR, and any DTCR the
    # SECR names in its header that no change row carries
    for row in dtcr_rows:
        slot = dtcr_entry(str(row.get("dtcr_number") or "").strip())
        slot["in_matching_report"] = True
        for key in ("reason_for_change", "status", "device_transmittal", "match_method"):
            slot[key] = row.get(key) or slot[key]
        _add(slot["harness_families"], [f.upper() for f in _split(row.get("harness_family"))])
        _add(slot["cnums"], _split(row.get("cnum")))
    for number in _split(record.get("dtcr_numbers")):
        dtcr_entry(number)

    families = [f.upper() for f in _split(record.get("harness_family"))]
    for slot in by_dtcr.values():
        _add(families, slot["harness_families"])

    ordered = []
    known = [k for k, _label in OBJECT_TYPES]
    for kind, label in list(OBJECT_TYPES) + [(k, k.replace("_", " ").title() + " changes")
                                             for k in groups if k not in known]:
        objects = sorted(groups.get(kind, {}).values(), key=lambda o: o["object_id"])
        ordered.append({"object_type": kind, "label": label,
                        "object_count": len(objects),
                        "change_count": sum(len(o["changes"]) for o in objects),
                        "objects": objects})

    return {
        "id": record["id"],
        "header": {key: record.get(key) or "" for key, _label in _HEADER_FIELDS} | {
            "version": record.get("version") or "",
            "import_origin": record.get("import_origin") or "",
            "original_issue_date": record.get("original_issue_date") or "",
            "reissue_date": record.get("reissue_date") or "",
            "created_at": record.get("created_at") or "",
            "enriched": bool(record.get("enriched"))},
        "scope": {"model_year": record.get("model_year") or "",
                  "program": record.get("program") or "",
                  "phase": record.get("phase") or "",
                  "harness_families": families},
        "totals": {"changes": len(changes), "by_action": by_action,
                   "by_object_type": {g["object_type"]: g["change_count"] for g in ordered},
                   "dtcrs": len(by_dtcr), "cnums": len(by_cnum)},
        "groups": ordered,
        "dtcrs": sorted(by_dtcr.values(), key=lambda d: d["dtcr_number"]),
        "cnums": sorted(by_cnum.values(),
                        key=lambda c: (-(c["connector_changes"] + c["circuit_changes"]),
                                       c["cnum"])),
        "affected_items": record.get("affected_items", []),
        "source_file": record.get("source_file"),
        "warnings": record.get("warnings", []),
    }


# ------------------------------------------------------------------- search
def _snippet(text: str, term: str, width: int = 48) -> str:
    """The text around the first match, so a hit can be read where it is listed."""
    text = re.sub(r"\s+", " ", str(text))
    at = text.lower().find(term.lower())
    if at < 0:
        return text[: width * 2]
    start, end = max(0, at - width), min(len(text), at + len(term) + width)
    return ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")


def search_documents(text: str, *, limit: int = 200, hits_per_document: int = 8,
                     db_path: Optional[Path] = None, **filters: str) -> List[Dict[str, Any]]:
    """Every SECR that contains ``text`` anywhere, with where and a snippet.

    Contains, not prefix, and over every text column: a word from an SE
    comment, part of a file name, a reason for change, a sales code, a part
    number. ``filters`` narrow by ``program``, ``model_year``, ``phase``,
    ``harness_family``, ``change_type`` and ``import_origin``. With no text
    the filtered SECRs come back with no hits, so the same call lists and
    searches.
    """
    secr_db.init_db(db_path)
    term = str(text or "").strip()
    like = f"%{term}%"
    clauses, params = _scope_clauses(filters)

    with secr_db.connect(db_path) as conn:
        change_columns = [r["name"] for r in conn.execute("PRAGMA table_info(secr_change)")
                          if r["name"] not in ("id", "secr_id", "source_row")]
        if term:
            header_sql = " OR ".join(f"s.{key} LIKE ?" for key, _l in _HEADER_FIELDS)
            change_sql = " OR ".join(f"c.{col} LIKE ?" for col in change_columns)
            clauses.append(
                f"(({header_sql})"
                f" OR EXISTS (SELECT 1 FROM secr_change c WHERE c.secr_id = s.id AND ({change_sql}))"
                " OR EXISTS (SELECT 1 FROM secr_dtcr d WHERE d.secr_id = s.id AND"
                "   (d.dtcr_number LIKE ? OR d.reason_for_change LIKE ? OR d.device_transmittal LIKE ?"
                "    OR d.cnum LIKE ? OR d.harness_family LIKE ? OR d.status LIKE ?))"
                " OR EXISTS (SELECT 1 FROM secr_affected_item a WHERE a.secr_id = s.id AND a.item LIKE ?)"
                " OR EXISTS (SELECT 1 FROM secr_source_file f WHERE f.secr_id = s.id AND f.filename LIKE ?))")
            params += [like] * (len(_HEADER_FIELDS) + len(change_columns) + 6 + 2)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = [dict(r) for r in conn.execute(
            "SELECT s.*, (SELECT COUNT(*) FROM secr_change c WHERE c.secr_id = s.id) AS change_count"
            f" FROM secr s {where} ORDER BY s.id DESC LIMIT ?", params + [int(limit)])]

        for row in rows:
            hits: List[Dict[str, Any]] = []
            if term:
                lowered = term.lower()
                for key, label in _HEADER_FIELDS:
                    if lowered in str(row.get(key) or "").lower():
                        hits.append({"where": "header", "label": label,
                                     "snippet": _snippet(row[key], term)})
                change_sql = " OR ".join(f"{col} LIKE ?" for col in change_columns)
                for change in conn.execute(
                        f"SELECT * FROM secr_change WHERE secr_id = ? AND ({change_sql})"
                        " ORDER BY object_type, object_id, id",
                        [row["id"]] + [like] * len(change_columns)):
                    change = dict(change)
                    col = next(c for c in change_columns
                               if lowered in str(change.get(c) or "").lower())
                    hits.append({"where": "change",
                                 "label": f"{change['object_type']} {change['object_id']} · "
                                          f"{_CHANGE_LABELS.get(col, col.replace('_', ' '))}",
                                 "object_type": change["object_type"],
                                 "object_id": change["object_id"],
                                 "snippet": _snippet(change[col], term)})
                for d in conn.execute("SELECT * FROM secr_dtcr WHERE secr_id = ?", [row["id"]]):
                    d = dict(d)
                    for col in ("dtcr_number", "reason_for_change", "device_transmittal",
                                "cnum", "harness_family", "status"):
                        if lowered in str(d.get(col) or "").lower():
                            hits.append({"where": "dtcr",
                                         "label": f"DTCR {d['dtcr_number']} · {col.replace('_', ' ')}",
                                         "snippet": _snippet(d[col], term)})
                            break
                for a in conn.execute(
                        "SELECT category, action, item FROM secr_affected_item"
                        " WHERE secr_id = ? AND item LIKE ?", [row["id"], like]):
                    hits.append({"where": "affected item",
                                 "label": f"{a['category']} {a['action']}", "snippet": a["item"]})
                for f in conn.execute(
                        "SELECT filename FROM secr_source_file WHERE secr_id = ? AND filename LIKE ?",
                        [row["id"], like]):
                    if not any(h["label"] == "File name" and h["snippet"] == f["filename"]
                               for h in hits):
                        hits.append({"where": "file", "label": "Stored workbook",
                                     "snippet": f["filename"]})
            counts: Dict[str, int] = {}
            for hit in hits:
                counts[hit["where"]] = counts.get(hit["where"], 0) + 1
            row["hit_count"] = len(hits)
            row["hits_by_place"] = counts
            row["hits"] = hits[:hits_per_document]
            row["more_hits"] = max(0, len(hits) - hits_per_document)
            row["harness_families"] = [f.upper() for f in _split(row.get("harness_family"))]
    keep = set(LIST_COLUMNS) | {"hit_count", "hits_by_place", "hits", "more_hits",
                                "harness_families"}
    return [{k: v for k, v in row.items() if k in keep} for row in rows]


# ------------------------------------------------------------------- facets
_FACETS = {
    "model_year": "s.model_year", "program": "s.program", "phase": "s.phase",
    "harness_family": "s.harness_family", "change_type": "s.change_type",
    "import_origin": "s.import_origin",
}


def _scope_clauses(filters: Dict[str, Any], without: str = "") -> Tuple[List[str], List[Any]]:
    unknown = set(filters) - set(_FACETS)
    if unknown:
        raise ValueError(f"not a SECR filter: {sorted(unknown)}; use {sorted(_FACETS)}")
    clauses, params = [], []
    for key, value in filters.items():
        if value and key != without:
            clauses.append(f"{_FACETS[key]} = ?")
            params.append(str(value))
    return clauses, params


def scope_facets(db_path: Optional[Path] = None, **filters: str) -> Dict[str, Any]:
    """``{facet: [{"name", "secrs", "changes", "selected"}]}`` plus ``totals``.

    Each facet is counted under every filter except its own, so picking MY2028
    narrows the programs and phases shown but leaves the other model years
    there to switch to.
    """
    secr_db.init_db(db_path)
    out: Dict[str, Any] = {}
    with secr_db.connect(db_path) as conn:
        clauses, params = _scope_clauses(filters)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        out["totals"] = dict(conn.execute(
            "SELECT COUNT(*) AS secrs, COUNT(DISTINCT s.secr_number) AS secr_numbers,"
            " COALESCE(SUM((SELECT COUNT(*) FROM secr_change c WHERE c.secr_id = s.id)), 0)"
            f" AS changes FROM secr s {where}", params).fetchone())
        for name, expression in _FACETS.items():
            clauses, params = _scope_clauses(filters, without=name)
            clauses.append(f"{expression} IS NOT NULL AND {expression} != ''")
            rows = conn.execute(
                f"SELECT {expression} AS name, COUNT(*) AS secrs,"
                " COALESCE(SUM((SELECT COUNT(*) FROM secr_change c WHERE c.secr_id = s.id)), 0)"
                f" AS changes FROM secr s WHERE {' AND '.join(clauses)}"
                " GROUP BY name ORDER BY name", params).fetchall()
            out[name] = [dict(r) | {"selected": str(filters.get(name) or "") == str(r["name"])}
                         for r in rows]
    return out
