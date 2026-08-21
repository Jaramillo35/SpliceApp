"""M5 — the evaluation set.

The questions engineers actually ask, each pinned to the records that must come
back. These check **retrieval**, not phrasing: given the right tool call, does
the database return the right rows? That separation is deliberate. Phrasing
depends on the model and will drift between versions; retrieval is ours, is
deterministic, and is what an answer's correctness rests on.

So this suite runs with no model and no network, and a prompt change can never
make it pass or fail. When a field report says "it got this wrong", the first
move is to add the question here and see whether retrieval or wording was at
fault.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from secrdb.assistant.grounding import check, summarise_evidence
from secrdb.assistant.tools import call_tool
from secrdb.core.secr.importer import import_secr_files

from tests.secr_fixtures import build_secr_workbook


@pytest.fixture(scope="module")
def corpus(tmp_path_factory) -> Path:
    """A small database spanning two harness families and two model years."""
    db_path = tmp_path_factory.mktemp("evaluation") / "corpus.db"
    import_secr_files(
        [
            ("ip.xlsx", build_secr_workbook(secr_number="D50319A", harness_family="IP")),
            (
                "body.xlsx",
                build_secr_workbook(
                    secr_number="D49957A",
                    harness_family="BODY_LEFT",
                    model_year="2027",
                ),
            ),
        ],
        db_path=db_path,
    )
    return db_path


def _rows(name: str, arguments: Dict[str, Any], db_path: Path) -> List[Dict[str, Any]]:
    result = call_tool(name, arguments, db_path=db_path)
    assert result.ok, f"{name} failed: {result.error}"
    return result.data if isinstance(result.data, list) else []


# ---------------------------------------------------------------------------
# The question set
#
# (question, tool, arguments, what the answer must contain)
# ---------------------------------------------------------------------------

EVALUATION_SET = [
    (
        "When did circuit A937F change?",
        "get_changes_by_circuit",
        {"circuit": "A937F"},
        {"secr_number": "D50319A", "object_id": "A937F"},
    ),
    (
        "Has connector D2784J changed before?",
        "get_changes_by_cnum",
        {"cnum": "D2784J"},
        {"object_type": "connector", "object_id": "D2784J"},
    ),
    (
        "What changed in SECR D50319A?",
        "get_changes_by_secr",
        {"secr_number": "D50319A"},
        {"secr_number": "D50319A"},
    ),
    (
        "What did DTCR 49919 change?",
        "get_changes_by_dtcr",
        {"dtcr_number": "49919"},
        {"dtcr_number": "49919"},
    ),
    (
        "What changed on the IP harness?",
        "get_changes_by_harness",
        {"harness_family": "IP"},
        {"harness_family": "IP"},
    ),
    (
        "Where was part number D4Z080-000-B introduced?",
        "get_connector_changes",
        {"connector_pn": "D4Z080-000-B"},
        {"object_type": "connector"},
    ),
]


@pytest.mark.parametrize(
    "question, tool, arguments, expected",
    EVALUATION_SET,
    ids=[item[0] for item in EVALUATION_SET],
)
def test_the_question_retrieves_the_right_records(
    question: str,
    tool: str,
    arguments: Dict[str, Any],
    expected: Dict[str, Any],
    corpus: Path,
) -> None:
    rows = _rows(tool, arguments, corpus)

    assert rows, f"{question!r} retrieved nothing"
    for key, value in expected.items():
        assert any(str(row.get(key)) == value for row in rows), (
            f"{question!r}: no row where {key}={value!r}"
        )


@pytest.mark.parametrize(
    "question, tool, arguments, expected",
    EVALUATION_SET,
    ids=[item[0] for item in EVALUATION_SET],
)
def test_a_templated_answer_is_grounded_in_what_was_retrieved(
    question: str,
    tool: str,
    arguments: Dict[str, Any],
    expected: Dict[str, Any],
    corpus: Path,
) -> None:
    """The fallback answer for every question must pass the grounding check.

    If the fallback itself could not be verified, a failed check would leave
    the engineer with nothing.
    """
    rows = _rows(tool, arguments, corpus)
    answer = summarise_evidence(rows)

    report = check(answer, rows, question=question)
    assert report.grounded, f"{question!r}: {report.reason}"


# ---------------------------------------------------------------------------
# Questions with no answer
# ---------------------------------------------------------------------------

UNKNOWN_SET = [
    ("When did circuit ZZ999 change?", "get_changes_by_circuit", {"circuit": "ZZ999"}),
    ("Has connector QQ111 changed?", "get_changes_by_cnum", {"cnum": "QQ111"}),
    ("What changed in SECR D00000X?", "get_changes_by_secr", {"secr_number": "D00000X"}),
    ("What did DTCR 99999 change?", "get_changes_by_dtcr", {"dtcr_number": "99999"}),
]


@pytest.mark.parametrize(
    "question, tool, arguments", UNKNOWN_SET, ids=[item[0] for item in UNKNOWN_SET]
)
def test_an_unknown_thing_retrieves_nothing_rather_than_something_wrong(
    question: str, tool: str, arguments: Dict[str, Any], corpus: Path
) -> None:
    """Returning a near-miss would be worse than returning nothing."""
    assert _rows(tool, arguments, corpus) == []


@pytest.mark.parametrize(
    "question, tool, arguments", UNKNOWN_SET, ids=[item[0] for item in UNKNOWN_SET]
)
def test_the_honest_no_answer_passes_the_grounding_check(
    question: str, tool: str, arguments: Dict[str, Any], corpus: Path
) -> None:
    rows = _rows(tool, arguments, corpus)
    answer = summarise_evidence(rows)

    assert "No matching records" in answer
    assert check(answer, rows, question=question).grounded


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------

def test_which_harness_family_has_the_most_changes(corpus: Path) -> None:
    result = call_tool("get_change_counts", {}, db_path=corpus)

    assert result.ok
    families = result.data["harness_family"]
    assert families, "no harness-family breakdown"
    assert families[0]["n"] >= families[-1]["n"]  # ordered by count
    assert {entry["name"] for entry in families} == {"IP", "BODY_LEFT"}


def test_how_many_secrs_are_in_the_database(corpus: Path) -> None:
    result = call_tool("get_change_counts", {}, db_path=corpus)
    assert result.data["totals"]["secrs"] == 2


def test_the_vocabulary_is_available_for_binding_names(corpus: Path) -> None:
    """'the IP harness' has to resolve to a value that exists."""
    result = call_tool("list_known_values", {}, db_path=corpus)
    assert "IP" in result.data["harness_family"]
    assert "2027" in result.data["model_year"]


def test_a_filtered_count_narrows(corpus: Path) -> None:
    everything = call_tool("get_change_counts", {}, db_path=corpus)
    just_ip = call_tool("get_change_counts", {"harness_family": "IP"}, db_path=corpus)

    assert just_ip.data["totals"]["secrs"] == 1
    assert just_ip.data["totals"]["changes"] < everything.data["totals"]["changes"]


# ---------------------------------------------------------------------------
# Cross-checks
# ---------------------------------------------------------------------------

def test_every_evaluation_question_uses_a_real_tool() -> None:
    """Guards against the set drifting away from the tool surface."""
    from secrdb.assistant.tools import TOOLS

    for _, tool, arguments, _ in EVALUATION_SET:
        assert tool in TOOLS, tool
        allowed = set(TOOLS[tool].parameters["properties"])
        assert set(arguments) <= allowed, f"{tool} cannot take {set(arguments) - allowed}"


def test_retrieval_agrees_across_routes(corpus: Path) -> None:
    """The same change reached two ways must be the same change.

    A937F is touched by both SECRs in the corpus, so only the rows belonging to
    D50319A are comparable — which is itself the point: a circuit lookup spans
    SECRs, a SECR lookup does not.
    """
    by_secr = _rows("get_changes_by_secr", {"secr_number": "D50319A"}, corpus)
    by_circuit = _rows("get_changes_by_circuit", {"circuit": "A937F"}, corpus)

    from_this_secr = {
        row["id"] for row in by_circuit if row.get("secr_number") == "D50319A"
    }
    assert from_this_secr
    assert from_this_secr <= {row["id"] for row in by_secr}
    # ...and the circuit really does appear in more than one SECR.
    assert {row.get("secr_number") for row in by_circuit} == {"D50319A", "D49957A"}
