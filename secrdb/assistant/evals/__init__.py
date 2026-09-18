"""Generation-side evaluation of the SECR assistant.

``tests/test_evaluation.py`` pins *retrieval*: given the right tool call, the
database returns the right rows. It runs with no model on purpose. This
package measures the other half — what a **model** does with the same
questions: whether it picks a tool that can answer, passes the right
arguments, retrieves the facts, says them, keeps its prose through the
grounding check, refuses when the database has nothing, and how long it takes.

    python -m secrdb.assistant.evals                       # the configured model
    python -m secrdb.assistant.evals --models qwen2.5:7b-instruct-q4_K_M qwen2.5:3b
    python -m secrdb.assistant.evals --limit 20 --category circuit

Everything runs locally against Ollama. The corpus is invented
(:mod:`.corpus`): programmes, connectors, circuits and DTCRs that exist
nowhere else, so a report can be shown to anyone.

Two layers, deliberately separate:

* the **question set and the scorer are deterministic** and are gated in CI
  (``tests/test_assistant_evals.py``): every case's reference tool call must
  return the facts the case expects, and the scorer must pass a reference
  run and fail a fabricating one. A change to a tool that breaks a question
  fails the build with no model involved.
* the **model run** is a measurement, not a gate: it needs Ollama, takes
  minutes, and varies by model. Its report is what gets compared between
  models and between prompt changes.
"""

from secrdb.assistant.evals.cases import Case, build_cases
from secrdb.assistant.evals.corpus import Corpus, build_corpus
from secrdb.assistant.evals.report import aggregate, to_markdown
from secrdb.assistant.evals.runner import run_cases
from secrdb.assistant.evals.scoring import CaseScore, score

__all__ = ["Case", "CaseScore", "Corpus", "aggregate", "build_cases", "build_corpus",
           "run_cases", "score", "to_markdown"]
