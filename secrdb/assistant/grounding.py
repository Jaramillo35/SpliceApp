"""The grounding check: no engineering identifier the evidence cannot support.

A language model asked about wiring harnesses will happily produce a SECR
number that looks exactly right and does not exist. For an engineering record
that is worse than no answer at all, so every answer is checked before it is
shown: each identifier-shaped token in the prose must appear in the tool
results the answer was built from, or in the question the engineer asked.

The check is mechanical, not another model. It cannot be argued with, and it
fails closed — an answer that does not pass is replaced by a templated summary
of the same evidence.

**What counts as an identifier.** Only tokens that could name a real thing:
DTCR-like numbers (4–6 digits), mixed letter-and-digit tokens (``D2784J``,
``A937F``, ``68774881AB``, ``D50319A``), part numbers with separators, and
``.xlsx`` filenames. Ordinary prose, counts, dates and words are left alone —
a checker that flagged "5 changes" would fire on every answer and teach
everyone to ignore it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Sequence, Set

#: Tokens that look like identifiers but are ordinary vocabulary here.
_ALLOWED = frozenset(
    {
        # change types and object kinds
        "ADD", "DELETE", "CHG", "COMP", "PN", "CHANGE",
        "CONNECTOR", "CIRCUIT", "HARNESS", "PART", "NUMBER",
        # column and concept names the model will legitimately name
        "CNUM", "DTCR", "DTCRS", "SECR", "SECRS", "BULLETIN", "PROGRAM",
        "PHASE", "FAMILY", "VERSION", "MY", "V1", "V2", "V3", "V4", "V5",
        "OLD", "NEW", "SALES", "CODE", "GAUGE", "COLOR", "COLOUR",
    }
)

#: A 4–6 digit run: DTCR numbers, bulletins, model years.
_NUMERIC = re.compile(r"\b\d{4,6}\b")

#: A token mixing letters and digits, optionally with part-number separators.
_MIXED = re.compile(r"\b[A-Za-z][A-Za-z0-9]*\d[A-Za-z0-9._\-|/]*\b")

#: A generated or imported SECR filename.
_FILENAME = re.compile(r"\b[\w.\-]+\.xlsx?\b", re.IGNORECASE)

#: Splits a stored value into the pieces a model might quote on its own.
_SPLIT = re.compile(r"[\s,;/|&()\[\]_\-]+")

#: Shortest token worth matching as a fragment of a longer stored value. Below
#: this, a "match" is a coincidence: a stored version of ``1`` would otherwise
#: make every token containing a 1 look supported.
_MIN_FRAGMENT = 4


#: Labels whose identifiers must come from a specific field, not merely exist
#: somewhere in the evidence. A SECR number is a real identifier, so presenting
#: one as a DTCR passes an existence check while being flatly wrong — which is
#: exactly what a field report caught.
_ROLE_FIELDS = {
    "DTCR": ("dtcr_number", "dtcr_numbers"),
    "SECR": ("secr_number",),
}

#: A role label, optionally plural, optionally followed by ``#`` or ``:``.
_ROLE_LABEL = re.compile(r"\b(DTCR|SECR)S?\b\s*[#:]?\s*", re.IGNORECASE)

#: Separators that continue a list of identifiers after a role label. No ``^``:
#: ``Pattern.match(string, pos)`` already anchors at ``pos``, whereas ``^`` would
#: only ever match at the true start of the string — which silently ended every
#: list after its first item.
_LIST_GAP = re.compile(r"[\s,;/&]*(?:and\s+)?[-•*]?\s*", re.IGNORECASE)


@dataclass
class Misattribution:
    """An identifier presented as something it is not."""

    label: str
    token: str

    def __str__(self) -> str:
        return f"{self.token} as a {self.label}"


@dataclass
class GroundingReport:
    """Whether an answer is supported, and by what."""

    grounded: bool
    checked: List[str] = field(default_factory=list)
    ungrounded: List[str] = field(default_factory=list)
    misattributed: List[Misattribution] = field(default_factory=list)
    evidence_values: int = 0

    @property
    def reason(self) -> str:
        if self.grounded:
            return ""
        parts: List[str] = []
        if self.ungrounded:
            parts.append(
                "The answer referred to "
                + ", ".join(repr(token) for token in self.ungrounded[:5])
                + (" and others" if len(self.ungrounded) > 5 else "")
                + ", which the retrieved records do not contain."
            )
        if self.misattributed:
            parts.append(
                "The answer presented "
                + ", ".join(str(item) for item in self.misattributed[:5])
                + (" and others" if len(self.misattributed) > 5 else "")
                + ", which the records do not support."
            )
        return " ".join(parts)


def _normalise(token: str) -> str:
    return token.strip().strip(".,;:!?'\"()[]").upper()


def extract_identifiers(text: str) -> List[str]:
    """Identifier-shaped tokens in a piece of prose, in order, de-duplicated."""
    found: List[str] = []
    seen: Set[str] = set()
    for pattern in (_FILENAME, _MIXED, _NUMERIC):
        for match in pattern.findall(text or ""):
            token = _normalise(str(match))
            if not token or token in seen:
                continue
            if token in _ALLOWED:
                continue
            # "V2"/"MY28" style tokens are prose, not identifiers.
            if re.fullmatch(r"MY\d{2,4}", token) or re.fullmatch(r"V\d{1,3}", token):
                continue
            seen.add(token)
            found.append(token)
    return found


def _expand(value: str) -> Iterable[str]:
    """A stored value plus the forms a model might quote it in.

    ``2028`` is also legitimately written ``28`` or ``MY28``; a part number
    like ``6098-7966_6911-8049`` may be quoted whole or in pieces.
    """
    token = _normalise(value)
    if not token:
        return ()
    forms = {token}
    for piece in _SPLIT.split(token):
        piece = _normalise(piece)
        if piece:
            forms.add(piece)
    if re.fullmatch(r"\d{4}", token):  # model year
        forms.add(token[-2:])
        forms.add("MY" + token)
        forms.add("MY" + token[-2:])
    return forms


def evidence_values(evidence: Any) -> Set[str]:
    """Every string the evidence contains, in every form worth matching."""
    values: Set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for item in node.values():
                walk(item)
        elif isinstance(node, (list, tuple, set)):
            for item in node:
                walk(item)
        elif node is None or isinstance(node, bool):
            return
        else:
            values.update(_expand(str(node)))

    walk(evidence)
    values.discard("")
    return values


def _supported(token: str, supported: Set[str]) -> bool:
    """Is this token backed by the evidence?

    Exact match first. Then, only for tokens long enough to be an identifier in
    their own right, allow the token to be a *fragment* of a longer stored
    value — a model may quote ``6098-7966`` out of
    ``6098-7966_6911-8049``. The relaxation runs in one direction only:
    treating a stored value as a fragment of the token would let a stored
    version number of ``1`` support ``D11111A``.
    """
    if token in supported:
        return True
    if len(token) < _MIN_FRAGMENT:
        return False
    return any(
        len(value) > len(token) and token in value for value in supported
    )


def field_values(evidence: Any, keys: Sequence[str]) -> Set[str]:
    """Every value the evidence holds under any of ``keys``."""
    values: Set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                if key in keys and item not in (None, ""):
                    values.update(_expand(str(item)))
                walk(item)
        elif isinstance(node, (list, tuple, set)):
            for item in node:
                walk(item)

    walk(evidence)
    values.discard("")
    return values


def _labelled_identifiers(answer: str) -> List[tuple]:
    """``(label, token)`` pairs where the answer presents a token *as* a label.

    Only tokens that directly follow the label are taken — the label, then any
    list separators, then identifiers. Reading further would sweep in ordinary
    prose: "DTCR 50319 changed circuit A111" must yield ``50319`` alone, not
    ``A111``.
    """
    pairs: List[tuple] = []
    for match in _ROLE_LABEL.finditer(answer or ""):
        label = match.group(1).upper()
        position = match.end()
        while position < len(answer):
            gap = _LIST_GAP.match(answer, position)
            position = gap.end() if gap else position
            token_match = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-|/]*").match(
                answer, position
            )
            if not token_match:
                break
            token = _normalise(token_match.group(0))
            if not token or not extract_identifiers(token):
                break  # ordinary word — the list has ended
            pairs.append((label, token))
            position = token_match.end()
    return pairs


def check_roles(answer: str, evidence: Any) -> List[Misattribution]:
    """Find identifiers presented under the wrong label.

    Existence is not enough: a SECR number quoted as a DTCR is in the evidence
    and still wrong. Only labels in :data:`_ROLE_FIELDS` are checked, and only
    when the evidence actually carries that field — otherwise there is nothing
    to check against and silence is the honest result.
    """
    problems: List[Misattribution] = []
    for label, token in _labelled_identifiers(answer):
        keys = _ROLE_FIELDS.get(label)
        if not keys:
            continue
        allowed = field_values(evidence, keys)
        if not allowed:
            continue
        if token not in allowed:
            problems.append(Misattribution(label=label, token=token))
    return problems


def check(
    answer: str,
    evidence: Any,
    question: str = "",
    extra_allowed: Sequence[str] = (),
) -> GroundingReport:
    """Verify every identifier in ``answer`` is supported.

    An identifier is supported when it appears in the evidence, in the
    question, or in ``extra_allowed``. Echoing the question matters: *"there is
    no record of circuit ZZ999"* is a correct and useful answer, and the whole
    point is that ZZ999 is **not** in the evidence.
    """
    supported = evidence_values(evidence)
    supported |= evidence_values(question)
    supported |= {_normalise(token) for token in extra_allowed}

    checked = extract_identifiers(answer)
    ungrounded = [
        token for token in checked if not _supported(token, supported)
    ]
    misattributed = check_roles(answer, evidence)
    return GroundingReport(
        grounded=not ungrounded and not misattributed,
        checked=checked,
        ungrounded=ungrounded,
        misattributed=misattributed,
        evidence_values=len(supported),
    )


# ---------------------------------------------------------------------------
# Deterministic fallback
# ---------------------------------------------------------------------------

def summarise_evidence(rows: List[Dict[str, Any]]) -> str:
    """A plain summary built only from retrieved rows.

    Used when the model's prose fails the check, and whenever a templated
    answer is safer than a written one. Every number here is counted, not
    generated.
    """
    if not rows:
        return "No matching records were found in the database."

    secrs: List[str] = []
    actions: Dict[str, int] = {}
    families: List[str] = []
    dtcrs: List[str] = []
    for row in rows:
        for key, bucket in (
            ("secr_number", secrs),
            ("harness_family", families),
            ("dtcr_number", dtcrs),
        ):
            value = str(row.get(key) or "").strip()
            if value and value not in bucket:
                bucket.append(value)
        action = str(row.get("action") or "").strip()
        if action:
            actions[action] = actions.get(action, 0) + 1

    parts = [f"Found {len(rows)} change record(s)"]
    if secrs:
        shown = ", ".join(secrs[:8]) + (" and others" if len(secrs) > 8 else "")
        parts.append(f"across {len(secrs)} SECR(s): {shown}")
    if families:
        parts.append("Harness families: " + ", ".join(families[:8]) + ".")
    if actions:
        parts.append(
            "Change types: "
            + ", ".join(f"{name} ({count})" for name, count in sorted(actions.items()))
            + "."
        )
    if dtcrs:
        parts.append("DTCRs: " + ", ".join(dtcrs[:8]) + ".")
        missing = sum(1 for row in rows if not str(row.get("dtcr_number") or "").strip())
        if missing:
            parts.append(f"{missing} record(s) have no DTCR recorded.")
    elif any("dtcr_number" in row for row in rows):
        parts.append("None of these records has a DTCR recorded.")
    return " ".join(parts).replace(" across", ", across", 1)
