"""What is missing, why the engine needs it, and what it blocks.

The requirement is that nothing is silently ignored, which means an absence has
to become a result rather than the lack of one. Every gap is reported in three
parts so an engineer can act on it without reading the code.
"""

from __future__ import annotations

from typing import Dict, List, Set

from splice.inline.model import Gap, Harness

BLOCKING = "blocking"
ADVISORY = "advisory"


def assess(
    summary_harnesses: Dict[str, Harness],
    complexity: Dict[str, Harness],
    out_of_scope: Set[str] | None = None,
) -> List[Gap]:
    """Check the inputs against each other before any validation runs."""
    out_of_scope = out_of_scope or set()
    gaps: List[Gap] = []

    for def_id, harness in sorted(summary_harnesses.items()):
        if harness.name in out_of_scope:
            gaps.append(
                Gap(
                    what=f"{harness.name} ({def_id}) is excluded from the study",
                    why="Marked out of scope in the app, not missing data",
                    affects="Its inline connectors are not checked",
                    severity=ADVISORY,
                )
            )
            continue
        if def_id not in complexity:
            gaps.append(
                Gap(
                    what=f"No complexity file for {harness.name} ({def_id})",
                    why=(
                        "Applicability cannot be evaluated without the builds the "
                        "harness ships as"
                    ),
                    affects=f"Every inline on {harness.name} is Undetermined",
                    severity=BLOCKING,
                )
            )

    used = {d for d, h in summary_harnesses.items() if h.name not in out_of_scope}
    for def_id, harness in sorted(complexity.items()):
        if def_id not in summary_harnesses:
            gaps.append(
                Gap(
                    what=f"Complexity {def_id} matches no harness in the summary",
                    why="Supplied but unused — often a previous phase",
                    affects="Nothing; reported so the set of inputs is accounted for",
                    severity=ADVISORY,
                )
            )
    return gaps


def duplicate_complexity(files: List[Harness]) -> List[Gap]:
    """Two complexity files claiming one DEF id.

    The collection script harvests by filename, so duplicates reappear even
    after a folder is tidied. Two of them differed by a sales code in the sample
    release, which changes results — so this is never resolved silently.
    """
    by_id: Dict[str, List[Harness]] = {}
    for harness in files:
        by_id.setdefault(harness.def_id, []).append(harness)

    gaps: List[Gap] = []
    for def_id, group in sorted(by_id.items()):
        if len(group) < 2:
            continue
        identical = len({frozenset(b.codes) for h in group for b in h.builds}) == len(
            {b.part_number for b in group[0].builds}
        ) and all(
            {(b.part_number, b.codes) for b in group[0].builds}
            == {(b.part_number, b.codes) for b in other}
            for other in [h.builds for h in group[1:]]
        )
        names = ", ".join(h.complexity_file or h.name for h in group)
        gaps.append(
            Gap(
                what=f"{len(group)} complexity files declare ID={def_id}",
                why=(
                    "They agree, so either can be used"
                    if identical
                    else "They disagree, so the choice changes the results"
                ),
                affects=names,
                severity=ADVISORY if identical else BLOCKING,
            )
        )
    return gaps
