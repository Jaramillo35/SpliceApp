"""Tests for the agent loop, driven by a scripted model.

No Ollama and no network: the fake client replays a fixed sequence of
responses, so the loop, the tool dispatch, the grounding fallback and the
issue recording are all exercised deterministically. What a real model would
say is the one thing these tests cannot pin down — and the point of the design
is that it does not matter, because nothing it says is trusted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from secrdb import diagnostics
from secrdb.assistant.agent import Assistant
from secrdb.assistant.ollama import ChatMessage, ChatResponse, OllamaUnavailable
from secrdb.core.secr.importer import import_secr_files

from tests.secr_fixtures import build_secr_workbook


@pytest.fixture(autouse=True)
def isolated_diagnostics(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(diagnostics, "DATA_DIR", tmp_path / "diag")


@pytest.fixture()
def populated(tmp_path: Path) -> Path:
    db_path = tmp_path / "agent.db"
    import_secr_files(
        [("ip.xlsx", build_secr_workbook(secr_number="D50319A", harness_family="IP"))],
        db_path=db_path,
    )
    return db_path


class ScriptedClient:
    """Replays canned model turns and records what it was sent."""

    def __init__(self, script: List[ChatResponse], raises: Optional[Exception] = None):
        self.script = list(script)
        self.raises = raises
        self.calls: List[List[ChatMessage]] = []

    def chat(self, messages, tools=None, temperature: float = 0.0) -> ChatResponse:
        if self.raises:
            raise self.raises
        self.calls.append(list(messages))
        if not self.script:
            return ChatResponse(content="(no more script)")
        return self.script.pop(0)


def _tool_call(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    return {"function": {"name": name, "arguments": arguments}}


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------

def test_a_tool_is_called_and_its_rows_become_evidence(populated: Path) -> None:
    client = ScriptedClient(
        [
            ChatResponse(
                tool_calls=[_tool_call("get_changes_by_circuit", {"circuit": "A937F"})]
            ),
            ChatResponse(
                content=(
                    "Circuit A937F changed in SECR D50319A (RU, MY2028, IP) "
                    "under DTCR 49919: DEF GAUGE 0.35 -> 0.50."
                )
            ),
        ]
    )

    answer = Assistant(client=client, db_path=populated).ask("when did A937F change?")

    assert answer.ok
    assert answer.rounds == 2
    assert answer.grounded and not answer.fallback_used
    assert "D50319A" in answer.answer
    assert answer.evidence[0].name == "get_changes_by_circuit"
    assert answer.rows and answer.rows[0]["object_id"] == "A937F"


def test_the_system_prompt_and_question_are_sent(populated: Path) -> None:
    client = ScriptedClient([ChatResponse(content="No records found.")])
    Assistant(client=client, db_path=populated).ask("what is in the database?")

    sent = client.calls[0]
    assert sent[0].role == "system"
    assert "Answer ONLY from the tools" in sent[0].content
    assert sent[1].role == "user"
    assert sent[1].content == "what is in the database?"


def test_tool_results_are_fed_back_to_the_model(populated: Path) -> None:
    client = ScriptedClient(
        [
            ChatResponse(tool_calls=[_tool_call("list_known_values", {})]),
            ChatResponse(content="The database covers program RU."),
        ]
    )
    Assistant(client=client, db_path=populated).ask("which programs?")

    second_turn = client.calls[1]
    assert second_turn[-1].role == "tool"
    assert second_turn[-1].tool_name == "list_known_values"
    assert "RU" in second_turn[-1].content


def test_several_rounds_of_tools_are_allowed(populated: Path) -> None:
    client = ScriptedClient(
        [
            ChatResponse(tool_calls=[_tool_call("list_known_values", {})]),
            ChatResponse(
                tool_calls=[_tool_call("get_changes_by_harness", {"harness_family": "IP"})]
            ),
            ChatResponse(content="The IP harness has changes in SECR D50319A."),
        ]
    )

    answer = Assistant(client=client, db_path=populated).ask("what changed on IP?")

    assert answer.rounds == 3
    assert [item.name for item in answer.evidence] == [
        "list_known_values",
        "get_changes_by_harness",
    ]


def test_a_bad_tool_call_is_reported_back_and_recovered_from(
    populated: Path,
) -> None:
    """The model invents a tool, is told so, and tries again."""
    client = ScriptedClient(
        [
            ChatResponse(tool_calls=[_tool_call("get_everything", {})]),
            ChatResponse(
                tool_calls=[_tool_call("get_changes_by_circuit", {"circuit": "A937F"})]
            ),
            ChatResponse(content="Circuit A937F changed in SECR D50319A."),
        ]
    )

    answer = Assistant(client=client, db_path=populated).ask("A937F?")

    assert not answer.evidence[0].ok
    assert "no tool called" in answer.evidence[0].error
    assert answer.ok and answer.grounded
    assert "D50319A" in answer.answer


def test_running_out_of_rounds_still_answers_from_evidence(populated: Path) -> None:
    client = ScriptedClient(
        [
            ChatResponse(tool_calls=[_tool_call("get_changes_by_circuit", {"circuit": "A937F"})])
            for _ in range(10)
        ]
    )

    answer = Assistant(client=client, db_path=populated, max_rounds=3).ask("A937F?")

    assert answer.rounds == 3
    assert answer.fallback_used
    assert "change record" in answer.answer


# ---------------------------------------------------------------------------
# Grounding
# ---------------------------------------------------------------------------

def test_a_fabricated_answer_is_replaced_by_the_evidence(populated: Path) -> None:
    """The whole point: an invented SECR number never reaches the engineer."""
    client = ScriptedClient(
        [
            ChatResponse(
                tool_calls=[_tool_call("get_changes_by_circuit", {"circuit": "A937F"})]
            ),
            ChatResponse(content="Circuit A937F was changed in SECR D77777Z."),
        ]
    )

    answer = Assistant(client=client, db_path=populated).ask("A937F?")

    assert not answer.grounded
    assert answer.fallback_used
    assert "D77777Z" not in answer.answer          # the fabrication is gone
    assert "D50319A" in answer.answer              # the real SECR is there
    assert "was discarded" in answer.answer
    # ...but it is still captured for the issue report and the debug panel.
    assert answer.grounding_report is not None
    assert "D77777Z" in answer.grounding_report.ungrounded


def test_saying_there_is_no_record_is_allowed(populated: Path) -> None:
    client = ScriptedClient(
        [
            ChatResponse(
                tool_calls=[_tool_call("get_changes_by_circuit", {"circuit": "ZZ999"})]
            ),
            ChatResponse(content="The database has no record of circuit ZZ999."),
        ]
    )

    answer = Assistant(client=client, db_path=populated).ask("when did ZZ999 change?")

    assert answer.grounded
    assert not answer.fallback_used
    assert "no record" in answer.answer


# ---------------------------------------------------------------------------
# Failures
# ---------------------------------------------------------------------------

def test_an_unreachable_model_returns_an_answer_object(populated: Path) -> None:
    client = ScriptedClient([], raises=OllamaUnavailable("Ollama is not running"))

    answer = Assistant(client=client, db_path=populated).ask("anything?")

    assert not answer.ok
    assert "not running" in answer.error
    assert answer.answer == ""  # nothing invented in place of an answer


def test_an_empty_question_is_refused(populated: Path) -> None:
    answer = Assistant(client=ScriptedClient([]), db_path=populated).ask("   ")
    assert not answer.ok
    assert "Ask a question" in answer.error


# ---------------------------------------------------------------------------
# Issue recording
# ---------------------------------------------------------------------------

def test_a_question_with_no_records_is_recorded(populated: Path) -> None:
    client = ScriptedClient(
        [
            ChatResponse(
                tool_calls=[_tool_call("get_changes_by_circuit", {"circuit": "ZZ999"})]
            ),
            ChatResponse(content="No record of ZZ999."),
        ]
    )

    Assistant(client=client, db_path=populated).ask("when did ZZ999 change?")

    recorded = diagnostics.load_issues()
    assert len(recorded) == 1
    assert recorded[0]["kind"] == diagnostics.KIND_UNANSWERED
    assert "ZZ999" in recorded[0]["summary"]
    assert recorded[0]["context"]["tools_called"][0]["name"] == "get_changes_by_circuit"


def test_a_failed_grounding_check_is_recorded(populated: Path) -> None:
    client = ScriptedClient(
        [
            ChatResponse(
                tool_calls=[_tool_call("get_changes_by_circuit", {"circuit": "A937F"})]
            ),
            ChatResponse(content="Changed in SECR D77777Z."),
        ]
    )

    Assistant(client=client, db_path=populated).ask("A937F?")

    recorded = diagnostics.load_issues()
    assert recorded[0]["kind"] == diagnostics.KIND_UNANSWERED
    assert "grounding" in recorded[0]["detail"]


def test_an_unreachable_model_is_recorded(populated: Path) -> None:
    client = ScriptedClient([], raises=OllamaUnavailable("Ollama is not running"))
    Assistant(client=client, db_path=populated).ask("anything?")

    recorded = diagnostics.load_issues()
    assert recorded[0]["kind"] == diagnostics.KIND_UNANSWERED
    assert "not running" in recorded[0]["detail"]


def test_a_good_answer_is_not_recorded_as_a_problem(populated: Path) -> None:
    client = ScriptedClient(
        [
            ChatResponse(
                tool_calls=[_tool_call("get_changes_by_circuit", {"circuit": "A937F"})]
            ),
            ChatResponse(content="Circuit A937F changed in SECR D50319A."),
        ]
    )

    Assistant(client=client, db_path=populated).ask("A937F?")

    assert diagnostics.load_issues() == []


def test_a_mislabelled_answer_is_replaced_and_explained_accurately(
    populated: Path,
) -> None:
    """From a field report: SECR numbers presented under a "DTCRs" heading.

    They exist in the evidence, so this is not fabrication — and the note the
    engineer reads must not claim the records were "not retrieved", because
    they were.
    """
    client = ScriptedClient(
        [
            ChatResponse(
                tool_calls=[_tool_call("get_changes_by_circuit", {"circuit": "A937F"})]
            ),
            ChatResponse(content="Circuit A937F relates to DTCRs D50319A."),
        ]
    )

    answer = Assistant(client=client, db_path=populated).ask("which DTCRs for A937F?")

    assert not answer.grounded
    assert answer.fallback_used
    assert answer.grounding_report.misattributed
    assert answer.grounding_report.ungrounded == []
    # D50319A is a real SECR, so the summary rightly lists it *as a SECR* —
    # what must not survive is its use as a DTCR.
    dtcr_section = answer.answer.split("DTCRs:")[1].split(".")[0]
    assert "D50319A" not in dtcr_section
    assert "49919" in dtcr_section
    assert "labelled a value as something it is not" in answer.answer
    assert "not retrieved" not in answer.answer


def test_a_cold_start_is_flagged_so_the_ui_can_say_so(populated: Path) -> None:
    """A slow first answer is not a broken install, and must not read as one."""
    from secrdb.assistant.ollama import OllamaTimeout

    client = ScriptedClient([], raises=OllamaTimeout("still loading the model"))

    answer = Assistant(client=client, db_path=populated).ask("anything?")

    assert not answer.ok
    assert answer.timed_out
    assert answer.answer == ""


def test_an_ordinary_failure_is_not_flagged_as_a_timeout(populated: Path) -> None:
    client = ScriptedClient([], raises=OllamaUnavailable("Ollama is not running"))

    answer = Assistant(client=client, db_path=populated).ask("anything?")

    assert not answer.ok and not answer.timed_out
