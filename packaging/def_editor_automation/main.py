"""DEF Editor Automation — entry point.

    python main.py                 open the Terminal Material updater
    python main.py --demo          open it already attached to the demo
    python main.py --selftest      run the navigation test AND the updater
                                   headlessly against the demo

The test is one sequence: take a program, model year, phase and harness, open
that harness in DEF Editor, open its Circuits page, and filter for one
circuit. ``--selftest`` runs exactly that against a scripted stand-in, so the
kit can be checked on a machine that has never seen DEF Editor. If it passes
here and fails on Windows, the difference is the application or an
AutomationId — not the sequence.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from defauto import application, gridreader, workflow  # noqa: E402


def selftest(program: str = "2031ZR", year: str = "2031", phase: str = "V1_A",
             harness: str = "BODY_LEFT", target: str = workflow.TARGET_CIRCUIT,
             seed: int = 31) -> int:
    session = application.demo(seed)
    print(f"defauto selftest — scripted DEF Editor, seed {seed}")
    print(f"vehicle {program} / {year} / {phase} / {harness}  ->  circuit {target}\n")

    outcome = workflow.run(session, program, year, phase, harness, target)
    for index, step in enumerate(outcome.steps, start=1):
        print(f"  {step.mark}  {index:2d}. {step.name:44s} {step.detail}")

    if not outcome.ok:
        failed = outcome.failed
        print(f"\nselftest FAILED at step {outcome.steps.index(failed) + 1}: "
              f"{failed.name} — {failed.detail}")
        return 1
    print(f"\nfound in composite {outcome.composite}\n")
    print(gridreader.as_table(outcome.grid))
    print("\nselftest passed.")
    return 0


def termmatl_selftest() -> int:
    """The updater against the demo: plan, apply, read back."""
    import io

    from openpyxl import Workbook

    from defauto import ids, termmatl as tm

    session = application.demo()
    session.composite.choose_programme("2031ZR", "2031", "V1_A")
    session.composite.search()
    session.composite.choose_composite(session.composite.composites()[0])
    session.composite.choose_harness(session.composite.harnesses()[0])
    session.circuits.open()
    grid = session.backend.grid(ids.GRID_CIRCUITS)
    cnum, ckt = grid.headers.index("Connector No"), grid.headers.index("Circuit")
    wb = Workbook()
    ws = wb.active
    ws.append(["CNUM", "Circuit Name", "Terminal"])
    ws.append([grid.rows[0][cnum], grid.rows[0][ckt], "Gold"])
    ws.append([grid.rows[1][cnum], grid.rows[1][ckt], ""])
    ws.append([grid.rows[2][cnum], grid.rows[2][ckt], "Silver+Nickel"])
    ws.append(["NOPE", "ZZ", "Tin"])
    buffer = io.BytesIO()
    wb.save(buffer)
    print("\ntermmatl selftest — scripted DEF Editor")
    planned = tm.plan(session.backend, tm.read_updates(buffer.getvalue(), "demo.xlsx"))
    for p in planned:
        print(f"  {tm.STATUS_LABEL[p.status]:28s} {p.update.cnum} {p.update.circuit} "
              f"{p.update.terminal!r} current={p.current!r} {p.detail}")
    tm.apply(session.backend, planned)
    got = [p.status for p in planned]
    want = [tm.APPLIED, tm.NO_VALUE, tm.UNKNOWN, tm.NOT_FOUND]
    if got != want:
        print(f"termmatl selftest FAILED: {got} != {want}")
        return 1
    print("termmatl selftest passed.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true",
                        help="open the window already attached to the demo")
    parser.add_argument("--selftest", action="store_true",
                        help="run the test headlessly and exit")
    parser.add_argument("--vehicle", "--program", dest="program", default="2031ZR")
    parser.add_argument("--year", default="2031")
    parser.add_argument("--phase", default="V1_A")
    parser.add_argument("--harness", default="BODY_LEFT")
    parser.add_argument("--circuit", default=workflow.TARGET_CIRCUIT)
    parser.add_argument("--seed", type=int, default=31)
    args = parser.parse_args(argv)

    if args.selftest:
        rc = selftest(args.program, args.year, args.phase, args.harness,
                      args.circuit, args.seed)
        return rc or termmatl_selftest()

    from defauto.gui import Workbench

    window = Workbench()
    if args.demo:
        window.after(200, window.on_demo_direct)
    window.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
