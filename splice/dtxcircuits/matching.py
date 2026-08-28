"""Suggest which complexity file belongs to which DTx harness family.

Names never agree exactly across the two sources — the DTx says
``SEAT_2ND_ROW_LEFT``, the file says ``SEAT 2ND ROW LEFT``; the DTx says
``POWERTRAIN``, the file says ``POWERTRAIN GAS``. This scores those
near-misses so the workbench can put a likely candidate on the same row as
the family it probably belongs to, leaving the decision to the SE.

Nothing here connects anything. A suggestion is a hint, never a mapping.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

EXACT = 1.0
#: below this a candidate is not worth showing next to a family
THRESHOLD = 0.34

#: tokens that carry no identity and would otherwise inflate every score
_NOISE = {"HARNESS", "COMPLEXITY", "ASSY", "ASSEMBLY", "THE", "AND"}


def normalize(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(name or "").upper())


def tokens(name: str) -> List[str]:
    """Identity-bearing words of a harness name, upper-cased."""
    raw = re.split(r"[^A-Za-z0-9]+", str(name or "").upper())
    return [t for t in raw if t and t not in _NOISE]


@dataclass
class Suggestion:
    """One candidate file for one DTx family, with why it was suggested."""

    key: str            # the caller's handle for the candidate (a filename)
    label: str          # the harness name inside that file
    score: float
    reason: str

    @property
    def is_exact(self) -> bool:
        return self.score >= EXACT


def score(family: str, candidate: str) -> Tuple[float, str]:
    """How strongly ``candidate`` looks like the file for ``family``."""
    fam_n, can_n = normalize(family), normalize(candidate)
    if not fam_n or not can_n:
        return 0.0, ""
    if fam_n == can_n:
        return EXACT, "names match exactly"

    # One name inside the other: POWERTRAIN in POWERTRAIN GAS. The score is the
    # share of the longer name the shorter one accounts for, so a short generic
    # stem inside a long name scores low and a near-complete overlap scores high.
    if fam_n in can_n or can_n in fam_n:
        ratio = min(len(fam_n), len(can_n)) / max(len(fam_n), len(can_n))
        longer, shorter = ((candidate, family) if len(can_n) > len(fam_n)
                           else (family, candidate))
        return max(ratio, 0.5), f"'{shorter}' is contained in '{longer}'"

    fam_t, can_t = set(tokens(family)), set(tokens(candidate))
    if fam_t and can_t:
        shared = fam_t & can_t
        if shared:
            jaccard = len(shared) / len(fam_t | can_t)
            return jaccard, "shares " + ", ".join(sorted(shared))
    return 0.0, ""


def suggest(families: Iterable[str],
            candidates: Dict[str, str],
            *, threshold: float = THRESHOLD,
            limit: int = 3) -> Dict[str, List[Suggestion]]:
    """Best candidates per family, strongest first.

    ``candidates`` maps a caller handle (the filename) to the harness name
    inside that file. Every family gets its own ranking; the same candidate
    may be suggested for several families, since only the SE can decide.
    """
    out: Dict[str, List[Suggestion]] = {}
    for family in families:
        ranked: List[Suggestion] = []
        for key, label in candidates.items():
            value, reason = score(family, label)
            if value >= threshold:
                ranked.append(Suggestion(key=key, label=label, score=value,
                                         reason=reason))
        ranked.sort(key=lambda s: (-s.score, s.label))
        out[family] = ranked[:limit]
    return out


def auto_map(families: Iterable[str],
             candidates: Dict[str, str]) -> Dict[str, str]:
    """Connections safe to make without asking: exact name matches only.

    Anything less certain is left for the SE, because a wrong connection
    yields confident findings rather than an error.
    """
    by_norm: Dict[str, str] = {}
    for key, label in candidates.items():
        by_norm.setdefault(normalize(label), key)
    mapping: Dict[str, str] = {}
    used: set = set()
    for family in families:
        key = by_norm.get(normalize(family))
        if key and key not in used:
            mapping[family] = key
            used.add(key)
    return mapping
