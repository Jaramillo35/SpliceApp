"""The rules. Given a built model, produce findings.

A cavity is **continuous** when there is a circuit end on each side carrying the
same circuit, and each of those conditions is actually built on its own harness.
That is the rule the engineering team set: a cavity often holds several options,
split by sales code on one side or on both, and the joint is sound when any of
them pairs up.

Applicability is only ever evaluated against the harness that owns it, using the
builds that harness ships as. The engine deliberately does not try to decide
which part number on one harness corresponds to which on another — that was
tried, and the complexity files do not support it. Evaluating per harness also
keeps impossible vehicles out of the reasoning: ``RSY`` and ``RTC`` both exist
on the IP and the Dash, but no build carries both.

Wire attribute differences are **marked, never judged**. Which of them are
acceptable is engineering judgement that belongs in a reviewable table.
"""

from __future__ import annotations

from typing import Dict, List, Set

from splice.common.logging import get_logger
from splice.inline.complexity import counterpart_applies, satisfying_builds
from splice.inline.summary import is_inline
from splice.inline.model import (
    CONDITIONS_EXCLUSIVE,
    INTEGRITY,
    MARK_UNPAIRED,
    Option,
    CONTINUOUS,
    INCONSISTENT,
    MARK_MATERIAL,
    MARK_SALES_CODE,
    MARK_SIZE,
    MARK_SUFFIX,
    MISSING_CONTINUATION,
    NOT_IN_SUMMARY,
    UNDETERMINED,
    CircuitEnd,
    Finding,
    Harness,
    InlinePair,
    StudyResult,
)

logger = get_logger(__name__)


def _by_cavity(ends: List[CircuitEnd], connector: str) -> Dict[str, List[CircuitEnd]]:
    grouped: Dict[str, List[CircuitEnd]] = {}
    for end in ends:
        if end.connector == connector:
            grouped.setdefault(end.cavity, []).append(end)
    return grouped


def _pair_options(
    side_a: List[CircuitEnd],
    side_b: List[CircuitEnd],
    harness_a: Harness | None,
    harness_b: Harness | None,
) -> List[Option]:
    """Match each wire on one side to its counterpart on the other.

    A counterpart is **not** consumed. One wire can serve several variants
    opposite it, and in this data that is the normal case: the IP splits a
    cavity into ``A934A`` and ``A934B`` by sales code while the Dash carries a
    single ``A934`` across all of its part numbers. Both IP variants continue
    through that one Dash wire, because its condition holds in the vehicles
    where each of them is built — which is what the complexity tables are for.

    Pairing one-to-one instead would report the second variant as unpaired, and
    an engineer would be sent to investigate a joint that is correct.
    """
    options: List[Option] = []
    served: set = set()

    for left in side_a:
        candidates = [
            (index, right)
            for index, right in enumerate(side_b)
            if right.circuit == left.circuit
            and counterpart_applies(
                harness_a, left.sales_code, harness_b, right.sales_code
            )
        ]
        # Prefer the same suffix, then the most specific condition available.
        candidates.sort(
            key=lambda pair: (pair[1].suffix != left.suffix, -len(pair[1].sales_code))
        )
        option = Option(
            circuit_a=left.circuit, suffix_a=left.suffix,
            sales_code_a=left.sales_code, size_a=left.size, material_a=left.material,
        )
        if candidates:
            index, right = candidates[0]
            served.add(index)
            option.circuit_b = right.circuit
            option.suffix_b = right.suffix
            option.sales_code_b = right.sales_code
            option.size_b = right.size
            option.material_b = right.material
            option.marks = _marks(left, right)
            option.matched = True
        else:
            option.marks = [MARK_UNPAIRED]
        options.append(option)

    # A wire on the far side that no near-side variant reaches is still shown.
    for index, right in enumerate(side_b):
        if index in served:
            continue
        options.append(
            Option(
                circuit_b=right.circuit, suffix_b=right.suffix,
                sales_code_b=right.sales_code, size_b=right.size,
                material_b=right.material,
                marks=[MARK_UNPAIRED],
            )
        )
    return options


def _marks(left: CircuitEnd, right: CircuitEnd) -> List[str]:
    marks = []
    if left.suffix != right.suffix:
        marks.append(MARK_SUFFIX)
    if left.size != right.size:
        marks.append(MARK_SIZE)
    if left.material != right.material:
        marks.append(MARK_MATERIAL)
    if left.sales_code != right.sales_code:
        marks.append(MARK_SALES_CODE)
    return marks


def _is_built(harness: Harness | None, expression: str) -> bool:
    """Is this condition true for at least one build of its own harness?

    With no complexity file the question cannot be answered, so the caller
    treats the cavity as undetermined rather than assuming either way.
    """
    if harness is None or not harness.builds:
        return True
    return bool(satisfying_builds(harness, expression))


def check_cavity(
    pair: InlinePair,
    cavity: str,
    side_a: List[CircuitEnd],
    side_b: List[CircuitEnd],
    harness_a: Harness | None,
    harness_b: Harness | None,
) -> Finding:
    """Decide one cavity."""
    finding = Finding(
        verdict=CONTINUOUS,
        connector_a=pair.connector_a,
        harness_a=harness_a.name if harness_a else pair.harness_a,
        connector_b=pair.connector_b,
        harness_b=harness_b.name if harness_b else pair.harness_b,
        cavity=cavity,
        circuits_a=sorted({e.label for e in side_a}),
        circuits_b=sorted({e.label for e in side_b}),
        sales_codes_a=sorted({e.sales_code for e in side_a}),
        sales_codes_b=sorted({e.sales_code for e in side_b}),
    )

    if not side_a or not side_b:
        finding.verdict = MISSING_CONTINUATION
        occupied = pair.connector_a if side_a else pair.connector_b
        empty = pair.connector_b if side_a else pair.connector_a
        finding.reason = (
            f"Cavity {cavity} is occupied on {occupied} and empty on {empty}."
        )
        return finding

    shared = {e.circuit for e in side_a} & {e.circuit for e in side_b}
    if not shared:
        finding.verdict = INCONSISTENT
        finding.reason = (
            f"Cavity {cavity} carries {', '.join(finding.circuits_a)} on "
            f"{pair.connector_a} but {', '.join(finding.circuits_b)} on "
            f"{pair.connector_b}."
        )
        return finding

    finding.options = _pair_options(side_a, side_b, harness_a, harness_b)

    for option in finding.options:
        if not option.matched:
            continue
        finding.verdict = CONTINUOUS
        finding.marks = sorted({m for o in finding.options for m in o.marks})
        finding.reason = (
            f"{option.label_a} continues through cavity {cavity}"
            + (
                f" ({option.sales_code_a or 'standard'} ↔ "
                f"{option.sales_code_b or 'standard'})"
                if option.sales_code_a != option.sales_code_b
                else ""
            )
            + "."
        )
        return finding

    # A shared circuit exists but no option is built on both sides.
    unbuilt_a = [
        e.sales_code for e in side_a if not _is_built(harness_a, e.sales_code)
    ]
    unbuilt_b = [
        e.sales_code for e in side_b if not _is_built(harness_b, e.sales_code)
    ]
    finding.verdict = CONDITIONS_EXCLUSIVE
    detail = []
    if unbuilt_a:
        detail.append(f"never built on {finding.harness_a}: {', '.join(unbuilt_a)}")
    if unbuilt_b:
        detail.append(f"never built on {finding.harness_b}: {', '.join(unbuilt_b)}")
    finding.reason = (
        f"Cavity {cavity} names {', '.join(sorted(shared))} on both sides, but no "
        "option is built on both. " + ("; ".join(detail) if detail else "")
    ).strip()
    return finding


def check_integrity(
    ends: List[CircuitEnd], complexity: Dict[str, Harness]
) -> List[Finding]:
    """Cross-check the two applicability sources against each other.

    The Circuit Summary states applicability twice: as a sales-code expression
    and as a vector of part-number columns. Evaluating the expression against
    the harness's complexity must reproduce the columns exactly — it does on all
    1,163 inline ends of the reference release. A disagreement means the export
    is stale or the complexity is the wrong revision, and neither source can be
    trusted for that row.
    """
    findings: List[Finding] = []
    for end in ends:
        harness = complexity.get(end.harness_id)
        if harness is None or not harness.builds or not end.builds:
            continue
        predicted = {
            build.part_number for build in satisfying_builds(harness, end.sales_code)
        }
        if predicted == set(end.builds):
            continue
        findings.append(
            Finding(
                verdict=INTEGRITY,
                connector_a=end.connector,
                harness_a=harness.name,
                cavity=end.cavity,
                circuits_a=[end.label],
                sales_codes_a=[end.sales_code],
                reason=(
                    f"Row {end.source_row}: '{end.sales_code or '(unconditional)'}' "
                    f"resolves to {len(predicted)} build(s) but the part-number "
                    f"columns mark {len(end.builds)}. "
                    f"Only in columns: {sorted(set(end.builds) - predicted) or '—'}; "
                    f"only in the expression: {sorted(predicted - set(end.builds)) or '—'}."
                ),
            )
        )
    return findings


def run_study(
    summary_harnesses: Dict[str, Harness],
    ends: List[CircuitEnd],
    complexity: Dict[str, Harness],
    pairs: List[InlinePair],
    unmated: List,
    out_of_scope: Set[str] | None = None,
) -> StudyResult:
    """Validate every cavity of every resolved inline pair."""
    out_of_scope = out_of_scope or set()
    result = StudyResult(harnesses=complexity, pairs=pairs)

    by_harness: Dict[str, List[CircuitEnd]] = {}
    for end in ends:
        by_harness.setdefault(end.harness_id, []).append(end)

    for pair in pairs:
        ends_a = _by_cavity(by_harness.get(pair.harness_a, []), pair.connector_a)
        ends_b = _by_cavity(by_harness.get(pair.harness_b, []), pair.connector_b)
        harness_a = complexity.get(pair.harness_a)
        harness_b = complexity.get(pair.harness_b)

        for cavity in sorted(set(ends_a) | set(ends_b), key=_cavity_sort):
            if harness_a is None or harness_b is None:
                missing = [
                    summary_harnesses[h].name
                    for h in (pair.harness_a, pair.harness_b)
                    if h not in complexity and h in summary_harnesses
                ]
                finding = Finding(
                    verdict=UNDETERMINED,
                    connector_a=pair.connector_a,
                    connector_b=pair.connector_b,
                    cavity=cavity,
                    reason=(
                        "No complexity file for "
                        + ", ".join(missing or ["one side"])
                        + ", so applicability cannot be evaluated."
                    ),
                )
            else:
                finding = check_cavity(
                    pair,
                    cavity,
                    ends_a.get(cavity, []),
                    ends_b.get(cavity, []),
                    harness_a,
                    harness_b,
                )
            result.findings.append(finding)
            result.cavities_checked += 1

    result.findings.extend(check_integrity(
        [e for e in ends if e.harness_id in complexity and is_inline(e)], complexity
    ))

    for connector, harness_id in unmated:
        harness = summary_harnesses.get(harness_id)
        result.findings.append(
            Finding(
                verdict=NOT_IN_SUMMARY,
                connector_a=connector,
                harness_a=harness.name if harness else harness_id,
                reason=(
                    f"{connector} is an inline on "
                    f"{harness.name if harness else harness_id}, but its mating "
                    "connector does not appear in the Circuit Summary."
                ),
            )
        )

    logger.info(
        "Inline study: %d cavities, %d findings, %d for review",
        result.cavities_checked, len(result.findings), len(result.review),
    )
    return result


def _cavity_sort(cavity: str):
    """Cavities are numbers written as text; sort them as numbers when possible."""
    try:
        return (0, int(cavity), "")
    except ValueError:
        return (1, 0, cavity)
