"""Integrity of the DTx Sales Code column, checked before anything is resolved.

The grammar (see :mod:`splice.inline.salescode`) is ``/`` OR, ``&`` AND, ``-``
NOT, ``()`` grouping. Two codes must be joined by an explicit ``/`` or ``&``.

An expression that breaks that rule does not fail loudly — it silently becomes
**false for every configuration**, because the evaluator reads the whole run as
one atom that no vehicle carries:

    "AAA-BBB"    -> false for {}, {AAA}, {BBB}, {AAA,BBB}
    "AAA&-BBB"   -> true for {AAA}                        (what was meant)

So the circuit reads as *never built* and is indistinguishable from a genuine
defect. That is why this runs before the circuit and connector analysis rather
than alongside it: an unchecked column poisons every verdict downstream.

Suggestions are proposed, never applied. Only the Systems Engineer knows
whether ``AAA BBB`` meant AND or OR.
"""

from __future__ import annotations

import itertools
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from splice.inline import salescode

logger = logging.getLogger(__name__)

MISSING_OPERATOR = "missing operator"
UNSATISFIABLE = "never true"
UNBALANCED = "unbalanced parentheses"

#: what a separator between two codes was probably meant to be
_SEPARATOR_INTENT: Dict[str, Tuple[str, str]] = {
    "-": ("&", "a NOT needs a connector before it"),
    "+": ("&", "'+' is AND in the complexity workbooks"),
    ",": ("/", "a comma lists alternatives"),
    ";": ("/", "a semicolon lists alternatives"),
}

_TOKEN = re.compile(r"[A-Za-z0-9]+")
#: how many codes an expression may have before satisfiability is not worth
#: brute-forcing (2**12 = 4096 assignments, the same ceiling boolmin uses)
MAX_CODES = 12


@dataclass
class Suggestion:
    expression: str
    reason: str


@dataclass
class Issue:
    """One malformed distinct expression, with everything resting on it."""

    expression: str
    kind: str
    detail: str
    suggestions: List[Suggestion] = field(default_factory=list)
    rows: int = 0
    families: List[str] = field(default_factory=list)
    circuits: List[str] = field(default_factory=list)

    @property
    def confident(self) -> bool:
        """One sensible reading — the SE is confirming, not deciding."""
        return len(self.suggestions) == 1


def _gaps(expression: str) -> List[Tuple[int, int, str]]:
    """Places where two codes meet with no ``/`` or ``&`` between them."""
    tokens = list(_TOKEN.finditer(expression))
    out: List[Tuple[int, int, str]] = []
    for left, right in zip(tokens, tokens[1:]):
        separator = expression[left.end():right.start()]
        if "/" in separator or "&" in separator:
            continue
        # a group boundary is punctuation, not a missing operator, unless it
        # closes and reopens: "(AAA)(BBB)" really is two operands
        stripped = separator.strip()
        if stripped and set(stripped) <= {"(", ")"} and stripped != ")(":
            continue
        out.append((left.end(), right.start(), separator))
    return out


def _repair(expression: str, connector: str) -> str:
    """Rewrite every bad gap with ``connector``, right to left."""
    text = expression
    for start, end, separator in reversed(_gaps(expression)):
        stripped = separator.strip()
        if stripped.startswith("-"):
            # keep the NOT, give it the connector it was missing
            text = text[:start] + connector + stripped + text[end:]
        elif stripped == ")(":
            text = text[:start] + ")" + connector + "(" + text[end:]
        else:
            text = text[:start] + connector + text[end:]
    return text


def satisfiable(expression: str) -> Optional[bool]:
    """Can any set of its own codes make it true? ``None`` = too many to check.

    A syntactically fine expression that is false for every assignment is
    broken on its own terms, whatever the harness data says.
    """
    codes = sorted(salescode.codes_in(expression))
    if not codes or len(codes) > MAX_CODES:
        return None
    for size in range(len(codes) + 1):
        for combination in itertools.combinations(codes, size):
            if salescode.evaluate(expression, set(combination)):
                return True
    return False


def _suggestions(expression: str) -> List[Suggestion]:
    """Candidate repairs, best first, each verified to actually be satisfiable."""
    gaps = _gaps(expression)
    if not gaps:
        return []
    separators = {g[2].strip() for g in gaps}
    ordered: List[str] = []
    # lead with the connector the separator implies, when they all agree
    intents = {_SEPARATOR_INTENT[s][0] for s in separators
               if s in _SEPARATOR_INTENT}
    if len(intents) == 1:
        ordered.append(intents.pop())
    for connector in ("&", "/"):
        if connector not in ordered:
            ordered.append(connector)

    out: List[Suggestion] = []
    for connector in ordered:
        candidate = _repair(expression, connector)
        if candidate == expression or any(s.expression == candidate for s in out):
            continue
        if satisfiable(candidate) is False:
            continue        # a repair that is still never true is no repair
        reason = next((why for sep, (conn, why) in _SEPARATOR_INTENT.items()
                       if conn == connector and sep in separators),
                      "AND — both codes required" if connector == "&"
                      else "OR — either code")
        out.append(Suggestion(expression=candidate, reason=reason))
    return out


def check(expression: str) -> Optional[Issue]:
    """The problem with one expression, or ``None`` when it is sound."""
    raw = (expression or "").strip()
    if not raw:
        return None            # unconditional; nothing to check

    if not salescode.is_valid(raw):
        return Issue(expression=raw, kind=UNBALANCED,
                     detail="The parentheses do not balance, so the expression "
                            "cannot be read.")

    gaps = _gaps(raw)
    if gaps:
        shown = ", ".join(f"'{g[2].strip() or ' '}'" for g in gaps)
        return Issue(
            expression=raw, kind=MISSING_OPERATOR,
            detail=(f"Two sales codes meet with no / or & between them "
                    f"({shown}). The evaluator reads the whole run as one code "
                    f"no vehicle carries, so this expression is false for every "
                    f"configuration and its circuits read as never built."),
            suggestions=_suggestions(raw))

    if satisfiable(raw) is False:
        return Issue(expression=raw, kind=UNSATISFIABLE,
                     detail="No combination of these codes makes the expression "
                            "true, so its circuits can never be built. Check "
                            "for a contradiction such as a code ANDed with its "
                            "own negation.")
    return None


def scan(rows: Iterable) -> List[Issue]:
    """Every malformed expression in a DTx, with what depends on it.

    Rows are grouped by distinct expression: one bad expression used on forty
    circuits is one decision, not forty.
    """
    seen: Dict[str, Issue] = {}
    for row in rows:
        expression = (getattr(row, "sales_code", "") or "").strip()
        if not expression:
            continue
        if expression not in seen:
            issue = check(expression)
            if issue is None:
                seen[expression] = None      # remember the sound ones too
                continue
            seen[expression] = issue
        issue = seen[expression]
        if issue is None:
            continue
        issue.rows += 1
        family = getattr(row, "harness_family", "")
        circuit = getattr(row, "circuit", "")
        if family and family not in issue.families:
            issue.families.append(family)
        if circuit and circuit not in issue.circuits:
            issue.circuits.append(circuit)
    issues = [i for i in seen.values() if i is not None]
    for issue in issues:
        issue.families.sort()
        issue.circuits.sort()
    issues.sort(key=lambda i: (-i.rows, i.expression))
    logger.info("Sales-code integrity: %d malformed expression(s)", len(issues))
    return issues


def apply_fixes(rows: Iterable, fixes: Dict[str, str]) -> List:
    """Rows with resolved expressions rewritten; the rest untouched.

    The original row objects are never mutated — the DTx as loaded stays the
    record of what was received.
    """
    import dataclasses
    out = []
    for row in rows:
        expression = (getattr(row, "sales_code", "") or "").strip()
        replacement = fixes.get(expression)
        out.append(dataclasses.replace(row, sales_code=replacement)
                   if replacement and replacement != expression else row)
    return out
