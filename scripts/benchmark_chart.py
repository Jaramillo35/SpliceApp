"""Measure the circuit chart at full scale, on invented data.

This exists because the chart's performance work was originally measured
against a customer export. Nobody else could reproduce those numbers, and the
file should not be what the repository's evidence rests on. The fixture in
``tests/fixtures_scale.py`` generates a programme of the same size from a
seed, so the measurement is reproducible by anyone with a checkout.

What it reports:

* how long the analysis, the chart build and the workbook build take;
* the worst stall the asyncio event loop suffers while the chart is built,
  once with the build on the loop (how the page used to do it) and once in a
  worker thread (how it does it now).

The second number is the one that mattered. NiceGUI derives its socket
heartbeat from ``reconnect_timeout``: it pings at 0.8x and gives the client up
0.4x later. Any stall past that budget costs the browser its connection, and
with the timeout elapsed the server discards the client — so the page comes
back rebuilt from nothing.

Run:  python -m scripts.benchmark_chart [--families 47] [--seed 2031]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from splice.dtxcircuits import (  # noqa: E402
    analyze_harness, integrity, matching, read_dtx_circuits,
)
from splice.dtxcircuits import chart as chart_mod  # noqa: E402
from splice.dtxcircuits import report as report_mod  # noqa: E402
from splice.dtxcircuits.analyze import union_condition  # noqa: E402
from splice.dtxcircuits.complexity import read_harness_file  # noqa: E402
from tests import fixtures_scale as fx  # noqa: E402

#: NiceGUI's default reconnect_timeout is 3s, which leaves this long between
#: a ping and the server being declared gone. nicegui_app.main raises it.
DEFAULT_PING_BUDGET = 3.0 * 0.4


def _conditions_by(rows, attribute: str) -> dict:
    grouped: dict = {}
    for row in rows:
        key = getattr(row, attribute, "")
        if key:
            grouped.setdefault(key, []).append(row)
    return {key: (union_condition(group) or "")
            for key, group in grouped.items()}


def prepare(families: int, seed: int):
    """Everything the chart needs, built the way the page builds it."""
    prog = fx.programme(families=families, seed=seed)

    t = time.monotonic()
    rows, meta = read_dtx_circuits(prog.dtx_bytes(), prog.dtx_name)
    read_dtx = time.monotonic() - t

    t = time.monotonic()
    harnesses, metas = {}, {}
    for family in prog.families:
        name = prog.complexity_name(family)
        harness, cmeta = read_harness_file(prog.complexity_bytes(family), name)
        harnesses[name], metas[name] = harness, cmeta
    read_complexity = time.monotonic() - t

    names = sorted({r.harness_family for r in rows})
    mapping = matching.auto_map(
        names, {f: (metas[f].harness or harnesses[f].name) for f in harnesses})
    if len(mapping) != len(names):
        raise SystemExit(f"only {len(mapping)} of {len(names)} families "
                         "matched — the fixture and the matcher disagree")

    fixed = integrity.apply_fixes(rows, {})
    t = time.monotonic()
    entries = []
    for family, filename in sorted(mapping.items()):
        harness = harnesses[filename]
        label = metas[filename].harness or harness.name
        analysis = analyze_harness(
            [r for r in fixed if r.harness_family == family], harness,
            harness_name=label)
        original = [r for r in rows if r.harness_family == family]
        entries.append(report_mod.Entry(
            label=f"{family} → {label}", family=family, filename=filename,
            analysis=analysis,
            original_circuit_conditions=_conditions_by(original, "circuit"),
            original_cnum_conditions=_conditions_by(original, "cnum"),
            complexity=harness))
    analyse = time.monotonic() - t

    print(f"  {len(rows):,} DTx rows · {prog.no_connect_rows:,} No Connect "
          f"({prog.no_connect_rows / len(rows) * 100:.0f}%) · "
          f"{len(prog.families)} families · {prog.part_numbers} part numbers")
    print(f"  read DTx {read_dtx:.1f}s · read complexity "
          f"{read_complexity:.1f}s · analyse {analyse:.1f}s")
    return entries, fixed, meta


async def _stall(build, gaps: List[float]) -> float:
    """Run ``build``, sampling how long the event loop goes unserviced."""
    stop = asyncio.Event()

    async def heartbeat() -> None:
        last = time.monotonic()
        while not stop.is_set():
            await asyncio.sleep(0.05)
            now = time.monotonic()
            gaps.append(now - last)
            last = now

    beat = asyncio.create_task(heartbeat())
    await asyncio.sleep(0.3)
    gaps.clear()
    t = time.monotonic()
    await build()
    elapsed = time.monotonic() - t
    stop.set()
    await beat
    return elapsed


async def measure(entries, rows, budget: float) -> None:
    def on_loop():
        chart_mod.build_charts(entries, rows)

    async def inline():
        on_loop()

    async def threaded():
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, on_loop)

    for label, build in (("on the event loop", inline),
                         ("in a worker thread", threaded)):
        gaps: List[float] = []
        elapsed = await _stall(build, gaps)
        worst = max(gaps)
        verdict = "DISCONNECT" if worst > budget else "survives"
        print(f"  {label:20s} build {elapsed:5.1f}s   "
              f"worst loop stall {worst:6.2f}s   -> {verdict}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--families", type=int, default=fx.FULL_SCALE)
    parser.add_argument("--seed", type=int, default=2031)
    parser.add_argument("--ping-budget", type=float,
                        default=DEFAULT_PING_BUDGET,
                        help="seconds a stall may last before the client is "
                             "dropped (NiceGUI: reconnect_timeout * 0.4)")
    args = parser.parse_args(argv)

    print(f"Invented programme {fx.PROGRAM} {fx.PHASE}, seed {args.seed}")
    entries, rows, meta = prepare(args.families, args.seed)

    charts = chart_mod.build_charts(entries, rows)
    print(f"  {len(charts)} charts · "
          f"{sum(len(c.rows) for c in charts):,} rows · "
          f"{sum(len(c.splices) for c in charts)} splices · "
          f"{sum(1 for c in charts for r in c.rows if r.mate_cnum)} mated")

    t = time.monotonic()
    data = chart_mod.build_chart_workbook(
        list(charts), meta.program or "", meta.phase or "")
    print(f"  workbook {time.monotonic() - t:.1f}s -> {len(data) / 1e6:.1f}MB")

    print(f"\nEvent loop, ping budget {args.ping_budget:.2f}s:")
    asyncio.run(measure(entries, rows, args.ping_budget))


if __name__ == "__main__":
    main()
