"""DTx reading conventions that are not in the sales-code grammar.

Two of them.

**501 is not an option code.** ``501`` is not an option code: written on its own it means the
circuit is on every harness part number. It is the second most common token in
a real export (213 occurrences in 2028RU X2_A, 201 of them alone), and reading
it as an ordinary code has two costs — the circuit resolves against a code no
complexity file lists, and ``501`` is then reported to the customer as a
sales-code gap they cannot act on.

The rule is deliberately narrow: **only a bare 501 is universal.** Inside a
larger expression (``501/RHV``, ``501&HAH`` — 12 rows between them) it is left
alone and evaluated as any other code. Widening it would silently rewrite
those expressions, and the SE asked for the narrow reading.

**N0 is not a circuit.** It is the DTx's marker for a cavity that connects to
nothing — a *No Connect*. In 2028RU X2_A it is 1,570 of 5,412 rows, and the
circuit name and the function column agree on every one of them: every row
named ``N0`` reads ``No Connect``, and every ``No Connect`` row is named
``N0``. Treated as a circuit it does real damage to the chart, because the
chart's job is to say where wires go: its 1,570 rows became 3,120 chart rows,
they were joined into one fabricated 269-cavity splice (``SN0A``), and 3,106
of them were given a far end — wires nobody drew.
"""

from __future__ import annotations

from typing import Optional

#: Codes that mean "every harness part number" when they are the whole
#: expression. A set because the convention may grow; the rule may not.
UNIVERSAL_ALONE = frozenset({"501"})


#: Circuit names that mean "this cavity connects to nothing".
NO_CONNECT_CIRCUITS = frozenset({"N0"})

#: The function column's wording for the same thing. Accepted alongside the
#: name because the two agreed on all 1,570 rows of the reference export, so
#: either alone identifies the row — and a future export that renames one is
#: still caught by the other.
NO_CONNECT_FUNCTION = "no connect"


def is_no_connect(circuit: Optional[str], function: Optional[str] = "") -> bool:
    """Is this row a No Connect placeholder rather than a wire?"""
    if (circuit or "").strip().upper() in NO_CONNECT_CIRCUITS:
        return True
    return (function or "").strip().lower() == NO_CONNECT_FUNCTION


def is_universal(expression: Optional[str]) -> bool:
    """Is this expression a bare universal code, meaning every build?"""
    return (expression or "").strip() in UNIVERSAL_ALONE


def effective_condition(expression: Optional[str]) -> Optional[str]:
    """The condition to resolve against a harness.

    ``None`` means unconditional — which is what a blank cell and a bare
    universal code both mean. Anything else is returned unchanged, so an
    expression that merely *mentions* a universal code keeps it.
    """
    text = (expression or "").strip()
    if not text or is_universal(text):
        return None
    return text
