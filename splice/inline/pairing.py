"""Working out which inline connector mates with which.

Two conventions appear in the data and both are honoured:

``X301A ↔ Y301A``   an X/Y prefix on a shared stem, with a shared trailing letter
``I350X ↔ I350Y``   an X/Y *suffix* on a shared stem

The device name corroborates rather than decides — ``Inline_X301 Dash_IP`` names
both harnesses, which is useful for explaining a pair but too free-form to
resolve one.

A connector whose mate is nowhere in the export is never guessed at. It is
reported as **Not in Ckt Summary**, because the usual cause is that the mating
harness was not exported, and that is a fact about the inputs the engineer needs
to see.
"""

from __future__ import annotations

import re
from typing import Dict, List, Set, Tuple

from splice.inline.model import CircuitEnd, InlinePair
from splice.inline.summary import is_inline

_XY_PREFIX = re.compile(r"^([XY])(\d+)([A-Z]?)$")
_XY_SUFFIX = re.compile(r"^(I\d+)([XY])$")


def mate_name(connector: str) -> str | None:
    """The name the mating connector would have, or ``None`` if unknown."""
    name = (connector or "").strip().upper()
    match = _XY_PREFIX.match(name)
    if match:
        flipped = "Y" if match.group(1) == "X" else "X"
        return f"{flipped}{match.group(2)}{match.group(3)}"
    match = _XY_SUFFIX.match(name)
    if match:
        flipped = "Y" if match.group(2) == "X" else "X"
        return f"{match.group(1)}{flipped}"
    return None


def locate_inlines(ends: List[CircuitEnd]) -> Dict[str, Set[str]]:
    """Connector name -> the harnesses it appears on."""
    located: Dict[str, Set[str]] = {}
    for end in ends:
        if is_inline(end) and end.connector:
            located.setdefault(end.connector, set()).add(end.harness_id)
    return located


def resolve(
    ends: List[CircuitEnd], in_scope: Set[str] | None = None
) -> Tuple[List[InlinePair], List[Tuple[str, str]]]:
    """Pair up inline connectors.

    Returns the pairs and the connectors left unmated, each with the harness it
    sits on. Only harnesses in ``in_scope`` participate, so an excluded harness
    neither creates pairs nor absorbs someone else's mate.
    """
    located = locate_inlines(ends)
    if in_scope is not None:
        located = {
            name: {h for h in harnesses if h in in_scope}
            for name, harnesses in located.items()
        }
        located = {name: h for name, h in located.items() if h}

    seen: Set[frozenset] = set()
    pairs: List[InlinePair] = []
    unmated: List[Tuple[str, str]] = []

    for connector in sorted(located):
        mate = mate_name(connector)
        partners = located.get(mate, set()) if mate else set()
        matched = False
        for harness in sorted(located[connector]):
            for other in sorted(partners):
                if other == harness:
                    continue  # a connector and its mate on one harness is not an inline
                key = frozenset({(connector, harness), (mate, other)})
                if key in seen:
                    matched = True
                    continue
                seen.add(key)
                pairs.append(
                    InlinePair(
                        connector_a=connector,
                        harness_a=harness,
                        connector_b=mate,
                        harness_b=other,
                        resolved_by="stem" if _XY_PREFIX.match(connector) else "suffix",
                    )
                )
                matched = True
        if not matched:
            for harness in sorted(located[connector]):
                unmated.append((connector, harness))

    return pairs, unmated
