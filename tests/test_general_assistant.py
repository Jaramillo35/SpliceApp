"""One assistant with every tool, and the workspace its file tools read from."""

from __future__ import annotations

from pathlib import Path

import pytest

from secrdb import diagnostics
from secrdb.assistant import workspace as ws
from secrdb.assistant.general import GENERAL_PROMPT, general_assistant, general_tools
from secrdb.assistant.ollama import ChatResponse
from secrdb.assistant.tools import tool_names
from secrdb.core.secr.importer import import_secr_files
from tests.secr_fixtures import build_secr_workbook


def test_the_general_assistant_has_every_tool_once(tmp_path):
    names = tool_names(general_tools(tmp_path))
    assert set(tool_names()) < set(names) and "compare_dtx_exports" in names
    assert len(names) == len(set(names)) == len(tool_names()) + 6
    assert "WORKSPACE FILE tools" in GENERAL_PROMPT and "SECR DATABASE tools" in GENERAL_PROMPT


def test_the_workspace_takes_workbooks_by_name_only(tmp_path):
    row = ws.save_file("C:\\\\Users\\\\me\\\\DTx 2030QX (NEW).xlsx", b"data", tmp_path)
    assert row["file"] == "DTx 2030QX (NEW).xlsx" and row["kind"] == "DTx export"
    assert ws.save_file("../../etc/DTCR_Report.xls", b"x", tmp_path)["file"] == "DTCR_Report.xls"
    assert {p.name for p in tmp_path.iterdir()} == {"DTx 2030QX (NEW).xlsx", "DTCR_Report.xls"}
    for name, data, why in (("notes.txt", b"x", "only Excel"), ("a.xlsx", b"", "is empty"),
                            ("big.xlsx", b"x" * (ws.MAX_FILE_BYTES + 1), "limit is")):
        with pytest.raises(ws.WorkspaceError, match=why):
            ws.save_file(name, data, tmp_path)
    with pytest.raises(ws.WorkspaceError, match="not a file name"):
        ws.resolve("../DTCR_Report.xls", tmp_path)
    assert ws.delete_file("DTCR_Report.xls", tmp_path) and not ws.delete_file("nope.xlsx", tmp_path)
    assert ws.clear(tmp_path) == 1 and ws.list_files(tmp_path) == []


def test_the_workspace_is_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(ws, "MAX_FILES", 2)
    ws.save_file("a.xlsx", b"1", tmp_path)
    ws.save_file("b.xlsx", b"1", tmp_path)
    ws.save_file("a.xlsx", b"22", tmp_path)                  # replacing is not adding
    with pytest.raises(ws.WorkspaceError, match="holds 2 files"):
        ws.save_file("c.xlsx", b"1", tmp_path)


def test_one_question_can_use_both_families(tmp_path, monkeypatch):
    """A file question and a history question in one conversation: the rows of
    both reach the evidence table, including rows nested in an engine result."""
    import shutil
    from demo import showcase
    monkeypatch.setattr(diagnostics, "DATA_DIR", tmp_path / "diag")
    out = tmp_path / "showcase"
    showcase.build(out)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    for f in (out / "4_dtx_compare").glob("*.xlsx"):
        shutil.copy(f, workspace / f.name)
    old = next(p.name for p in workspace.glob("*_OLD.xlsx"))
    new = next(p.name for p in workspace.glob("*_NEW.xlsx"))
    db_path = tmp_path / "secr.db"
    import_secr_files([("ip.xlsx", build_secr_workbook(secr_number="D50319A"))], db_path=db_path)

    script = [
        ChatResponse(tool_calls=[{"function": {"name": "compare_dtx_exports",
                                               "arguments": {"old_file": old, "new_file": new}}}]),
        ChatResponse(tool_calls=[{"function": {"name": "get_changes_by_circuit",
                                               "arguments": {"circuit": "A937F"}}}]),
        ChatResponse(content="QK106 and QK702 were added; A937F changed under SECR D50319A."),
    ]

    class Scripted:
        def chat(self, messages, tools=None, temperature: float = 0.0):
            assert messages[0].content == GENERAL_PROMPT and len(tools) == len(general_tools(workspace))
            return script.pop(0)

    answer = general_assistant(client=Scripted(), db_path=db_path, workspace=workspace) \
        .ask("What changed between the exports, and is A937F in a SECR?")
    assert answer.ok and answer.grounded, answer.grounding_report
    assert [c["name"] for c in answer.tool_calls] == ["compare_dtx_exports", "get_changes_by_circuit"]
    circuits = {r.get("Circuit Name") for r in answer.rows} | {r.get("object_id") for r in answer.rows}
    assert {"QK106", "QK702", "A937F"} <= circuits
