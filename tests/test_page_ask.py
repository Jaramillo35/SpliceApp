"""Ask the Assistant, driven as a user would — no browser, no model.

A scripted client stands in for Ollama; the showcase's invented DTx exports
sit in a workspace of their own. What is pinned is what the page promises:
the workspace says what the assistant can read and that it stays here; a
refusal from the workspace is shown as written; file questions wait for
files; every answer carries what the assistant did, one block per tool call
with its own figures, and a tool error verbatim; and the page says so when
the model is not ready instead of letting the engineer wait.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User

from secrdb.assistant.ollama import ChatResponse, OllamaClient, OllamaStatus


def _status(ready: bool, message: str = "") -> OllamaStatus:
    return OllamaStatus(reachable=ready, model_present=ready, host="http://local",
                        model="invented", message=message)


@pytest.fixture()
def desk(tmp_path: Path, monkeypatch):
    """An isolated workspace, database and diagnostics dir; a ready model;
    and a script the test fills with the model's turns."""
    from secrdb import diagnostics
    from secrdb.assistant import general, workspace
    from secrdb.core.secr.importer import import_secr_files
    from tests.secr_fixtures import build_secr_workbook

    root = tmp_path / "ws"
    root.mkdir()
    db_path = tmp_path / "secr.db"
    import_secr_files([("ip.xlsx", build_secr_workbook(secr_number="D50319A"))], db_path=db_path)
    monkeypatch.setattr(diagnostics, "DATA_DIR", tmp_path / "diag")
    monkeypatch.setattr(workspace, "default_workspace", lambda: root)
    monkeypatch.setattr(OllamaClient, "status", lambda self: _status(True))

    script: list[ChatResponse] = []

    class Scripted:
        def chat(self, messages, tools=None, temperature: float = 0.0):
            return script.pop(0)

    real = general.general_assistant
    monkeypatch.setattr(general, "general_assistant",
                        lambda client=None, **kw: real(client=Scripted(), db_path=db_path,
                                                       workspace=root))
    return root, script


def _showcase_into(root: Path, tmp_path: Path) -> tuple[str, str]:
    from demo import showcase
    out = tmp_path / "showcase"
    showcase.build(out)
    for f in (out / "4_dtx_compare").glob("*.xlsx"):
        shutil.copy(f, root / f.name)
    return (next(p.name for p in root.glob("*_OLD.xlsx")),
            next(p.name for p in root.glob("*_NEW.xlsx")))


def _button(user: User, label: str) -> ui.button:
    return next(b for b in user.find(kind=ui.button).elements if b.text == label)


async def _ask(user: User, question: str) -> None:
    user.find(kind=ui.input).type(question)
    user.find(kind=ui.button, content="Ask").click()


class TestWorkspace:
    async def test_it_says_what_the_assistant_can_read(self, user: User, desk):
        await user.open("/ask")
        await user.should_see("The assistant can only read the files listed here")
        await user.should_see("They stay on this machine")
        await user.should_see("No files yet")

    async def test_file_questions_wait_for_files(self, user: User, desk):
        await user.open("/ask")
        await user.should_see("About your files")
        assert not _button(user, "Where does circuit QK106 land?").enabled
        assert _button(user, "Has connector D2784J changed before?").enabled

    async def test_files_are_listed_with_a_guess_and_can_be_removed(self, user, desk, tmp_path):
        root, _ = desk
        old, _new = _showcase_into(root, tmp_path)
        await user.open("/ask")
        await user.should_see(old)
        await user.should_see("looks like:")
        assert _button(user, "Where does circuit QK106 land?").enabled
        user.find(kind=ui.button, content="Remove all").click()
        await user.should_see("No files yet")
        assert not list(root.glob("*.xlsx"))

    async def test_a_refusal_is_shown_as_written(self, user: User, desk):
        from secrdb.assistant import workspace
        with pytest.raises(workspace.WorkspaceError) as refusal:
            workspace.save_file("notes.txt", b"x", desk[0])
        await user.open("/ask")
        upload = user.find(kind=ui.upload).elements.pop()
        from types import SimpleNamespace

        class File:
            name = "notes.txt"
            async def read(self):
                return b"x"

        with upload:                                   # a handler runs in its element's slot
            for handler in upload._upload_handlers:
                await handler(SimpleNamespace(file=File()))
        await user.should_see(str(refusal.value))


class TestAnswers:
    async def test_a_compare_shows_what_it_did_with_its_own_figures(self, user, desk, tmp_path):
        root, script = desk
        old, new = _showcase_into(root, tmp_path)
        script += [
            ChatResponse(tool_calls=[{"function": {"name": "compare_dtx_exports",
                                                   "arguments": {"old_file": old, "new_file": new}}}]),
            ChatResponse(tool_calls=[{"function": {"name": "get_changes_by_circuit",
                                                   "arguments": {"circuit": "A937F"}}}]),
            ChatResponse(content="QK106 and QK702 were added; A937F changed under SECR D50319A."),
        ]
        await user.open("/ask")
        await _ask(user, "What changed, and is A937F in a SECR?")
        await user.should_see("QK106 and QK702 were added")
        await user.should_see("What it did · 2 tool call(s)")
        await user.should_see("Compared two DTx exports")
        await user.should_see("Looked up a circuit in the SECR history")
        await user.should_see(f"old {old} · new {new}")
        await user.should_see("Added circuits")
        await user.should_see("Modified circuits")
        await user.should_see("To write the workbook for this, use")

    async def test_a_starter_asks_its_question(self, user: User, desk):
        _, script = desk
        script += [ChatResponse(tool_calls=[{"function": {"name": "get_changes_by_cnum",
                                                          "arguments": {"cnum": "D2784J"}}}]),
                   ChatResponse(content="Nothing on record for D2784J.")]
        await user.open("/ask")
        user.find(kind=ui.button, content="Has connector D2784J changed before?").click()
        await user.should_see("Looked up a connector in the SECR history")
        assert not script                                        # the model was really asked

    async def test_a_tool_error_is_shown_verbatim(self, user, desk, tmp_path):
        root, script = desk
        _showcase_into(root, tmp_path)
        script += [
            ChatResponse(tool_calls=[{"function": {"name": "find_circuit",
                                                   "arguments": {"file": "nope.xlsx",
                                                                 "circuit": "QK106"}}}]),
            ChatResponse(content="I could not open that file."),
        ]
        await user.open("/ask")
        await _ask(user, "Where does QK106 land in nope.xlsx?")
        await user.should_see("Found where a circuit lands in a DTx export")
        await user.should_see("No file 'nope.xlsx' in the workspace")


class TestHonesty:
    async def test_it_sets_the_wait_before_the_first_question(self, user: User, desk):
        await user.open("/ask")
        await user.should_see("about 10 to 30 seconds")
        await user.should_see("model ready")

    async def test_a_model_that_is_not_ready_gates_ask(self, user: User, desk, monkeypatch):
        monkeypatch.setattr(OllamaClient, "status",
                            lambda self: _status(False, "Ollama is not running at http://local."))
        await user.open("/ask")
        await user.should_see("Ollama is not running at http://local.")
        await user.should_see("Needs: the local model (see above)")
        assert not _button(user, "Ask").enabled


def test_packing_restructures_and_never_recomputes():
    from types import SimpleNamespace

    from nicegui_app.pages.ask import EVIDENCE_CAP, pack_call
    result = SimpleNamespace(
        name="compare_dtx_exports", arguments={"old_file": "a.xlsx", "new_file": "b.xlsx"},
        row_count=80, truncated=True, error="",
        data={"old_file": "a.xlsx", "new_file": "b.xlsx", "changes_total": 80,
              "counts": {"added_circuit_count": 2, "modified_circuit_count": 0},
              "changes": [{"Circuit Name": f"QK{i}", "gone": None} for i in range(80)]})
    call = pack_call(result)
    assert call["facts"] == {}                                   # only repeated the arguments
    assert call["figures"] == {"changes_total": 80, "added_circuit_count": 2,
                               "modified_circuit_count": 0}
    table = call["tables"][0]
    assert (table["title"], table["total"], len(table["rows"])) == ("Changes", 80, EVIDENCE_CAP)
    assert table["rows"][0] == {"Circuit Name": "QK0", "gone": ""}
    assert call["truncated"] is True
