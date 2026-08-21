"""Sales-code expressions: the language applicability is written in.

The grammar was not documented anywhere; it was recovered from the data. A
Circuit Summary states applicability twice — as an expression and as a vector of
harness part numbers — and the two agree on all 700 expression-bearing rows of
the 28RU X2_A IP export only under one reading:

    /   OR      binds TIGHTEST   "XZ2/XZ3/XAC&-RFX"  ==  (XZ2|XZ3|XAC) & !RFX
    &   AND     binds looser     "LBH/LBR&LBB"       ==  (LBH|LBR) & LBB
    -   NOT     prefix, on an atom or a parenthesised group
    ()  grouping
    ""  empty   unconditional - the circuit is in every build

Reading ``/`` with the precedence it has in most programming languages
mispredicts 20 of those 700 rows, so this is not a detail.

A code may be numeric: ``501`` is a sales code, not a number. A token pattern
that requires a leading letter silently makes every expression mentioning it
unsatisfiable, which during validation turned 24 sound cavities into false
failures.
"""

from __future__ import annotations

import re
from typing import FrozenSet, Iterable, List, Set

#: A sales code: letters and digits, no separators. ``501`` and ``RSY`` both.
_TOKEN = re.compile(r"[A-Za-z0-9]+")

_OR = "/"
_AND = "&"
_NOT = "-"


def codes_in(expression: str) -> Set[str]:
    """Every sales code an expression mentions."""
    return set(_TOKEN.findall(expression or ""))


def _split_top(text: str, separator: str) -> List[str]:
    """Split on a separator, ignoring anything inside parentheses."""
    parts: List[str] = []
    depth = 0
    current = ""
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == separator and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += char
    parts.append(current)
    return parts


def evaluate(expression: str, codes: Iterable[str]) -> bool:
    """Is ``expression`` true for a vehicle carrying ``codes``?

    An empty expression is unconditional and evaluates true — 266 of the 966
    rows in the sample IP export are unconditional.
    """
    present = codes if isinstance(codes, (set, frozenset)) else set(codes)
    text = re.sub(r"\s+", "", expression or "")
    if not text:
        return True
    return _evaluate(text, present)


def _evaluate(text: str, present: Set[str]) -> bool:
    # AND is the loosest operator, so it splits first and OR binds inside it.
    return all(
        any(_atom(operand, present) for operand in _split_top(conjunct, _OR))
        for conjunct in _split_top(text, _AND)
    )


def _atom(token: str, present: Set[str]) -> bool:
    negated = False
    while token.startswith(_NOT):
        negated = not negated
        token = token[1:]
    if token.startswith("(") and token.endswith(")"):
        value = _evaluate(token[1:-1], present)
    else:
        value = token in present
    return (not value) if negated else value


def is_valid(expression: str) -> bool:
    """True when the expression parses and its parentheses balance."""
    text = re.sub(r"\s+", "", expression or "")
    if not text:
        return True
    depth = 0
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                return False
    if depth:
        return False
    try:
        evaluate(expression, set())
        evaluate(expression, codes_in(expression))
    except RecursionError:
        return False
    return True


def satisfiable(expression: str, configurations: Iterable[FrozenSet[str]]) -> bool:
    """Does any real vehicle satisfy this expression?"""
    return any(evaluate(expression, config) for config in configurations)


def co_satisfiable(
    left: str, right: str, configurations: Iterable[FrozenSet[str]]
) -> bool:
    """Is there a vehicle where both conditions hold at once?

    Evaluated over configurations that are actually built rather than over every
    combination of codes. The distinction is not academic: ``RSY`` and ``RTC``
    both exist on the IP and the Dash, but no build carries both, so treating
    them as independent invents a vehicle and reports a continuity gap in it.
    """
    return any(
        evaluate(left, config) and evaluate(right, config)
        for config in configurations
    )
