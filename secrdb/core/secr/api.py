"""SECR query API — the read-only surface over the SECR database.

Every question the UI asks the database goes through here, and this is the only
module a future local assistant (Ollama / Qwen) is given access to. The
functions are deliberately narrow, parameterised, and read-only:

    * no function accepts SQL, so the assistant can never execute arbitrary SQL
    * no function writes, so a wrong answer can never corrupt engineering data
    * every result is plain dicts/lists, ready to be serialised into a tool
      response

Writes live in :mod:`secrdb.core.secr.db` (used by generation and import) and are
not re-exported here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from secrdb.core.secr import db as secr_db

# Object types a change can be about, for callers building filters.
OBJECT_TYPES = ("connector", "circuit", "part_number", "harness")


def search_secrs(
    query: str = "",
    *,
    program: str = "",
    model_year: str = "",
    bulletin: str = "",
    harness_family: str = "",
    phase: str = "",
    dtcr: str = "",
    change_type: str = "",
    limit: int = 200,
    db_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Find SECRs by free text and/or filters. Each row explains its match."""
    return secr_db.search_secrs(
        query,
        program=program,
        model_year=model_year,
        bulletin=bulletin,
        harness_family=harness_family,
        phase=phase,
        dtcr=dtcr,
        change_type=change_type,
        limit=limit,
        db_path=db_path,
    )


def get_secr_summary(
    secr_number: str, version: str = "", db_path: Optional[Path] = None
) -> Optional[Dict[str, Any]]:
    """Header, DTCRs and change counts for one SECR — without the full change list.

    With no ``version``, the most recently stored version is returned.
    """
    matches = [
        record
        for record in secr_db.list_secrs(db_path=db_path)
        if record["secr_number"] == str(secr_number).strip()
        and (not version or record["version"] == str(version).strip())
    ]
    if not matches:
        return None
    record = secr_db.get_secr(matches[0]["id"], db_path=db_path)
    if record is None:
        return None
    changes = record.pop("changes", [])
    by_action: Dict[str, int] = {}
    by_object: Dict[str, int] = {}
    for change in changes:
        by_action[change["action"]] = by_action.get(change["action"], 0) + 1
        by_object[change["object_type"]] = by_object.get(change["object_type"], 0) + 1
    record["change_count"] = len(changes)
    record["changes_by_action"] = by_action
    record["changes_by_object_type"] = by_object
    return record


def get_changes_by_secr(
    secr_number: str, version: str = "", db_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """Every change record belonging to one SECR."""
    summary = get_secr_summary(secr_number, version, db_path=db_path)
    if summary is None:
        return []
    return secr_db.get_changes(summary["id"], db_path=db_path)


def get_changes_by_dtcr(
    dtcr_number: str, limit: int = 1000, db_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """Everything a DTCR touches, across all SECRs.

    A DTCR reaches the database two ways, and they diverge constantly:

    * it is written into the SE comment of an individual change row, which
      attributes it to that exact change; or
    * it is listed on the SECR's Summary sheet, which attributes it to the
      whole SECR and to no particular row.

    Those are different acts by different people, so roughly half of the DTCRs
    an engineer can see in the app appear only in the second form. Reading only
    change rows made those DTCRs answer "nothing found" — reported from the
    field twice for the same DTCR.

    Change rows are returned when they exist. When none carry the DTCR, the
    SECRs that list it are returned instead, each marked
    ``dtcr_attribution='secr'`` so an answer can say *"DTCR 50948 is listed on
    SECR D50277A (DASH), but no individual change record is tagged with it"*
    rather than staying silent.
    """
    term = str(dtcr_number).strip()
    if not term:
        return []

    changes = secr_db.find_changes(
        dtcr_number=term, limit=limit, db_path=db_path
    )
    if changes:
        for row in changes:
            row["dtcr_attribution"] = "change"
        return changes

    listed = secr_db.search_secrs(dtcr=term, limit=limit, db_path=db_path)
    for row in listed:
        row["dtcr_attribution"] = "secr"
        row["dtcr_number"] = term
    return listed


def get_changes_by_harness(
    harness_family: str,
    *,
    model_year: str = "",
    program: str = "",
    limit: int = 1000,
    db_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Every change on a harness family, optionally narrowed to a MY/program."""
    return secr_db.find_changes(
        harness_family=harness_family,
        model_year=model_year,
        program=program,
        limit=limit,
        db_path=db_path,
    )


def get_changes_by_cnum(
    cnum: str, limit: int = 1000, db_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """Every change involving a connector (e.g. ``D2784J``), in either role.

    A connector is involved two ways, and an engineer asking about one means
    both:

    ``connector``   the connector itself changed — part number, suffix, added,
                    deleted. The change's own object.
    ``endpoint``    a circuit was routed to or from it. The change's object is
                    the *circuit*; the connector is where it lands, with a
                    cavity.

    Each row carries ``connector_role`` saying which it was, so an answer can
    tell "D2784J changed" from "a circuit moved onto D2784J cavity 7" instead
    of blurring them together.
    """
    term = str(cnum).strip()
    if not term:
        return []
    rows = secr_db.find_changes(connector=term, limit=limit, db_path=db_path)
    for row in rows:
        _describe_endpoint(row, term)
    return rows


#: Which column pair describes each end, before and after.
_ENDPOINT_SIDES = (
    ("FROM", "after", "from_dnum", "from_cav"),
    ("TO", "after", "to_dnum", "to_cav"),
    ("FROM", "before", "from_dnum_old", "from_cav_old"),
    ("TO", "before", "to_dnum_old", "to_cav_old"),
)


def _describe_endpoint(row: Dict[str, Any], connector: str) -> None:
    """Say how this row involves the connector, in place.

    ``connector_role`` is ``connector`` when the connector itself changed, and
    ``endpoint`` when a circuit terminates on it. Endpoint rows also get the
    side, the cavity, and ``endpoint_state``:

    ``arrived``   the circuit moved onto this pin
    ``left``      the circuit moved off it — still a change *to* that pin
    ``present``   the pin did not move; something else about the circuit did
    """
    upper = connector.strip().upper()
    if row.get("object_type") == "connector" and str(
        row.get("object_id") or ""
    ).upper().startswith(upper):
        row["connector_role"] = "connector"
        return

    hits = {
        (side, when): row.get(cav)
        for side, when, dnum, cav in _ENDPOINT_SIDES
        if str(row.get(dnum) or "").upper() == upper
    }
    if not hits:
        row["connector_role"] = "connector"
        return

    side = next(s for s, _when in hits)
    before = (side, "before") in hits
    after = (side, "after") in hits
    row["connector_role"] = "endpoint"
    row["endpoint_side"] = side
    row["endpoint_cavity"] = hits.get((side, "after")) or hits.get(
        (side, "before")
    )
    row["endpoint_state"] = (
        "present" if before and after else "arrived" if after else "left"
    )


def get_changes_by_endpoint(
    connector: str,
    cavity: str = "",
    limit: int = 1000,
    db_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Every change at a connector's pin — optionally one cavity.

    Answers "what is wired to D2784J?" and "has X501A cavity 7 had any
    changes?". Both directions count: a circuit arriving at the pin and a
    circuit leaving it are each a change to that pin, so a circuit routed away
    from ``X501A|7`` is returned even though it now terminates elsewhere.

    Each row says which in ``endpoint_state`` (``arrived`` / ``left`` /
    ``present``), and carries its SECR's phase, so the same pin holding
    different circuits across phases reads as a history rather than a
    contradiction.
    """
    term = str(connector).strip()
    if not term:
        return []
    rows = secr_db.find_changes(
        endpoint=term,
        cavity=str(cavity).strip(),
        limit=limit,
        db_path=db_path,
    )
    for row in rows:
        _describe_endpoint(row, term)
    return rows


def get_changes_by_circuit(
    circuit: str, limit: int = 1000, db_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """Every change on a circuit (e.g. ``A937F``; ``A937`` also matches it)."""
    return secr_db.find_changes(
        object_type="circuit", object_id=circuit, limit=limit, db_path=db_path
    )


def get_connector_changes(
    connector_pn: str, limit: int = 1000, db_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """Every change where a connector part number was the old or new value."""
    term = str(connector_pn).strip()
    if not term:
        return []
    matches = secr_db.find_changes(
        object_type="connector", limit=limit, db_path=db_path
    )
    return [
        change
        for change in matches
        if term in str(change.get("old_value") or "")
        or term in str(change.get("new_value") or "")
    ]


def get_program_summary(
    program: str, db_path: Optional[Path] = None
) -> Dict[str, Any]:
    """SECR and change counts for one vehicle program."""
    return _scope_summary({"program": program}, db_path=db_path)


def get_model_year_summary(
    model_year: str, db_path: Optional[Path] = None
) -> Dict[str, Any]:
    """SECR and change counts for one model year."""
    return _scope_summary({"model_year": model_year}, db_path=db_path)


def _scope_summary(
    scope: Dict[str, str], db_path: Optional[Path] = None
) -> Dict[str, Any]:
    secrs = secr_db.search_secrs(limit=10_000, db_path=db_path, **scope)
    changes_by_action: Dict[str, int] = {}
    families: Dict[str, int] = {}
    dtcrs: Dict[str, int] = {}
    for secr in secrs:
        family = secr.get("harness_family") or "(unspecified)"
        families[family] = families.get(family, 0) + 1
        for change in secr_db.get_changes(secr["id"], db_path=db_path):
            action = change["action"]
            changes_by_action[action] = changes_by_action.get(action, 0) + 1
            dtcr = change.get("dtcr_number")
            if dtcr:
                dtcrs[dtcr] = dtcrs.get(dtcr, 0) + 1
    return {
        **scope,
        "secr_count": len(secrs),
        "change_count": sum(changes_by_action.values()),
        "changes_by_action": changes_by_action,
        "secrs_by_harness_family": dict(
            sorted(families.items(), key=lambda kv: -kv[1])
        ),
        "top_dtcrs": dict(sorted(dtcrs.items(), key=lambda kv: -kv[1])[:10]),
        "secr_numbers": [s["secr_number"] for s in secrs],
    }


def get_database_summary(db_path: Optional[Path] = None) -> Dict[str, Any]:
    """Totals and breakdowns for the dashboard."""
    return secr_db.database_summary(db_path=db_path)


def get_revision_chain(
    secr_number: str, db_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """Revision history of a SECR, oldest change last (as stored)."""
    summary = get_secr_summary(secr_number, db_path=db_path)
    if summary is None:
        return []
    return secr_db.get_revision_chain(summary["id"], db_path=db_path)


#: The tool surface a local assistant is allowed to call. Keeping it explicit
#: means adding a function here is a deliberate act, not an accident of import.
READ_ONLY_TOOLS = {
    "search_secrs": search_secrs,
    "get_secr_summary": get_secr_summary,
    "get_changes_by_secr": get_changes_by_secr,
    "get_changes_by_dtcr": get_changes_by_dtcr,
    "get_changes_by_harness": get_changes_by_harness,
    "get_changes_by_cnum": get_changes_by_cnum,
    "get_changes_by_endpoint": get_changes_by_endpoint,
    "get_changes_by_circuit": get_changes_by_circuit,
    "get_connector_changes": get_connector_changes,
    "get_program_summary": get_program_summary,
    "get_model_year_summary": get_model_year_summary,
    "get_database_summary": get_database_summary,
    "get_revision_chain": get_revision_chain,
}
