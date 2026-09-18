"""``python -m secrdb.assistant.evals`` — run the evaluation against Ollama."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from secrdb.assistant.evals import aggregate, build_cases, build_corpus, run_cases, to_markdown


def main(argv=None) -> int:
    from secrdb.config import OLLAMA_MODEL  # noqa: PLC0415

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", default=[OLLAMA_MODEL])
    parser.add_argument("--seed", type=int, default=2031)
    parser.add_argument("--limit", type=int, default=0, help="first N cases per category mix")
    parser.add_argument("--category", default="", help="only this category")
    parser.add_argument("--out", default="reports/assistant_evals")
    args = parser.parse_args(argv)

    corpus = build_corpus(seed=args.seed)
    cases = build_cases(corpus)
    if args.category:
        cases = [c for c in cases if c.category == args.category]
    if args.limit:
        step = max(1, len(cases) // args.limit)          # spread across categories
        cases = cases[::step][: args.limit]
    if not cases:
        print("no cases selected", file=sys.stderr)
        return 2

    summaries = []
    with tempfile.TemporaryDirectory(prefix="secr_evals_") as td:
        db_path = Path(td) / "corpus.db"
        corpus.import_into(db_path)
        for model in args.models:
            print(f"== {model}: {len(cases)} cases")

            def progress(n, total, s, model=model):
                mark = "ok " if s.passed else "FAIL"
                print(f"  {n:3d}/{total} {mark} {s.seconds:6.1f}s  {s.case_id}  {s.error[:60]}")

            scores = run_cases(cases, db_path=db_path, model=model, progress=progress)
            summaries.append(aggregate(scores, model=model))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (out / f"evals_{stamp}.json").write_text(json.dumps(
        {"seed": args.seed, "cases": len(cases), "models": summaries}, indent=2))
    report = to_markdown(summaries, args.seed)
    (out / f"evals_{stamp}.md").write_text(report)
    print(report)
    print(f"written to {out}/evals_{stamp}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
