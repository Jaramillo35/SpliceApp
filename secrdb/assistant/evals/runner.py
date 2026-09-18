"""Ask every case of one model and score the answers."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Callable, Iterable, List, Optional

from secrdb import diagnostics
from secrdb.assistant.agent import Assistant
from secrdb.assistant.evals.cases import Case
from secrdb.assistant.evals.scoring import CaseScore, score


def run_cases(cases: Iterable[Case], *, db_path: Path, client=None, model: str = "",
              progress: Optional[Callable[[int, int, CaseScore], None]] = None,
              all_tools: bool = False) -> List[CaseScore]:
    """``client`` is anything with ``chat(messages, tools=...)``; by default an
    ``OllamaClient`` for ``model``. Unanswered-question diagnostics are sent
    to a scratch folder, so an evaluation never pollutes the field log."""
    if client is None:
        from secrdb.assistant.ollama import OllamaClient  # noqa: PLC0415
        client = OllamaClient(model=model)
    cases = list(cases)
    scores: List[CaseScore] = []
    kept = diagnostics.DATA_DIR
    with tempfile.TemporaryDirectory(prefix="secr_evals_diag_") as scratch:
        diagnostics.DATA_DIR = Path(scratch)
        try:
            if all_tools:
                # the app's general assistant: SECR + engine tools, its own
                # prompt, an empty workspace — does the wider tool set cost
                # accuracy on the same SECR questions?
                from secrdb.assistant.general import general_assistant  # noqa: PLC0415
                assistant = general_assistant(client=client, db_path=db_path,
                                              workspace=Path(scratch) / "workspace")
            else:
                assistant = Assistant(client=client, db_path=db_path)
            for n, case in enumerate(cases, start=1):
                result = score(case, assistant.ask(case.question, session_id="evals"))
                scores.append(result)
                if progress is not None:
                    progress(n, len(cases), result)
        finally:
            diagnostics.DATA_DIR = kept
    return scores
