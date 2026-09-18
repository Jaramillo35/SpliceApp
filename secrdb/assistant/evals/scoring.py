"""Score one answered question. Deterministic: no model, no network."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

from secrdb.assistant.evals.cases import Case

#: how an answer says the database has nothing
_NO_RECORD = re.compile(
    r"\b(no record|no records|not? (?:find|found)|nothing|does not (?:exist|appear|have)|"
    r"doesn't (?:exist|appear|have)|no (?:changes?|matching|data|results?|entries|information)|"
    r"not in the database|0 (?:records|results|changes))\b", re.I)


@dataclass
class CaseScore:
    case_id: str
    category: str
    question: str
    #: a tool that can answer this question was called
    tool_ok: bool = False
    #: … with the reference arguments (values compared case-insensitively)
    args_ok: bool = False
    #: the facts came back from the database (or, for an absent id, nothing did)
    retrieved: bool = False
    #: the final answer says the facts (or says there is no record)
    answered: bool = False
    #: the model's own prose survived the grounding check
    prose_kept: bool = False
    #: nothing forbidden was presented
    clean: bool = True
    error: str = ""
    timed_out: bool = False
    rounds: int = 0
    seconds: float = 0.0
    tools_called: List[str] = field(default_factory=list)
    missing_facts: List[str] = field(default_factory=list)
    missing_in_answer: List[str] = field(default_factory=list)
    answer: str = ""

    @property
    def passed(self) -> bool:
        return (not self.error and self.tool_ok and self.retrieved
                and self.answered and self.clean)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self) | {"passed": self.passed}


def _norm(value: Any) -> str:
    return re.sub(r"\s+", "", str(value)).upper()


def score(case: Case, answer) -> CaseScore:
    """``answer`` is an ``AssistantAnswer`` (or anything shaped like one)."""
    out = CaseScore(case_id=case.id, category=case.category, question=case.question,
                    error=answer.error or "", timed_out=bool(getattr(answer, "timed_out", False)),
                    rounds=answer.rounds, seconds=answer.elapsed_seconds,
                    answer=answer.answer or "")
    calls = answer.tool_calls
    out.tools_called = [c["name"] for c in calls]
    good = [c for c in calls if c["name"] in case.accept_tools and not c.get("error")]
    out.tool_ok = bool(good)

    wanted = {k: _norm(v) for k, v in case.reference[1].items()}
    out.args_ok = any(
        all(w in {_norm(v) for v in (c.get("arguments") or {}).values()} for w in wanted.values())
        for c in good) if wanted else out.tool_ok

    evidence = _norm(json.dumps([r.data for r in answer.evidence if r.ok], default=str))
    said = _norm(out.answer)
    if case.expect_empty:
        out.retrieved = bool(calls) and answer.found_nothing
        out.answered = bool(_NO_RECORD.search(out.answer))
    else:
        out.missing_facts = [f for f in case.facts if _norm(f) not in evidence]
        out.retrieved = out.tool_ok and not out.missing_facts
        out.missing_in_answer = [f for f in case.say if _norm(f) not in said]
        out.answered = not out.missing_in_answer
    out.clean = not any(_norm(f) in said for f in case.forbidden)
    out.prose_kept = bool(out.answer) and answer.grounded and not answer.fallback_used
    return out
