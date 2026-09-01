"""DTx reading conventions that are not in the sales-code grammar.

One so far. ``501`` is not an option code: written on its own it means the
circuit is on every harness part number. It is the second most common token in
a real export (213 occurrences in 2028RU X2_A, 201 of them alone), and reading
it as an ordinary code has two costs — the circuit resolves against a code no
complexity file lists, and ``501`` is then reported to the customer as a
sales-code gap they cannot act on.

The rule is deliberately narrow: **only a bare 501 is universal.** Inside a
larger expression (``501/RHV``, ``501&HAH`` — 12 rows between them) it is left
alone and evaluated as any other code. Widening it would silently rewrite
those expressions, and the SE asked for the narrow reading.
"""

from __future__ import annotations

from typing import Optional

#: Codes that mean "every harness part number" when they are the whole
#: expression. A set because the convention may grow; the rule may not.
UNIVERSAL_ALONE = frozenset({"501"})


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
