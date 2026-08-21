"""Tests for the Ollama client — with a fake transport, never a live server.

The point of these is the failure modes. In a field test the client will meet a
machine where Ollama isn't installed, isn't running, or hasn't pulled the
model, and what the engineer sees in each case has to be actionable.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

from secrdb.config import OLLAMA_KEEP_ALIVE
from secrdb.assistant.ollama import (
    ChatMessage,
    OllamaClient,
    OllamaError,
    OllamaModelMissing,
    OllamaTimeout,
    OllamaUnavailable,
    parse_tool_call,
)


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: Any = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    """Records what was sent and replays canned responses."""

    def __init__(
        self,
        get_response: Optional[Any] = None,
        post_response: Optional[Any] = None,
        raise_on: str = "",
    ):
        self.get_response = get_response
        self.post_response = post_response
        self.raise_on = raise_on
        self.posted: List[Dict[str, Any]] = []

    def get(self, url: str, timeout: float = 0) -> Any:
        if self.raise_on == "get":
            raise ConnectionError("connection refused")
        return self.get_response

    def post(self, url: str, json: Any = None, timeout: float = 0) -> Any:
        if self.raise_on == "post":
            raise ConnectionError("connection refused")
        self.posted.append(json)
        return self.post_response


def _client(session: FakeSession, model: str = "qwen2.5:7b") -> OllamaClient:
    return OllamaClient(host="http://localhost:11434", model=model, session=session)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_status_reports_a_server_that_is_not_running() -> None:
    status = _client(FakeSession(raise_on="get")).status()

    assert not status.reachable and not status.ready
    assert "Is it running?" in status.message


def test_status_reports_a_model_that_is_not_pulled() -> None:
    session = FakeSession(get_response=FakeResponse(200, {"models": [{"name": "llama3:8b"}]}))

    status = _client(session).status()

    assert status.reachable
    assert not status.model_present and not status.ready
    assert "ollama pull qwen2.5:7b" in status.message  # tells them the fix
    assert status.installed_models == ["llama3:8b"]


def test_status_is_ready_when_the_model_is_present() -> None:
    session = FakeSession(
        get_response=FakeResponse(200, {"models": [{"name": "qwen2.5:7b"}]})
    )
    assert _client(session).status().ready


def test_an_untagged_model_matches_a_tagged_install() -> None:
    """Asking for 'qwen2.5' should accept 'qwen2.5:7b-instruct-q4_K_M'."""
    session = FakeSession(
        get_response=FakeResponse(
            200, {"models": [{"name": "qwen2.5:7b-instruct-q4_K_M"}]}
        )
    )
    assert _client(session, model="qwen2.5").status().ready


def test_a_different_tag_of_the_same_model_is_not_a_match() -> None:
    """qwen2.5:7b-instruct-q4_K_M is not qwen2.5:3b.

    Reporting "ready" for the wrong tag sends the engineer to a 404 on their
    first question, which is a far worse failure than saying it is missing.
    """
    session = FakeSession(
        get_response=FakeResponse(200, {"models": [{"name": "qwen2.5:3b"}]})
    )
    status = _client(session, model="qwen2.5:7b-instruct-q4_K_M").status()

    assert not status.ready
    assert "ollama pull qwen2.5:7b-instruct-q4_K_M" in status.message
    assert status.installed_models == ["qwen2.5:3b"]


def test_latest_is_the_same_as_untagged() -> None:
    session = FakeSession(
        get_response=FakeResponse(200, {"models": [{"name": "qwen2.5"}]})
    )
    assert _client(session, model="qwen2.5:latest").status().ready


def test_status_never_raises(monkeypatch) -> None:
    """The UI calls this on every render; it must degrade, not crash."""
    session = FakeSession(get_response=FakeResponse(500))
    status = _client(session).status()
    assert not status.ready and status.message


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

def test_chat_sends_the_model_messages_and_tools() -> None:
    session = FakeSession(
        post_response=FakeResponse(200, {"message": {"content": "hello"}})
    )
    tools = [{"type": "function", "function": {"name": "x", "parameters": {}}}]

    response = _client(session).chat(
        [ChatMessage(role="user", content="hi")], tools=tools
    )

    assert response.content == "hello"
    assert not response.wants_tools
    sent = session.posted[0]
    assert sent["model"] == "qwen2.5:7b"
    assert sent["stream"] is False
    assert sent["options"]["temperature"] == 0.0  # retrieval, not creativity
    assert sent["tools"] == tools
    assert sent["messages"] == [{"role": "user", "content": "hi"}]


def test_chat_returns_tool_calls() -> None:
    session = FakeSession(
        post_response=FakeResponse(
            200,
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "get_changes_by_circuit",
                                "arguments": {"circuit": "A111"},
                            }
                        }
                    ],
                }
            },
        )
    )

    response = _client(session).chat([ChatMessage(role="user", content="A111?")])

    assert response.wants_tools
    name, arguments = parse_tool_call(response.tool_calls[0])
    assert name == "get_changes_by_circuit"
    assert arguments == {"circuit": "A111"}


def test_unreachable_server_raises_an_actionable_error() -> None:
    with pytest.raises(OllamaUnavailable, match="Is it running"):
        _client(FakeSession(raise_on="post")).chat([ChatMessage("user", "hi")])


def test_missing_model_raises_with_the_pull_command() -> None:
    session = FakeSession(post_response=FakeResponse(404, {"error": "model not found"}))
    with pytest.raises(OllamaModelMissing, match="ollama pull"):
        _client(session).chat([ChatMessage("user", "hi")])


def test_a_server_error_surfaces_its_detail() -> None:
    session = FakeSession(post_response=FakeResponse(500, {"error": "out of memory"}))
    with pytest.raises(OllamaError, match="out of memory"):
        _client(session).chat([ChatMessage("user", "hi")])


def test_an_unreadable_response_is_reported() -> None:
    session = FakeSession(post_response=FakeResponse(200, None))
    with pytest.raises(OllamaError, match="unreadable"):
        _client(session).chat([ChatMessage("user", "hi")])


def test_tool_results_are_sent_back_with_their_name() -> None:
    session = FakeSession(post_response=FakeResponse(200, {"message": {"content": "ok"}}))

    _client(session).chat(
        [
            ChatMessage(role="user", content="A111?"),
            ChatMessage(
                role="tool",
                content='{"result": []}',
                tool_name="get_changes_by_circuit",
            ),
        ]
    )

    tool_message = session.posted[0]["messages"][1]
    assert tool_message["role"] == "tool"
    assert tool_message["tool_name"] == "get_changes_by_circuit"


# ---------------------------------------------------------------------------
# Tool-call parsing
# ---------------------------------------------------------------------------

def test_arguments_may_arrive_as_a_json_string() -> None:
    """Some models emit arguments as a string rather than an object."""
    call = {
        "function": {
            "name": "get_changes_by_cnum",
            "arguments": json.dumps({"cnum": "D2784J"}),
        }
    }
    assert parse_tool_call(call) == ("get_changes_by_cnum", {"cnum": "D2784J"})


def test_malformed_arguments_degrade_to_empty() -> None:
    """A broken argument blob must not crash the loop — the dispatcher will
    report the missing argument and the model can correct itself."""
    call = {"function": {"name": "get_changes_by_cnum", "arguments": "{not json"}}
    assert parse_tool_call(call) == ("get_changes_by_cnum", {})


def test_a_flat_tool_call_is_accepted() -> None:
    call = {"name": "list_known_values", "arguments": {}}
    assert parse_tool_call(call) == ("list_known_values", {})


def test_a_nameless_tool_call_yields_no_name() -> None:
    name, arguments = parse_tool_call({"function": {"arguments": {}}})
    assert name == ""
    assert arguments == {}


# ---------------------------------------------------------------------------
# Cold starts (field report, 2026-08-12)
# ---------------------------------------------------------------------------

class TimingOutSession(FakeSession):
    """Connects, then never answers — what a model still loading looks like."""

    def post(self, url: str, json: Any = None, timeout: float = 0) -> Any:
        import requests

        self.posted.append(json)
        raise requests.exceptions.ReadTimeout("HTTPConnectionPool: Read timed out.")


def test_a_read_timeout_is_not_reported_as_a_dead_server() -> None:
    """Three field sessions lost their first question to this.

    Ollama was running the whole time — it was loading 4.7GB off disk. Telling
    the engineer "is it running?" sent them to reinstall software that was
    never broken.
    """
    client = OllamaClient(session=TimingOutSession())

    with pytest.raises(OllamaTimeout) as caught:
        client.chat([ChatMessage(role="user", content="hi")])

    message = str(caught.value)
    assert "is it running" not in message.lower()
    assert "still loading the model" in message
    assert "Ask again" in message


def test_a_refused_connection_still_says_the_server_is_down() -> None:
    """The other failure keeps the other message — they need different fixes."""
    client = OllamaClient(session=FakeSession(raise_on="post"))

    with pytest.raises(OllamaUnavailable) as caught:
        client.chat([ChatMessage(role="user", content="hi")])

    assert "Is it running?" in str(caught.value)
    assert not isinstance(caught.value, OllamaTimeout)


def test_a_timeout_is_a_kind_of_unavailable() -> None:
    """Callers that only catch OllamaUnavailable must still catch this."""
    assert issubclass(OllamaTimeout, OllamaUnavailable)


def test_the_model_is_asked_to_stay_loaded() -> None:
    """Ollama unloads after 5 minutes by default, re-charging the cold start."""
    session = FakeSession(
        post_response=FakeResponse(payload={"message": {"content": "ok"}})
    )
    OllamaClient(session=session).chat([ChatMessage(role="user", content="hi")])

    assert session.posted[0]["keep_alive"] == OLLAMA_KEEP_ALIVE


def test_warming_asks_for_the_model_and_never_raises() -> None:
    """The warm-up runs on page load; it must not be able to break the page."""
    session = TimingOutSession()          # the expected case: it times out
    assert OllamaClient(session=session).warm() is True
    assert session.posted[0]["model"]
    assert session.posted[0]["keep_alive"] == OLLAMA_KEEP_ALIVE

    assert OllamaClient(session=FakeSession(raise_on="post")).warm() is True
