"""Tests for the assistant's tool layer.

These run without Ollama: the tool layer is deliberately independent of the
model, so retrieval can be verified on its own and a prompt change can never
silently break it.

The database is built from real SECR workbook fixtures and thrown away.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from secrdb.assistant import tools as tool_layer
from secrdb.assistant.tools import (
    MAX_ROWS,
    TOOLS,
    call_tool,
    tool_names,
    tool_specs,
)
from secrdb.core.secr.importer import import_secr_files

from tests.secr_fixtures import build_secr_workbook


@pytest.fixture()
def populated(tmp_path: Path) -> Path:
    """A database with two SECRs on different harness families."""
    db_path = tmp_path / "assistant.db"
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


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

def test_every_tool_exposes_a_valid_spec() -> None:
    specs = tool_specs()
    assert len(specs) == len(TOOLS)
    for spec in specs:
        assert spec["type"] == "function"
        function = spec["function"]
        assert function["name"] in TOOLS
        assert function["description"].strip()
        parameters = function["parameters"]
        assert parameters["type"] == "object"
        assert parameters["additionalProperties"] is False
        for name, prop in parameters["properties"].items():
            assert prop.get("type"), f"{function['name']}.{name} has no type"
            assert prop.get("description"), f"{function['name']}.{name} undocumented"


def test_specs_are_json_serialisable() -> None:
    """They are posted to Ollama as JSON, so they must survive a round trip."""
    assert json.loads(json.dumps(tool_specs())) == tool_specs()


def test_schema_matches_the_handler_signature() -> None:
    """A schema that advertises an argument the handler cannot take would fail
    only at call time, once the model happened to use it."""
    for name, tool in TOOLS.items():
        signature = inspect.signature(tool.handler)
        accepted = set(signature.parameters)
        for argument in tool.parameters["properties"]:
            assert argument in accepted, f"{name} advertises unknown arg {argument!r}"
        for argument in tool.parameters["required"]:
            assert argument in accepted, f"{name} requires unknown arg {argument!r}"
        assert "db_path" in accepted, f"{name} cannot be pointed at a database"


def test_required_arguments_have_no_default() -> None:
    for name, tool in TOOLS.items():
        signature = inspect.signature(tool.handler)
        for argument in tool.parameters["required"]:
            parameter = signature.parameters[argument]
            assert parameter.default is inspect.Parameter.empty, (
                f"{name}.{argument} is required but defaulted"
            )


def test_the_surface_is_read_only() -> None:
    """No tool may write, delete or execute SQL."""
    forbidden = ("save", "delete", "import", "insert", "update_", "execute", "sql")
    for name, tool in TOOLS.items():
        assert not any(word in name for word in forbidden), name
        source = inspect.getsource(tool.handler).lower()
        for statement in ("insert into", "delete from", "drop table", "update "):
            assert statement not in source, f"{name} appears to write: {statement}"


# ---------------------------------------------------------------------------
# Dispatch guards
# ---------------------------------------------------------------------------

def test_unknown_tool_is_reported_not_raised(populated: Path) -> None:
    result = call_tool("get_everything", {}, db_path=populated)
    assert not result.ok
    assert "no tool called" in result.error
    assert "search_secrs" in result.error  # tells the model what it can use


def test_unexpected_argument_is_reported(populated: Path) -> None:
    result = call_tool(
        "get_changes_by_circuit",
        {"circuit": "A937F", "colour": "red"},
        db_path=populated,
    )
    assert not result.ok
    assert "colour" in result.error


def test_missing_required_argument_is_reported(populated: Path) -> None:
    result = call_tool("get_changes_by_circuit", {}, db_path=populated)
    assert not result.ok
    assert "requires circuit" in result.error


def test_a_failing_handler_is_reported_not_raised(populated: Path) -> None:
    result = call_tool("get_change_counts", {"top_n": "lots"}, db_path=populated)
    assert result.ok  # top_n is clamped rather than fatal
    assert result.data["totals"]["changes"] > 0


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def test_circuit_lookup_answers_the_motivating_question(populated: Path) -> None:
    """'When did circuit A937F change?' must come back with the SECR, the
    program/model year, the DTCR and the old and new values."""
    result = call_tool(
        "get_changes_by_circuit", {"circuit": "A937F"}, db_path=populated
    )

    assert result.ok and result.row_count
    row = result.data[0]
    for key in (
        "secr_number",
        "program",
        "model_year",
        "harness_family",
        "action",
        "old_value",
        "new_value",
        "dtcr_number",
    ):
        assert key in row, key
    assert row["object_id"] == "A937F"


def test_a_circuit_prefix_finds_the_suffixed_circuit(populated: Path) -> None:
    result = call_tool("get_changes_by_circuit", {"circuit": "A937"}, db_path=populated)
    assert result.ok
    assert {row["object_id"] for row in result.data} == {"A937F"}


def test_cnum_lookup_returns_both_connector_roles(populated: Path) -> None:
    """The connector's own changes, plus the circuits that land on it."""
    result = call_tool("get_changes_by_cnum", {"cnum": "D2784J"}, db_path=populated)
    assert result.ok and result.row_count

    by_role = {row["connector_role"] for row in result.data}
    assert by_role <= {"connector", "endpoint"}
    for row in result.data:
        if row["connector_role"] == "connector":
            assert row["object_type"] == "connector"
        else:
            # The object is the circuit; the connector is where it terminates.
            assert row["object_type"] == "circuit"
            assert row["endpoint_side"] in {"FROM", "TO"}


def test_endpoint_lookup_finds_circuits_landing_on_a_connector(
    populated: Path,
) -> None:
    result = call_tool(
        "get_changes_by_endpoint", {"connector": "D2784J"}, db_path=populated
    )
    assert result.ok and result.row_count
    assert all(row["object_type"] == "circuit" for row in result.data)
    assert all(
        "D2784J" in (str(row.get("from_dnum")), str(row.get("to_dnum")))
        for row in result.data
    )


def test_known_values_lists_the_real_vocabulary(populated: Path) -> None:
    result = call_tool("list_known_values", {}, db_path=populated)
    assert result.ok
    assert set(result.data["harness_family"]) == {"IP", "BODY_LEFT"}
    assert "PN CHANGE" in result.data["change_type"]


def test_counts_answer_most_and_how_many(populated: Path) -> None:
    result = call_tool("get_change_counts", {}, db_path=populated)
    assert result.ok
    assert result.data["totals"]["secrs"] == 2
    assert result.data["harness_family"]


def test_summary_and_changes_agree_for_one_secr(populated: Path) -> None:
    summary = call_tool(
        "get_secr_summary", {"secr_number": "D50319A"}, db_path=populated
    )
    changes = call_tool(
        "get_changes_by_secr", {"secr_number": "D50319A"}, db_path=populated
    )
    assert summary.ok and changes.ok
    assert summary.data["change_count"] == changes.row_count


def test_a_question_with_no_answer_returns_empty_not_an_error(
    populated: Path,
) -> None:
    """The model must be able to say 'no record of that' — an empty result is
    an answer, not a failure."""
    result = call_tool(
        "get_changes_by_circuit", {"circuit": "ZZ999"}, db_path=populated
    )
    assert result.ok
    assert result.data == []
    assert result.row_count == 0


def test_unknown_secr_summary_is_null_not_an_error(populated: Path) -> None:
    result = call_tool(
        "get_secr_summary", {"secr_number": "NOT-A-SECR"}, db_path=populated
    )
    assert result.ok
    assert result.data is None


# ---------------------------------------------------------------------------
# Payload safety
# ---------------------------------------------------------------------------

def test_results_never_contain_binary_or_unserialisable_values(
    populated: Path,
) -> None:
    """Stored workbooks are blobs; they must never reach the model."""
    for name, arguments in (
        ("get_secr_summary", {"secr_number": "D50319A"}),
        ("get_changes_by_secr", {"secr_number": "D50319A"}),
        ("search_secrs", {"query": "D2784J"}),
        ("get_database_summary", {}),
    ):
        result = call_tool(name, arguments, db_path=populated)
        assert result.ok, f"{name}: {result.error}"
        json.dumps(result.to_model_payload())  # raises if anything is unsafe


def test_row_limits_are_capped_and_declared(populated: Path, monkeypatch) -> None:
    monkeypatch.setattr(tool_layer, "MAX_ROWS", 2)
    result = call_tool(
        "get_changes_by_secr", {"secr_number": "D50319A"}, db_path=populated
    )
    assert result.truncated
    assert result.row_count == 2
    payload = result.to_model_payload()
    assert payload["truncated"] is True
    assert "Narrow the question" in payload["note"]


def test_limit_argument_cannot_exceed_the_hard_cap(populated: Path) -> None:
    result = call_tool(
        "get_changes_by_harness",
        {"harness_family": "IP", "limit": 10_000},
        db_path=populated,
    )
    assert result.ok
    assert result.row_count <= MAX_ROWS


def test_error_payloads_reach_the_model(populated: Path) -> None:
    payload = call_tool("nope", {}, db_path=populated).to_model_payload()
    assert "error" in payload and payload["error"]


def test_a_tool_that_answers_with_a_mapping_reports_what_it_returned(
    populated: Path,
) -> None:
    """Reporting 0 rows for a working tool is a false lead in an issue report.

    ``list_known_values`` answers with a mapping, not rows. It used to report
    row_count 0 even when full, which made a tool that worked look like a tool
    that returned nothing — and cost a real investigation.
    """
    result = call_tool("list_known_values", {}, db_path=populated)

    assert result.ok and result.data
    assert result.row_count > 0
    assert result.row_count == sum(
        len(value) if isinstance(value, (list, dict)) else 1
        for value in result.data.values()
    )


def test_an_empty_database_still_reports_zero(tmp_path: Path) -> None:
    """The count must reflect content, not merely that a dict came back."""
    result = call_tool("list_known_values", {}, db_path=tmp_path / "empty.db")

    assert result.ok
    assert result.row_count == 0
