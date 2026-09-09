"""DEF Editor Automation — entry point.

    python main.py                 open the workbench window
    python main.py --demo          open it already attached to the demo
    python main.py --selftest      run a whole workflow headlessly and report

``--selftest`` is what makes this kit checkable on a machine that has never
seen DEF Editor: it drives the full sequence — programme, composite, harness,
every module, both quality checks — against the scripted backend and prints
what came back. If that passes here and fails on Windows, the difference is
the application or an AutomationId, not the workflow.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from defauto import application  # noqa: E402


def selftest(seed: int = 31) -> int:
    session = application.demo(seed)
    print(f"defauto selftest — scripted DEF Editor, seed {seed}\n")

    missing = [a for a, ok in session.diagnose() if not ok]
    print(f"diagnose            : {'all present' if not missing else missing}")

    line = session.composite.vehicle_lines()[0]
    session.backend.select("ComboBox_Vehicle_Line", line)
    year = session.composite.model_years()[0]
    session.backend.select("ComboBox_Model_Year", year)
    phase = session.composite.phases()[0]

    session.composite.choose_programme(line, year, phase)
    composites = session.composite.search()
    print(f"programme           : {line} / {year} / {phase}")
    print(f"composites          : {len(composites)}")
    if not len(composites):
        print("FAILED: Filter produced no composites")
        return 1

    name = session.composite.composites()[0]
    session.composite.choose_composite(name)
    harnesses = session.composite.harnesses()
    session.composite.choose_harness(harnesses[0])
    print(f"open                : {session.composite.selection}")

    session.devices.open()
    print(f"devices             : {len(session.devices.read())}")
    session.circuits.open()
    print(f"circuits            : {len(session.circuits.read())}")
    print(f"  missing           : {len(session.circuits.missing())}")
    print(f"  single-ended      : {len(session.circuits.single_ended())}")
    session.circuits.clear_filters()
    session.splices.open()
    print(f"splices             : {len(session.splices.read())}")
    print(f"complexity devices  : {len(session.complexity.devices())}")
    print(f"complexity circuits : {len(session.complexity.circuits())}")
    compare = session.complexity.compare_codes()
    print(f"sales codes         : {len(compare['both'])} both, "
          f"{len(compare['available_only'])} available only, "
          f"{len(compare['used_only'])} used only")

    check = session.quality.circuits()
    print(f"connector checks    : {check.summary}")
    inline = session.quality.run_inline()
    print(f"inline pairs        : {inline.summary}")
    failing = session.quality.failing_pairs(inline.rows)
    if failing:
        try:
            session.quality.sign_off()
        except Exception as exc:  # noqa: BLE001 - the refusal IS the test
            print(f"sign-off            : correctly refused — {exc}")
        else:
            print("FAILED: signed off over a failing pair")
            return 1
    else:
        session.quality.sign_off()
        print("sign-off            : accepted, all pairs matching")

    print("\nselftest passed.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true",
                        help="open the window already attached to the demo")
    parser.add_argument("--selftest", action="store_true",
                        help="run the whole workflow headlessly and exit")
    parser.add_argument("--seed", type=int, default=31)
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest(args.seed)

    from defauto.gui import Workbench

    window = Workbench()
    if args.demo:
        window.after(200, window.on_demo)
    window.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
