"""Turn scores into numbers a person can compare between models."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from secrdb.assistant.evals.scoring import CaseScore

METRICS = (("passed", "Pass"), ("tool_ok", "Right tool"), ("args_ok", "Right arguments"),
           ("retrieved", "Facts retrieved"), ("answered", "Facts stated"),
           ("prose_kept", "Prose kept by grounding"), ("clean", "Nothing forbidden"))


def _rate(scores: List[CaseScore], name: str) -> float:
    return round(sum(1 for s in scores if getattr(s, name)) / len(scores), 3) if scores else 0.0


def _percentile(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(q * len(ordered)))], 2)


def aggregate(scores: Iterable[CaseScore], model: str = "") -> Dict[str, Any]:
    scores = list(scores)
    seconds = [s.seconds for s in scores]
    by_category: Dict[str, List[CaseScore]] = {}
    for s in scores:
        by_category.setdefault(s.category, []).append(s)
    return {
        "model": model, "cases": len(scores),
        "rates": {name: _rate(scores, name) for name, _label in METRICS},
        "errors": sum(1 for s in scores if s.error),
        "timeouts": sum(1 for s in scores if s.timed_out),
        "latency_seconds": {"p50": _percentile(seconds, 0.5), "p95": _percentile(seconds, 0.95),
                            "max": round(max(seconds), 2) if seconds else 0.0},
        "mean_rounds": round(sum(s.rounds for s in scores) / len(scores), 2) if scores else 0.0,
        "by_category": {c: {"cases": len(v), "pass": _rate(v, "passed"),
                            "right_tool": _rate(v, "tool_ok"),
                            "facts_stated": _rate(v, "answered")}
                        for c, v in sorted(by_category.items())},
        "failures": [s.as_dict() for s in scores if not s.passed],
    }


def to_markdown(summaries: List[Dict[str, Any]], seed: int) -> str:
    lines = ["# SECR assistant — generation evaluation", "",
             f"Invented corpus, seed {seed}. Local models through Ollama. "
             "A case passes when a tool that can answer was called, the facts came back, "
             "the answer states them, and nothing forbidden was presented.", "",
             "| Model | Cases | " + " | ".join(label for _n, label in METRICS)
             + " | Errors | p50 s | p95 s | Rounds |",
             "|---|---|" + "---|" * (len(METRICS) + 4)]
    for s in summaries:
        lines.append(f"| {s['model']} | {s['cases']} | "
                     + " | ".join(f"{s['rates'][n]:.0%}" for n, _l in METRICS)
                     + f" | {s['errors']} | {s['latency_seconds']['p50']} | "
                       f"{s['latency_seconds']['p95']} | {s['mean_rounds']} |")
    for s in summaries:
        lines += ["", f"## {s['model']} by category", "",
                  "| Category | Cases | Pass | Right tool | Facts stated |", "|---|---|---|---|---|"]
        for name, c in s["by_category"].items():
            lines.append(f"| {name} | {c['cases']} | {c['pass']:.0%} | "
                         f"{c['right_tool']:.0%} | {c['facts_stated']:.0%} |")
        if s["failures"]:
            lines += ["", f"### {s['model']} — first failures", ""]
            for f in s["failures"][:12]:
                why = [k for k in ("tool_ok", "retrieved", "answered", "clean") if not f[k]]
                lines.append(f"- `{f['case_id']}` {f['question']} — failed: "
                             f"{', '.join(why) or f['error']}; called {f['tools_called'] or 'nothing'}")
    return "\n".join(lines) + "\n"
