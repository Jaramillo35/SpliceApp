"""The question set, derived from the corpus so its expectations cannot drift.

Each case carries a **reference call** — the tool call a careful engineer
would make — and the facts that call must return. CI runs every reference
call against the corpus, so a question whose expectation is wrong, or a tool
change that stops answering it, fails without a model.

A model is not held to the reference call: ``accept_tools`` lists every tool
that can answer the question, and scoring is mostly about what was
*retrieved* and *said*, not about the route taken.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from secrdb.assistant.evals.corpus import Corpus, absent_identifiers

#: tools that can answer "which SECRs / what changed for this identifier"
_LOOKUP = ("search_secrs",)


@dataclass
class Case:
    id: str
    category: str
    question: str
    reference: Tuple[str, Dict[str, Any]]
    accept_tools: Tuple[str, ...]
    #: strings the retrieved evidence must contain
    facts: List[str] = field(default_factory=list)
    #: strings the final answer must contain
    say: List[str] = field(default_factory=list)
    #: the database holds nothing: the right answer is to say so
    expect_empty: bool = False
    #: strings the answer must not present (e.g. a SECR number offered as a DTCR)
    forbidden: List[str] = field(default_factory=list)


def _phrasings(templates: Tuple[str, ...], **values: str) -> List[str]:
    return [t.format(**values) for t in templates]


def build_cases(corpus: Corpus) -> List[Case]:
    cases: List[Case] = []

    def add(category: str, questions: List[str], reference, accept, **kw) -> None:
        for n, question in enumerate(questions):
            cases.append(Case(id=f"{category}-{len(cases):03d}-{n}", category=category,
                              question=question, reference=reference,
                              accept_tools=tuple(accept), **kw))

    for s in corpus.secrs:
        for c in s.circuits:
            add("circuit", _phrasings((
                "When did circuit {c} change?",
                "Which SECR changed the gauge of {c}, and from what to what?",
            ), c=c.circuit), ("get_changes_by_circuit", {"circuit": c.circuit}),
                ("get_changes_by_circuit",) + _LOOKUP,
                facts=[s.secr_number, c.circuit], say=[s.secr_number])
        for k in s.connectors:
            add("connector", _phrasings((
                "Has connector {k} changed before?",
                "What happened to CNUM {k}?",
            ), k=k.cnum), ("get_changes_by_cnum", {"cnum": k.cnum}),
                ("get_changes_by_cnum", "get_changes_by_endpoint") + _LOOKUP,
                facts=[s.secr_number, k.cnum], say=[s.secr_number])
        add("connector_pn", [f"Which change introduced connector part number {s.connectors[0].new_pn}?"],
            ("get_connector_changes", {"connector_pn": s.connectors[0].new_pn}),
            ("get_connector_changes",) + _LOOKUP,
            facts=[s.secr_number, s.connectors[0].cnum], say=[s.connectors[0].cnum])
        for d in s.dtcrs:
            reference = ("get_changes_by_dtcr", {"dtcr_number": d})
            accept = ("get_changes_by_dtcr",) + _LOOKUP
            # "what did it change" is answered by the objects, not the SECR
            # number — the first model run named the connector and circuits
            # and was marked wrong for leaving the SECR out.
            touched = [k.cnum for k in s.connectors if k.dtcr == d] \
                + [c.circuit for c in s.circuits if c.dtcr == d]
            add("dtcr", [f"What did DTCR {d} change?"], reference, accept,
                facts=[s.secr_number, d] + touched, say=touched[:1])
            add("dtcr", [f"Which SECR implements DTCR {d}?"], reference, accept,
                facts=[s.secr_number, d], say=[s.secr_number])
        add("secr", _phrasings((
            "Summarise SECR {n}.",
            "Which harness family and program is {n} for?",
        ), n=s.secr_number), ("get_secr_summary", {"secr_number": s.secr_number}),
            ("get_secr_summary", "get_changes_by_secr", "get_revision_chain") + _LOOKUP,
            facts=[s.secr_number, s.harness_family, s.program],
            say=[s.harness_family])
        # the confusion the system prompt warns about: DTCRs, not SECR numbers
        add("dtcr_of_secr", [f"Which DTCRs are related to SECR {s.secr_number}?"],
            ("get_secr_summary", {"secr_number": s.secr_number}),
            ("get_secr_summary", "get_changes_by_secr") + _LOOKUP,
            facts=list(s.dtcrs), say=list(s.dtcrs))

    for family in sorted({s.harness_family for s in corpus.secrs}):
        owners = [s.secr_number for s in corpus.secrs if s.harness_family == family]
        add("harness", _phrasings((
            "What has changed on the {f} harness?",
            "List the SECRs that touch harness family {f}.",
        ), f=family), ("get_changes_by_harness", {"harness_family": family}),
            ("get_changes_by_harness",) + _LOOKUP, facts=owners, say=owners[:1])
    for program in sorted({s.program for s in corpus.secrs}):
        add("program", [f"How many SECRs does program {program} have?"],
            ("get_program_summary", {"program": program}),
            ("get_program_summary", "get_change_counts", "get_database_summary") + _LOOKUP,
            facts=[program],
            say=[str(sum(1 for s in corpus.secrs if s.program == program))])
    for year in sorted({s.model_year for s in corpus.secrs}):
        add("model_year", [f"How many SECRs are there for model year {year}?"],
            ("get_model_year_summary", {"model_year": year}),
            ("get_model_year_summary", "get_change_counts", "get_database_summary") + _LOOKUP,
            facts=[year],
            say=[str(sum(1 for s in corpus.secrs if s.model_year == year))])
    add("database", ["What is in this database?", "How many SECRs and changes are stored?"],
        ("get_database_summary", {}), ("get_database_summary", "list_known_values") + _LOOKUP,
        facts=[], say=[str(len(corpus.secrs))])

    circuit, cnum, dtcr = absent_identifiers()
    known = [s.secr_number for s in corpus.secrs]
    add("absent", _phrasings(("When did circuit {c} change?",
                              "Which SECR covers circuit {c}?"), c=circuit),
        ("get_changes_by_circuit", {"circuit": circuit}),
        ("get_changes_by_circuit",) + _LOOKUP, expect_empty=True, forbidden=known)
    add("absent", _phrasings(("Has connector {k} ever changed?",), k=cnum),
        ("get_changes_by_cnum", {"cnum": cnum}),
        ("get_changes_by_cnum", "get_changes_by_endpoint") + _LOOKUP,
        expect_empty=True, forbidden=known)
    add("absent", _phrasings(("What did DTCR {d} change?",), d=dtcr),
        ("get_changes_by_dtcr", {"dtcr_number": dtcr}),
        ("get_changes_by_dtcr",) + _LOOKUP, expect_empty=True, forbidden=known)
    return cases
