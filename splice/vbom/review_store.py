"""Persist the VBOM review-gate resolutions between sessions.

The review gate is a set of judgements — "this VIN takes this PN for this
family" — that take real thought and were lost the moment the page was
reloaded (the interface schema study's finding F7 for VBOM). They are kept
here, in one small JSON document next to the other workbench stores, so a
bundle regenerated tomorrow arrives with yesterday's decisions restored.

Resolutions are keyed by **programme + case identity**, never by run or by
filename::

    "<MY last two digits>_<program>|<VIN>|<HarnessFamily>"

The engine already identifies a review case as ``ReviewID = "VIN|HarnessFamily"``
(``splice.vbom.engine.build_selection_review_cases``) and
``splice.vbom.review.apply_resolutions`` consumes exactly that pair. A VIN is
the vehicle's identity in the BuildSpec / DoAll and a harness family is the
name the complexity file declares — both survive a re-export, a re-run and a
renamed upload. The programme tag in front is the same ``{MY}_{Program}`` tag
every VBOM output carries, so two programmes reviewed on the shared server
never collide. Nothing else about a case (its reasons, its candidates) is
part of the key: those are what the engine recomputes, not what the SE
decided.

Same shape as :mod:`splice.dtxcircuits.store`: atomic writes, an author and
a revision on every save, and :class:`StaleWrite` when the file moved on
since it was loaded.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Optional

from splice.config import DATA_DIR

logger = logging.getLogger(__name__)

STORE_PATH = DATA_DIR / "vbom" / "review.json"
SCHEMA = 1


def empty() -> dict:
    return {"schema": SCHEMA, "resolutions": {},
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


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------
# identity
# --------------------------------------------------------------------------

def program_tag(my: str, program: str) -> str:
    """The ``{MY last two}_{Program}`` tag every VBOM output is named with."""
    my = str(my or "").strip()
    short = my[-2:] if len(my) >= 2 else my
    return f"{short}_{str(program or '').strip()}"


def case_key(my: str, program: str, review_id: str) -> str:
    """What one review case is called across runs: programme tag + ReviewID
    (``VIN|HarnessFamily``, as the engine builds it)."""
    return f"{program_tag(my, program)}|{str(review_id or '').strip()}"


# --------------------------------------------------------------------------
# load / save
# --------------------------------------------------------------------------

def load(path: Optional[Path] = None) -> dict:
    """The stored resolutions, or an empty document — never raises."""
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
    if not isinstance(data.get("resolutions"), dict):
        data["resolutions"] = {}
    data.setdefault("saved", "")
    data.setdefault("saved_by", "")
    data.setdefault("revision", 0)
    return data


def save(state: dict, path: Optional[Path] = None, *, by: str = "",
         expected_revision: Optional[int] = None) -> Path:
    """Write atomically, so an interrupted save cannot truncate the file.

    Every save carries an author and bumps the revision. A caller that
    passes ``expected_revision`` is refused with :class:`StaleWrite` when
    the file has moved on since it was loaded — two engineers on the shared
    server must not silently overwrite each other's judgements.
    """
    target = Path(path or STORE_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    current = load(target)
    if expected_revision is not None and current["revision"] != expected_revision:
        raise StaleWrite(current)
    payload = dict(state)
    payload["resolutions"] = dict(state.get("resolutions", {}) or {})
    payload["schema"] = SCHEMA
    payload["saved"] = _now()
    payload["saved_by"] = by
    payload["revision"] = current["revision"] + 1
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(target)
    return target


# --------------------------------------------------------------------------
# resolutions
# --------------------------------------------------------------------------

def remember(resolutions: Dict[str, dict], my: str, program: str,
             review_id: str, pn: str, note: str = "", by: str = "") -> Dict[str, dict]:
    """Return a copy of ``resolutions`` with one case resolved."""
    out = dict(resolutions or {})
    out[case_key(my, program, review_id)] = {
        "pn": str(pn or "").strip(), "note": str(note or ""),
        "by": str(by or ""), "at": _now()}
    return out


def forget(resolutions: Dict[str, dict], my: str, program: str,
           review_id: str) -> Dict[str, dict]:
    """Return a copy of ``resolutions`` with one case reopened."""
    out = dict(resolutions or {})
    out.pop(case_key(my, program, review_id), None)
    return out


def restore(resolutions: Dict[str, dict], my: str, program: str,
            review_ids: Iterable[str],
            allowed: Optional[Dict[str, Iterable[str]]] = None) -> Dict[str, dict]:
    """The stored decisions for the cases of this run, by ReviewID.

    Only cases the engine flagged this time come back — a decision for a case
    that no longer exists is left in the store untouched but not surfaced.
    When ``allowed`` (ReviewID -> the PNs the case offers) is given, a stored
    PN the case no longer offers is dropped rather than applied: the SE sees
    the case open again instead of a choice the engine would refuse.
    """
    out: Dict[str, dict] = {}
    allowed = allowed or {}
    for rid in review_ids:
        raw = (resolutions or {}).get(case_key(my, program, rid))
        if not isinstance(raw, dict):
            continue
        pn = str(raw.get("pn", "") or "").strip()
        if not pn:
            continue
        if rid in allowed and pn not in set(allowed[rid]):
            continue
        out[rid] = {"pn": pn, "note": str(raw.get("note", "") or ""),
                    "by": str(raw.get("by", "") or ""),
                    "at": str(raw.get("at", "") or "")}
    return out
