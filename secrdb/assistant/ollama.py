"""Ollama client — the local model backend.

Everything here talks to an Ollama server over plain HTTP. There is no cloud
SDK and no API key: inference happens on the machine (or on an internal host
the team controls), so no engineering data leaves the premises.

The client is deliberately small. Its job is to send a conversation plus the
tool specs and hand back what came out, translating the ways Ollama can fail
into messages an engineer can act on — "Ollama isn't running", "the model isn't
pulled" — rather than a raw connection error. In a field test the failure
message *is* the feature.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests

from secrdb.config import (
    OLLAMA_HOST,
    OLLAMA_KEEP_ALIVE,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT_SECONDS,
)


class OllamaError(RuntimeError):
    """Ollama could not be used. The message is meant for the engineer."""


class OllamaUnavailable(OllamaError):
    """The server is not reachable."""


class OllamaModelMissing(OllamaError):
    """The server is up but the model has not been pulled."""


class OllamaTimeout(OllamaUnavailable):
    """We connected, but the answer did not arrive in time.

    Almost always a cold start: the model is being loaded from disk. Kept
    distinct from :class:`OllamaUnavailable` so the UI can say "still loading"
    instead of "is it running?", which is both wrong and unhelpful here.
    """


@dataclass
class ChatMessage:
    """One turn. ``tool_calls`` is present on assistant turns that call tools."""

    role: str
    content: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    tool_name: str = ""

    def to_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            payload["tool_calls"] = self.tool_calls
        if self.tool_name:
            payload["tool_name"] = self.tool_name
        return payload


@dataclass
class ChatResponse:
    """What the model returned: prose, tool calls, or both."""

    content: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    model: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


@dataclass
class OllamaStatus:
    """Whether the assistant can run, and if not, what to tell the user."""

    reachable: bool
    model_present: bool
    host: str
    model: str
    installed_models: List[str] = field(default_factory=list)
    message: str = ""

    @property
    def ready(self) -> bool:
        return self.reachable and self.model_present


def _is_read_timeout(exc: BaseException) -> bool:
    """True when we connected and the server simply took too long to answer.

    Checked by class name rather than by importing ``requests.exceptions`` so
    an injected fake transport (and the frozen build) behave the same way.
    """
    for error in (exc, exc.__cause__, exc.__context__):
        if error is None:
            continue
        if "timeout" in type(error).__name__.lower():
            return True
    return "timed out" in str(exc).lower()


def _transport_error(
    exc: BaseException, *, host: str, timeout: float
) -> "OllamaError":
    """Turn a transport failure into a message that names the actual problem.

    A read timeout and a refused connection are different failures with
    different fixes, and telling someone "is it running?" when it plainly is
    sends them to reinstall software that was never broken. That happened in
    the field: three sessions, every first question, Ollama running the whole
    time.
    """
    if _is_read_timeout(exc):
        return OllamaTimeout(
            f"Ollama at {host} did not answer within {timeout:.0f}s. It is "
            "running — it is most likely still loading the model, which can "
            "take a few minutes the first time after starting. Ask again; the "
            "second question is normally fast."
        )
    return OllamaUnavailable(
        f"Could not reach Ollama at {host}. Is it running? ({exc})"
    )


class OllamaClient:
    """A thin, synchronous client for Ollama's ``/api/chat``."""

    def __init__(
        self,
        host: str = "",
        model: str = "",
        timeout: float = 0.0,
        session: Optional[Any] = None,
    ) -> None:
        self.host = (host or OLLAMA_HOST).rstrip("/")
        self.model = model or OLLAMA_MODEL
        self.timeout = timeout or OLLAMA_TIMEOUT_SECONDS
        # Injectable so tests never need a live server.
        self._session = session or requests

    # -- health ------------------------------------------------------------

    def list_models(self) -> List[str]:
        """Model names the server has pulled."""
        try:
            response = self._session.get(
                f"{self.host}/api/tags", timeout=min(self.timeout, 10)
            )
        except Exception as exc:  # noqa: BLE001 - any transport failure
            raise OllamaUnavailable(
                f"Could not reach Ollama at {self.host}. Is it running? ({exc})"
            ) from exc
        if response.status_code != 200:
            raise OllamaUnavailable(
                f"Ollama at {self.host} returned HTTP {response.status_code}."
            )
        try:
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            raise OllamaUnavailable(
                f"Ollama at {self.host} returned an unreadable response."
            ) from exc
        return [str(entry.get("name", "")) for entry in payload.get("models", [])]

    def status(self) -> OllamaStatus:
        """Check the backend without raising — the UI shows this, it doesn't crash on it."""
        try:
            models = self.list_models()
        except OllamaError as exc:
            return OllamaStatus(
                reachable=False,
                model_present=False,
                host=self.host,
                model=self.model,
                message=str(exc),
            )

        present = self._model_matches(models)
        return OllamaStatus(
            reachable=True,
            model_present=present,
            host=self.host,
            model=self.model,
            installed_models=models,
            message=(
                ""
                if present
                else (
                    f"Ollama is running but {self.model!r} is not installed. "
                    f"Run:  ollama pull {self.model}"
                )
            ),
        )

    def warm(self) -> bool:
        """Ask Ollama to load the model, without waiting for it.

        The cold start is unavoidable — 4.7GB has to come off disk — but *when*
        it happens is a choice. Triggering it when the assistant page opens
        means the load overlaps with the engineer reading the page and typing a
        question, instead of being charged to that question.

        Returns whether the request was accepted. Never raises: a warm-up that
        fails must not stop anyone from asking anything.
        """
        try:
            self._session.post(
                f"{self.host}/api/chat",
                json={
                    "model": self.model,
                    "messages": [],
                    "stream": False,
                    "keep_alive": OLLAMA_KEEP_ALIVE,
                },
                timeout=2,
            )
        except Exception:  # noqa: BLE001 - including the expected read timeout
            # A timeout here is the normal case and means the load started.
            return True
        return True

    def _model_matches(self, models: List[str]) -> bool:
        """Is the configured model installed?

        Ollama reports models as ``name:tag``. A request that names a tag must
        match that tag exactly — ``qwen2.5:7b-instruct-q4_K_M`` is a different
        model from ``qwen2.5:3b``, and reporting "ready" for the wrong one sends
        the engineer to a 404 on their first question. Only an *untagged*
        request is allowed to match any installed tag of that name.
        """
        wanted = self.model
        if wanted in models:
            return True
        if ":" in wanted:
            # "name" and "name:latest" are the same model to Ollama.
            base, tag = wanted.split(":", 1)
            return tag == "latest" and base in models
        return any(name.split(":", 1)[0] == wanted for name in models)

    # -- chat --------------------------------------------------------------

    def chat(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        *,
        temperature: float = 0.0,
    ) -> ChatResponse:
        """One round trip. ``temperature=0`` because this is retrieval, not prose.

        Streaming is off: the loop needs the whole message (including any tool
        calls) before it can act on it.
        """
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [message.to_payload() for message in messages],
            "stream": False,
            "options": {"temperature": temperature},
        }
        if tools:
            payload["tools"] = tools

        payload["keep_alive"] = OLLAMA_KEEP_ALIVE

        try:
            response = self._session.post(
                f"{self.host}/api/chat", json=payload, timeout=self.timeout
            )
        except Exception as exc:  # noqa: BLE001
            raise _transport_error(exc, host=self.host, timeout=self.timeout)

        if response.status_code == 404:
            raise OllamaModelMissing(
                f"Ollama does not have the model {self.model!r}. "
                f"Run:  ollama pull {self.model}"
            )
        if response.status_code != 200:
            detail = ""
            try:
                detail = str(response.json().get("error", ""))
            except Exception:  # noqa: BLE001
                detail = (getattr(response, "text", "") or "")[:300]
            raise OllamaError(
                f"Ollama returned HTTP {response.status_code}. {detail}".strip()
            )

        try:
            body = response.json()
        except Exception as exc:  # noqa: BLE001
            raise OllamaError("Ollama returned an unreadable response.") from exc

        message = body.get("message") or {}
        return ChatResponse(
            content=str(message.get("content") or ""),
            tool_calls=list(message.get("tool_calls") or []),
            model=str(body.get("model") or self.model),
            raw=body,
        )


def parse_tool_call(call: Dict[str, Any]) -> tuple:
    """Pull ``(name, arguments)`` out of one tool call.

    Ollama nests the call under ``function`` and usually returns arguments as a
    dict, but some models emit a JSON string instead. Both are accepted; a name
    is required, since without one there is nothing to dispatch.
    """
    import json

    function = call.get("function") or call
    name = str(function.get("name") or "").strip()
    arguments = function.get("arguments")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            arguments = {}
    if not isinstance(arguments, dict):
        arguments = {}
    return name, arguments
