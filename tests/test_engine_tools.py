"""Engine tools: the assistant running the tested engines on workspace files."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from secrdb import diagnostics
from secrdb.assistant.agent import Assistant
from secrdb.assistant.engine_tools import ENGINE_PROMPT, engine_tools
from secrdb.assistant.ollama import ChatResponse
from secrdb.assistant.tools import call_tool, tool_names, tool_specs


@pytest.fixture(scope="module")
def workspace(tmp_path_factory) -> Path:
    from demo import showcase
    out = tmp_path_factory.mktemp("showcase")
    showcase.build(out)
    ws = tmp_path_factory.mktemp("workspace")
    for f in (out / "4_dtx_compare").glob("*.xlsx"):
        shutil.copy(f, ws / f.name)
    (ws / "notes.txt").write_text("not a workbook")
    return ws


@pytest.fixture()
def tools(workspace):
    return engine_tools(workspace)


def _names(workspace):
    files = {f["kind"]: f["file"] for f in
             call_tool("list_workspace_files", {}, registry=engine_tools(workspace)).data}
    old = next(p.name for p in workspace.glob("*_OLD.xlsx"))
    new = next(p.name for p in workspace.glob("*_NEW.xlsx"))
    return old, new, files["DTCR report"]


def test_the_workspace_lists_files_by_kind(tools, workspace):
    result = call_tool("list_workspace_files", {}, registry=tools)
    kinds = {f["file"]: f["kind"] for f in result.data}
    assert set(kinds.values()) == {"DTx export", "DTCR report", "other"}
    assert all("/" not in name for name in kinds)


def test_a_tool_takes_a_file_name_never_a_path(tools, workspace):
    for bad in ("../secret.xlsx", str(workspace / "x.xlsx"), ""):
        result = call_tool("describe_dtx", {"file": bad or " "}, registry=tools)
        assert not result.ok
    result = call_tool("describe_dtx", {"file": "missing.xlsx"}, registry=tools)
    assert "No file 'missing.xlsx'" in result.error and "_OLD.xlsx" in result.error


def test_a_dtx_is_described_from_its_own_title_block(tools, workspace):
    old, _new, _dtcr = _names(workspace)
    d = call_tool("describe_dtx", {"file": old}, registry=tools).data
    assert d["phase"] == "V1_A" and d["circuits"] > 0 and d["harness_families"]


def test_the_compare_finds_the_planted_circuits(tools, workspace):
    old, new, _dtcr = _names(workspace)
    r = call_tool("compare_dtx_exports", {"old_file": old, "new_file": new}, registry=tools)
    assert r.ok, r.error
    assert r.data["counts"]["added_circuit_count"] == 2          # QK106 and QK702
    circuits = {row["Circuit Name"] for row in r.data["changes"]}
    assert {"QK106", "QK702"} <= circuits
    family = r.data["changes"][0]["Harness Family"]
    one = call_tool("compare_dtx_exports", {"old_file": old, "new_file": new,
                                            "harness_family": family.lower()}, registry=tools)
    assert {row["Harness Family"] for row in one.data["changes"]} == {family}


def test_a_circuit_and_a_connector_are_found_with_their_pins(tools, workspace):
    _old, new, _dtcr = _names(workspace)
    rows = call_tool("find_circuit", {"file": new, "circuit": "QK106"}, registry=tools).data
    assert rows and all(r["circuit"].startswith("QK106") and r["cnum"] and r["pin"] for r in rows)
    at = call_tool("find_connector", {"file": new, "cnum": rows[0]["cnum"].lower()},
                   registry=tools).data
    assert any(r["circuit"] == rows[0]["circuit"] for r in at)
    assert call_tool("find_circuit", {"file": new, "circuit": "ZZ999"}, registry=tools).data == []


def test_dtcrs_are_matched_to_connectors_and_families(tools, workspace):
    old, new, dtcr = _names(workspace)
    r = call_tool("match_dtcrs", {"old_file": old, "new_file": new, "dtcr_file": dtcr},
                  registry=tools)
    assert r.ok, r.error
    assert r.data["dtcrs"] == r.data["matched"] > 0 and r.data["unmatched"] == 0
    assert all(row["CNUM"] and row["Harness Family"] for row in r.data["rows"])


def test_the_engine_tools_are_a_separate_registry(tools):
    assert "compare_dtx_exports" not in tool_names(), "the SECR assistant's prompt is unchanged"
    assert "search_secrs" not in tool_names(tools)
    assert len(tool_specs(tools)) == 6
    result = call_tool("search_secrs", {"query": "x"}, registry=tools)
    assert "no tool called" in result.error and "compare_dtx_exports" in result.error


def test_an_assistant_given_engine_tools_runs_them(tools, workspace, tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "DATA_DIR", tmp_path / "diag")
    old, new, _dtcr = _names(workspace)

    class Scripted:
        def __init__(self):
            self.seen = []

        def chat(self, messages, tools=None, temperature: float = 0.0):
            self.seen.append((messages[0].content, [t["function"]["name"] for t in tools]))
            if not any(m.role == "tool" for m in messages):
                return ChatResponse(tool_calls=[{"function": {
                    "name": "compare_dtx_exports",
                    "arguments": {"old_file": old, "new_file": new}}}])
            return ChatResponse(content="Two circuits were added: QK106 and QK702.")

    client = Scripted()
    answer = Assistant(client=client, tools=tools, system_prompt=ENGINE_PROMPT) \
        .ask("What changed between the two exports?")
    assert answer.ok and answer.tool_calls[0]["name"] == "compare_dtx_exports"
    assert "QK106" in answer.answer and answer.grounded
    prompt, offered = client.seen[0]
    assert prompt == ENGINE_PROMPT and "compare_dtx_exports" in offered
