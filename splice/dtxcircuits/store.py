"""Persist the applicability workbench between sessions.

Three things are worth keeping: the mapping the SE built by hand, the rows
they ticked for cleanup, and the sales-code repairs they confirmed. All are
laborious to redo and none is derivable from the files.

The mapping is stored by **harness identity** — the def id inside the
complexity file, falling back to the harness name — never by filename. A file
re-exported tomorrow has a new name and the same def id, and the mapping
should survive that; keying on the filename would silently lose it.

Written atomically next to the Circuit Health baseline, in the same shape
(a small JSON document), so there is one place to look for workbench state.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from splice.config import DATA_DIR

logger = logging.getLogger(__name__)

STORE_PATH = DATA_DIR / "circuit_applicability" / "workbench.json"
SCHEMA = 1


def empty() -> dict:
    return {"schema": SCHEMA, "mapping": {}, "cleanup": {}, "fixes": {},
            "saved": "", "saved_by": "", "revision": 0}


class StaleWrite(Exception):
    """The store changed under us: someone else saved since we loaded it.

    Carries who and when, so the page can say so instead of overwriting."""

    def __init__(self, current: dict) -> None:
        self.by = str(current.get("saved_by", "") or "")
        self.at = str(current.get("saved", "") or "")
        self.revision = int(current.get("revision", 0) or 0)
        super().__init__(f"changed by {self.by or 'someone else'} at {self.at}")


def envelope(data: dict) -> dict:
    """Who saved the store last, when, and which revision that was."""
    return {"by": str(data.get("saved_by", "") or ""),
            "at": str(data.get("saved", "") or ""),
            "revision": int(data.get("revision", 0) or 0)}


def harness_identity(def_id: str = "", harness_name: str = "") -> str:
    """What a complexity file is called across re-exports.

    The def id is the identity every engine matches on; the harness name is
    the fallback for a file that does not declare one.
    """
    ident = str(def_id or "").strip()
    return ident or str(harness_name or "").strip().upper()


def load(path: Optional[Path] = None) -> dict:
    """The stored workbench, or an empty one — never raises."""
    target = Path(path or STORE_PATH)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return empty()
    except Exception as exc:  # noqa: BLE001 — a corrupt file must not block work
        logger.warning("Could not read %s (%s); starting empty", target, exc)
        return empty()
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        logger.info("Ignoring %s: schema %r is not %d", target,
                    data.get("schema") if isinstance(data, dict) else None, SCHEMA)
        return empty()
    data.setdefault("mapping", {})
    data.setdefault("cleanup", {})
    # sales-code repairs are keyed by the raw expression, so they carry over
    # to any DTx that repeats the same malformed text
    data.setdefault("fixes", {})
    data.setdefault("saved_by", "")
    data.setdefault("revision", 0)
    return data


def save(state: dict, path: Optional[Path] = None, *, by: str = "",
         expected_revision: Optional[int] = None) -> Path:
    """Write atomically, so an interrupted save cannot truncate the file.

    Every save carries an author and bumps the revision. A caller that
    passes ``expected_revision`` is refused with :class:`StaleWrite` when
    the file has moved on since it was loaded — the shared server's two
    engineers must not silently overwrite each other's mapping.
    """
    target = Path(path or STORE_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    current = load(target)
    if expected_revision is not None and current["revision"] != expected_revision:
        raise StaleWrite(current)
    payload = dict(state)
    payload["schema"] = SCHEMA
    payload["saved"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload["saved_by"] = by
    payload["revision"] = current["revision"] + 1
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(target)
    return target


# --------------------------------------------------------------------------
# mapping
# --------------------------------------------------------------------------

def remember_mapping(mapping: Dict[str, List[str]],
                     identity_of: Dict[str, str]) -> Dict[str, List[str]]:
    """Turn a live mapping (family -> filenames) into storable identities."""
    out: Dict[str, List[str]] = {}
    for family, filenames in mapping.items():
        idents = [identity_of[f] for f in filenames
                  if identity_of.get(f)]
        if idents:
            out[family] = list(dict.fromkeys(idents))
    return out


def restore_mapping(stored: Dict[str, List[str]],
                    identity_of: Dict[str, str]) -> Dict[str, List[str]]:
    """Rebuild a live mapping from identities, for the files actually loaded.

    An identity with no matching file this session is dropped rather than
    guessed at — the SE sees an unconnected row instead of a wrong one.
    """
    by_identity: Dict[str, str] = {}
    for filename, identity in identity_of.items():
        if identity:
            by_identity.setdefault(identity, filename)
    out: Dict[str, List[str]] = {}
    for family, idents in (stored or {}).items():
        files = [by_identity[i] for i in idents if i in by_identity]
        if files:
            out[family] = list(dict.fromkeys(files))
    return out


# --------------------------------------------------------------------------
# cleanup selections
# --------------------------------------------------------------------------

def remember_cleanup(cleanup: dict) -> dict:
    """Selections as plain JSON — the note is kept so the store explains itself."""
    return {key: {"family": s.family, "harness": s.harness, "kind": s.kind,
                  "ident": s.ident, "verdict": s.verdict,
                  "condition": s.condition, "note": s.note,
                  # the instruction travels with the tick: a row ticked in an
                  # earlier run is still exported as a work item, and without
                  # these it would export with an empty Action column
                  "priority": s.priority, "fix_in": s.fix_in,
                  "action": s.action, "def_id": s.def_id,
                  "builds": s.builds, "evidence": s.evidence}
            for key, s in cleanup.items()}


def restore_cleanup(stored: dict) -> dict:
    """Rebuild selection records. Notes are refreshed on the next analysis, so
    a stored note only has to survive until then."""
    from splice.dtxcircuits.report import CleanupSelection
    out = {}
    for key, raw in (stored or {}).items():
        if not isinstance(raw, dict):
            continue
        out[key] = CleanupSelection(
            key=key, family=raw.get("family", ""), harness=raw.get("harness", ""),
            kind=raw.get("kind", ""), ident=raw.get("ident", ""),
            verdict=raw.get("verdict", ""), condition=raw.get("condition", ""),
            note=raw.get("note", ""), priority=raw.get("priority", ""),
            fix_in=raw.get("fix_in", ""), action=raw.get("action", ""),
            def_id=raw.get("def_id", ""), builds=raw.get("builds", ""),
            evidence=raw.get("evidence", ""))
    return out
