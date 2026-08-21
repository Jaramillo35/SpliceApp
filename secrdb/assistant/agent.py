"""The agent loop: question in, grounded answer plus evidence out.

    question
       -> model picks a tool
       -> tools.call_tool() queries the database
       -> results go back to the model
       -> model writes prose
       -> grounding.check() verifies every identifier
       -> answer + evidence table

The model chooses *which* question to ask the database and how to word the
reply. It never supplies a fact. Anything it states that the evidence cannot
support is discarded in favour of a templated summary of the same rows, so a
wrong answer is replaced by a plainer true one rather than shown.

Questions that could not be answered are recorded through
:mod:`secrdb.diagnostics` — in a field test those are the most useful thing the
app can collect.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from secrdb import diagnostics
from secrdb.assistant import grounding
from secrdb.assistant.ollama import (
    ChatMessage,
    OllamaClient,
    OllamaError,
    OllamaTimeout,
    parse_tool_call,
)
from secrdb.assistant.tools import ToolResult, call_tool, tool_specs

#: How many times the model may call tools before it has to answer. Real
#: questions need one or two rounds; the cap stops a loop from running forever.
MAX_ROUNDS = 5

SYSTEM_PROMPT = """\
You answer questions about a SECR database for automotive wiring harnesses.
A SECR is an engineering change request; it records changes to connectors
(CNUMs), circuits, and harness part numbers, and is linked to DTCRs, bulletins,
a vehicle program, a model year, an engineering phase and a harness family.

A SECR number and a DTCR number are DIFFERENT THINGS and are never
interchangeable:
  * a SECR number looks like D50319A, D28X1RU_1000 or M27001 and appears in the
    `secr_number` field;
  * a DTCR number is digits only, like 50319 or 50092, and appears in the
    `dtcr_number` field.
If asked which DTCRs relate to something, read `dtcr_number` — never answer
with SECR numbers. If a row has no `dtcr_number`, say that no DTCR is recorded
for it rather than substituting the SECR.

Rules:
1. Answer ONLY from the tools. You have no knowledge of this database.
   Never state a SECR number, DTCR, CNUM, circuit, part number or count that a
   tool did not return, and never present a value from one field as another.
2. Always call at least one tool before answering. If you are unsure which
   value the user means, call list_known_values first.
3. If the tools return nothing, say plainly that the database has no record of
   it. Do not guess, and do not offer a plausible-sounding alternative.
4. Be concise and factual, the way an engineer writes. Give the SECR number,
   the program, model year and harness family, the DTCR, and the old and new
   values when they are relevant.
5. Say how many records you found. Do not list more than about ten; the full
   table is shown to the user beneath your answer.
"""


@dataclass
class AssistantAnswer:
    """One answered (or unanswerable) question, with everything behind it."""

    question: str
    answer: str = ""
    evidence: List[ToolResult] = field(default_factory=list)
    rounds: int = 0
    grounded: bool = True
    fallback_used: bool = False
    grounding_report: Optional[grounding.GroundingReport] = None
    error: str = ""
    elapsed_seconds: float = 0.0
    #: The model was reachable but did not answer in time — a cold start, not a
    #: broken install. The UI says so rather than blaming the server.
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def tool_calls(self) -> List[Dict[str, Any]]:
        """What was asked of the database, for the UI and for issue reports."""
        return [
            {
                "name": result.name,
                "arguments": result.arguments,
                "rows": result.row_count,
                "error": result.error,
            }
            for result in self.evidence
        ]

    @property
    def rows(self) -> List[Dict[str, Any]]:
        """Every row retrieved, flattened — the evidence table."""
        collected: List[Dict[str, Any]] = []
        for result in self.evidence:
            if result.ok and isinstance(result.data, list):
                collected.extend(
                    row for row in result.data if isinstance(row, dict)
                )
        return collected

    @property
    def found_nothing(self) -> bool:
        return not any(
            result.ok and result.data not in (None, [], {}) for result in self.evidence
        )


class Assistant:
    """Runs questions against the database through a local model."""

    def __init__(
        self,
        client: Optional[OllamaClient] = None,
        db_path: Optional[Path] = None,
        max_rounds: int = MAX_ROUNDS,
    ) -> None:
        self.client = client or OllamaClient()
        self.db_path = db_path
        self.max_rounds = max_rounds

    def ask(self, question: str, *, session_id: str = "") -> AssistantAnswer:
        """Answer one question. Never raises — failures come back on the answer."""
        started = time.monotonic()
        result = AssistantAnswer(question=question.strip())
        if not result.question:
            result.error = "Ask a question first."
            return result

        messages = [
            ChatMessage(role="system", content=SYSTEM_PROMPT),
            ChatMessage(role="user", content=result.question),
        ]
        specs = tool_specs()

        try:
            self._run(messages, specs, result)
        except OllamaTimeout as exc:
            result.error = str(exc)
            result.timed_out = True
        except OllamaError as exc:
            result.error = str(exc)
        except Exception as exc:  # noqa: BLE001 - the UI must always get an answer object
            result.error = f"The assistant failed: {exc}"
            diagnostics.record_error(
                exc, where="assistant", context={"question": result.question},
                session_id=session_id,
            )

        result.elapsed_seconds = round(time.monotonic() - started, 2)
        self._ground(result)
        self._record_if_unanswered(result, session_id=session_id)
        return result

    # -- the loop ----------------------------------------------------------

    def _run(
        self,
        messages: List[ChatMessage],
        specs: List[Dict[str, Any]],
        result: AssistantAnswer,
    ) -> None:
        for round_number in range(1, self.max_rounds + 1):
            result.rounds = round_number
            response = self.client.chat(messages, tools=specs)

            if not response.wants_tools:
                result.answer = response.content.strip()
                return

            messages.append(
                ChatMessage(
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
            )
            for call in response.tool_calls:
                name, arguments = parse_tool_call(call)
                tool_result = call_tool(name, arguments, db_path=self.db_path)
                result.evidence.append(tool_result)
                messages.append(
                    ChatMessage(
                        role="tool",
                        content=json.dumps(
                            tool_result.to_model_payload(), default=str
                        ),
                        tool_name=name or "unknown",
                    )
                )

        # Out of rounds: answer from what was gathered rather than nothing.
        result.answer = ""

    # -- grounding ---------------------------------------------------------

    def _ground(self, result: AssistantAnswer) -> None:
        """Verify the prose, and replace it with a templated summary if needed."""
        if result.error:
            return

        evidence = [item.data for item in result.evidence if item.ok]

        if not result.answer:
            # The model never produced prose (ran out of rounds, or returned an
            # empty message). The evidence still answers the question.
            result.answer = grounding.summarise_evidence(result.rows)
            result.fallback_used = True
            return

        report = grounding.check(result.answer, evidence, question=result.question)
        result.grounding_report = report
        result.grounded = report.grounded
        if report.grounded:
            return

        # The rejected identifiers are deliberately NOT repeated here. They are
        # fabrications or mislabellings; putting them on screen invites someone
        # to copy one into a document. They stay on the report, which the debug
        # panel shows and the issue export carries.
        #
        # The two failures need different wording: "not retrieved" is simply
        # untrue of a misattribution, where the value was retrieved and then
        # given the wrong name. An explanation that misdescribes what happened
        # costs more trust than it saves.
        if report.misattributed and not report.ungrounded:
            cause = (
                "labelled a value as something it is not (for example a SECR "
                "number given as a DTCR)"
            )
        elif report.misattributed:
            cause = "referred to records that were not retrieved, and mislabelled others"
        else:
            cause = "referred to records that were not retrieved"

        result.fallback_used = True
        result.answer = (
            grounding.summarise_evidence(result.rows)
            + f"\n\n_(The assistant's wording {cause}, so it was discarded. "
            "The summary above is built directly from the records below.)_"
        )

    def _record_if_unanswered(
        self, result: AssistantAnswer, *, session_id: str = ""
    ) -> None:
        """Log questions the assistant could not answer, for the issue report."""
        reason = ""
        if result.error:
            reason = result.error
        elif result.found_nothing:
            reason = "No tool returned any records."
        elif not result.grounded:
            reason = "The answer failed the grounding check: " + (
                result.grounding_report.reason if result.grounding_report else ""
            )
        if not reason:
            return
        diagnostics.record_unanswered(
            result.question,
            reason=reason,
            tools_called=result.tool_calls,
            session_id=session_id,
        )
