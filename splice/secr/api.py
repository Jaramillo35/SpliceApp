"""SECR query API — the read-only surface over the SECR database.

Every question the UI asks the database goes through here, and this is the only
module a future local assistant (Ollama / Qwen) is given access to. The
functions are deliberately narrow, parameterised, and read-only:

    * no function accepts SQL, so the assistant can never execute arbitrary SQL
    * no function writes, so a wrong answer can never corrupt engineering data
    * every result is plain dicts/lists, ready to be serialised into a tool
      response

Writes live in :mod:`splice.secr.db` (used by generation and import) and are
not re-exported here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from splice.secr import db as secr_db

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
    """Every change attributed to a DTCR, across all SECRs."""
    return secr_db.find_changes(
        dtcr_number=str(dtcr_number).strip(), limit=limit, db_path=db_path
    )


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
    """Every change on a connector number (e.g. ``D2784J``)."""
    return secr_db.find_changes(
        object_type="connector", object_id=cnum, limit=limit, db_path=db_path
    )


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
    "get_changes_by_circuit": get_changes_by_circuit,
    "get_connector_changes": get_connector_changes,
    "get_program_summary": get_program_summary,
    "get_model_year_summary": get_model_year_summary,
    "get_database_summary": get_database_summary,
    "get_revision_chain": get_revision_chain,
}
