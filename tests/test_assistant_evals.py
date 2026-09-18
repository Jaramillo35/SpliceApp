"""The generation evaluation's deterministic half — gated in CI, no model.

The question set must be answerable: every case's reference tool call is run
against the invented corpus and must return the facts the case expects. And
the scorer must tell a good run from a bad one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from secrdb.assistant.evals import aggregate, build_cases, build_corpus, run_cases, to_markdown
from secrdb.assistant.ollama import ChatResponse
from secrdb.assistant.tools import call_tool, tool_names


@pytest.fixture(scope="module")
def corpus():
    return build_corpus(seed=2031)


@pytest.fixture(scope="module")
def db_path(corpus, tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("evals") / "corpus.db"
    corpus.import_into(path)
    return path


@pytest.fixture(scope="module")
def cases(corpus):
    return build_cases(corpus)


def test_the_corpus_is_reproducible_and_invented(corpus):
    again = build_corpus(seed=2031)
    assert [s.secr_number for s in again.secrs] == [s.secr_number for s in corpus.secrs]
    assert build_corpus(seed=7).secrs[0].connectors[0].cnum != corpus.secrs[0].connectors[0].cnum
    assert {s.program for s in corpus.secrs} == {"QX", "ZR"}


def test_the_question_set_is_large_and_covers_every_kind(cases):
    assert len(cases) >= 100
    assert {c.category for c in cases} >= {"circuit", "connector", "connector_pn", "dtcr",
                                           "secr", "dtcr_of_secr", "harness", "program",
                                           "model_year", "database", "absent"}
    assert len({c.id for c in cases}) == len(cases)
    names = set(tool_names())
    assert all(c.reference[0] in names and set(c.accept_tools) <= names for c in cases)
    assert all(c.reference[0] in c.accept_tools for c in cases)


def test_every_reference_call_returns_what_the_case_expects(cases, db_path):
    """The CI gate: a tool change that stops answering a question fails here."""
    wrong = []
    for case in cases:
        result = call_tool(*case.reference, db_path=db_path)
        assert result.ok, f"{case.id}: {result.error}"
        text = json.dumps(result.data, default=str).upper()
        if case.expect_empty:
            if result.data not in (None, [], {}):
                wrong.append((case.id, "expected nothing"))
        else:
            missing = [f for f in case.facts if f.upper() not in text]
            if missing:
                wrong.append((case.id, missing))
    assert not wrong, wrong[:10]


class ReferenceClient:
    """Makes each case's reference call, then answers with the facts."""

    def __init__(self, cases, *, fabricate: bool = False, refuse: bool = False):
        self.by_question = {c.question: c for c in cases}
        self.fabricate, self.refuse = fabricate, refuse

    def chat(self, messages, tools=None, temperature: float = 0.0) -> ChatResponse:
        case = self.by_question[next(m.content for m in messages if m.role == "user")]
        if not any(m.role == "tool" for m in messages):
            name, arguments = case.reference
            return ChatResponse(tool_calls=[{"function": {"name": name, "arguments": arguments}}])
        if self.refuse or case.expect_empty:
            return ChatResponse(content="The database has no record of that.")
        if self.fabricate:
            return ChatResponse(content="That was SECR D99X9ZZ_4242 under DTCR 12345.")
        return ChatResponse(content="Found: " + ", ".join(case.say + case.facts) + ".")


def test_a_reference_run_passes_every_case(cases, db_path):
    scores = run_cases(cases, db_path=db_path, client=ReferenceClient(cases))
    failed = [(s.case_id, s.missing_facts, s.missing_in_answer, s.tools_called)
              for s in scores if not s.passed]
    assert not failed, failed[:5]
    summary = aggregate(scores, model="reference")
    assert summary["rates"]["passed"] == 1.0 and summary["rates"]["args_ok"] == 1.0
    assert set(summary["by_category"]) == {c.category for c in cases}


def test_a_fabricating_model_is_caught(cases, db_path):
    sample = [c for c in cases if c.category == "circuit"][:6]
    scores = run_cases(sample, db_path=db_path, client=ReferenceClient(cases, fabricate=True))
    # the grounding check replaces the fabrication with the evidence summary:
    # the facts are still retrieved, but the model's prose is not kept
    assert all(s.retrieved and not s.prose_kept for s in scores)
    assert "D99X9ZZ_4242" not in " ".join(s.answer for s in scores)


def test_refusing_a_question_that_has_an_answer_fails_it(cases, db_path):
    sample = [c for c in cases if c.category == "dtcr"][:4]
    scores = run_cases(sample, db_path=db_path, client=ReferenceClient(cases, refuse=True))
    assert all(not s.passed and s.retrieved and not s.answered for s in scores)


def test_an_absent_identifier_must_be_refused_not_invented(cases, db_path):
    sample = [c for c in cases if c.category == "absent"]
    good = run_cases(sample, db_path=db_path, client=ReferenceClient(cases))
    assert all(s.passed for s in good)

    class Inventor(ReferenceClient):
        def chat(self, messages, tools=None, temperature: float = 0.0):
            reply = super().chat(messages, tools, temperature)
            if reply.content:
                reply.content = f"It changed in {sample[0].forbidden[0]}."
            return reply

    # The grounding check catches the invention and replaces it with the
    # (empty) evidence summary: the user never sees the made-up SECR, and the
    # score records that the model's own prose did not survive.
    bad = run_cases(sample, db_path=db_path, client=Inventor(cases))
    assert all(not s.prose_kept and s.clean for s in bad)
    assert aggregate(bad)["rates"]["prose_kept"] == 0.0


def test_an_evaluation_does_not_write_to_the_field_diagnostics(cases, db_path, tmp_path, monkeypatch):
    from secrdb import diagnostics
    monkeypatch.setattr(diagnostics, "DATA_DIR", tmp_path / "field")
    run_cases([c for c in cases if c.category == "absent"][:2], db_path=db_path,
              client=ReferenceClient(cases))
    assert diagnostics.DATA_DIR == tmp_path / "field"
    assert not (tmp_path / "field").exists() or not any((tmp_path / "field").iterdir())


def test_the_report_compares_models(cases, db_path):
    sample = cases[:10]
    a = aggregate(run_cases(sample, db_path=db_path, client=ReferenceClient(cases)), "model-a")
    b = aggregate(run_cases(sample, db_path=db_path,
                            client=ReferenceClient(cases, refuse=True)), "model-b")
    text = to_markdown([a, b], seed=2031)
    assert "| model-a | 10 | 100% |" in text and "| model-b | 10 |" in text
    assert "first failures" in text and "seed 2031" in text
