"""Circuit Health Check — NiceGUI prototype (UI-stack evaluation).

Same engine as the Streamlit page (splice.inline.health imported unchanged);
only the surface differs. Run:

    python prototypes/nicegui_circuit_health/main.py       # http://localhost:8503

What this demonstrates that Streamlit cannot:
- no full-page rerun: uploading, dispositioning, and tab switches update only
  the affected elements, instantly;
- a real disposition dialog (modal over the list, not a form re-render);
- sticky metrics header that updates live as findings are dispositioned;
- motion with restraint (150-200ms ease-out reveals, press feedback) per the
  design-engineering guidance.

Prototype scope: single local user, global state, no auth.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nicegui import run, ui

from splice.config import DATA_DIR
from splice.inline import health
from splice.inline.complexity import read_complexity
from splice.inline.pairing import resolve
from splice.inline.summary import read_circuit_summary

BASELINE_PATH = DATA_DIR / "inline_health" / "baseline.json"

BRAND = "#d95926"
SEV_COLOR = {"Blocker": "#e66767", "High": "#c98500", "Review": "#d5c04b"}
SEV_ICON = {"Blocker": "report", "High": "warning", "Review": "help_outline"}
KIND_LABEL = {"cavity": "Cavity mismatch", "one_sided_window": "Missing variant window",
              "route_window_gap": "Route gap"}


class State:
    summary_bytes: bytes | None = None
    summary_name: str = ""
    cx_files: dict[str, bytes] = {}
    result: health.HealthResult | None = None
    rejected: list[str] = []


S = State()

# Dev convenience: SPLICE_PROTO_AUTOLOAD=<dir> preloads a validation set so the
# findings UI can be exercised without clicking through uploads.
import os  # noqa: E402
_auto = os.getenv("SPLICE_PROTO_AUTOLOAD")
if _auto and Path(_auto).is_dir():
    _d = Path(_auto)
    _s = next(iter(_d.glob("Circuit Summary*.xlsx")), None)
    if _s is not None:
        S.summary_bytes, S.summary_name = _s.read_bytes(), _s.name
    for _f in sorted(_d.glob("*.xls[mM]")):
        S.cx_files[_f.name] = _f.read_bytes()

ui.dark_mode().enable()
ui.colors(primary=BRAND)
ui.add_head_html("""
<style>
  .sx-reveal { animation: sxin 180ms cubic-bezier(0.23,1,0.32,1) both; }
  @keyframes sxin { from { opacity: 0; transform: translateY(4px); } }
  .q-btn { transition: transform 140ms cubic-bezier(0.23,1,0.32,1); }
  .q-btn:active { transform: scale(0.97); }
  @media (prefers-reduced-motion: reduce) { .sx-reveal { animation: none; } }
</style>
""")


def sev_chip(sev: str):
    color = SEV_COLOR.get(sev, "#3987e5")
    with ui.row().classes("items-center gap-1 px-2 py-0.5 rounded-full border") \
            .style(f"border-color:{color}55;background:{color}22;color:{color}"):
        ui.icon(SEV_ICON.get(sev, "info")).classes("text-sm")
        ui.label(sev).classes("text-xs font-semibold")


# --------------------------------------------------------------------------- analysis
def analyze() -> None:
    harnesses, ends = read_circuit_summary(S.summary_bytes, S.summary_name)
    complexity, rejected = {}, []
    for name, blob in S.cx_files.items():
        try:
            cx = read_complexity(blob, name)
            cx.complexity_file = name
            if cx.def_id in harnesses:
                complexity[cx.def_id] = cx
            else:
                rejected.append(f"{name} (DEF id {cx.def_id} not in the summary)")
        except Exception as exc:
            rejected.append(f"{name}: {exc}")
    pairs, unmated = resolve(ends, set(harnesses))
    S.result = health.analyze(harnesses, ends, complexity, pairs, unmated)
    S.rejected = rejected


async def on_run() -> None:
    if not (S.summary_bytes and S.cx_files):
        ui.notify("Load the Circuit Summary and complexity files first", type="warning")
        return
    spinner = ui.notification("Analyzing every inline, cavity, and option window…",
                              spinner=True, timeout=None)
    try:
        await run.io_bound(analyze)
    finally:
        spinner.dismiss()
    ui.notify(f"{len(S.result.findings)} findings · {len(S.result.cleared)} auto-cleared",
              type="positive")
    render_results.refresh()
    render_metrics.refresh()


# --------------------------------------------------------------------------- header
with ui.header().classes("items-center justify-between px-6 bg-[#14161c] border-b") \
        .style("border-color:#ffffff20"):
    with ui.row().classes("items-center gap-3"):
        ui.icon("monitor_heart").classes("text-2xl").style(f"color:{BRAND}")
        ui.label("Circuit Health Check").classes("text-lg font-bold tracking-tight")
        ui.label("NiceGUI prototype").classes(
            "text-xs px-2 py-0.5 rounded-full").style(f"background:{BRAND}33;color:{BRAND}")

    @ui.refreshable
    def render_metrics() -> None:
        if S.result is None:
            return
        baseline = health.load_baseline(BASELINE_PATH)
        open_f = S.result.open_findings(baseline)
        cells = [
            ("Blockers open", sum(1 for f in open_f if f.severity == "Blocker"), "#e66767"),
            ("High open", sum(1 for f in open_f if f.severity == "High"), "#c98500"),
            ("Dispositioned", len(S.result.findings) - len(open_f), "#9ca3af"),
            ("Auto-cleared", len(S.result.cleared), "#199e70"),
        ]
        with ui.row().classes("items-center gap-5"):
            for label, value, color in cells:
                with ui.column().classes("items-center gap-0"):
                    ui.label(str(value)).classes("text-xl font-bold leading-none") \
                        .style(f"color:{color}")
                    ui.label(label).classes("text-[11px] opacity-60")

    render_metrics()

# --------------------------------------------------------------------------- inputs
with ui.column().classes("w-full max-w-5xl mx-auto p-6 gap-4"):
    with ui.card().classes("w-full sx-reveal").style("background:#1a1d24"):
        ui.label("Inputs").classes("text-base font-bold")
        ui.label("Circuit Summary + one Harness Complexity per harness. Files are "
                 "matched by the DEF id inside each file, never the filename.") \
            .classes("text-sm opacity-60")
        with ui.row().classes("w-full gap-4"):
            async def on_summary(e) -> None:
                S.summary_bytes, S.summary_name = await e.file.read(), e.file.name
                ui.notify(f"Summary: {e.file.name}", type="positive")

            async def on_cx(e) -> None:
                S.cx_files[e.file.name] = await e.file.read()
                cx_count.set_text(f"{len(S.cx_files)} complexity file(s) loaded")

            ui.upload(label="Circuit Summary (.xlsx)", on_upload=on_summary,
                      auto_upload=True).props('accept=".xlsx" color=primary flat bordered') \
                .classes("flex-1")
            ui.upload(label="Harness Complexity files (.xlsm)", on_upload=on_cx,
                      multiple=True, auto_upload=True) \
                .props('accept=".xlsm,.xlsx" color=primary flat bordered').classes("flex-1")
        cx_count = ui.label("").classes("text-xs opacity-60")
        ui.button("Run health check", icon="play_arrow", on_click=on_run) \
            .props("unelevated").classes("mt-2")

    # ---------------------------------------------------------------------- results
    @ui.refreshable
    def render_results() -> None:
        if S.result is None:
            return
        result = S.result
        baseline = health.load_baseline(BASELINE_PATH)
        dispositions = baseline.get("dispositions", {})

        with ui.card().classes("w-full sx-reveal").style("background:#1a1d24"):
            ui.label("Gate 0 — input health").classes("text-base font-bold")
            for issue in S.rejected:
                ui.label(f"✗ {issue}").classes("text-sm").style("color:#e66767")
            if result.inputs.missing_complexity:
                ui.label("Missing complexity: " + ", ".join(result.inputs.missing_complexity)) \
                    .classes("text-sm").style("color:#c98500")
            if result.inputs.skew_days > 30:
                ui.label(f"Revision skew {result.inputs.skew_days} days — {result.inputs.skew_pair}") \
                    .classes("text-sm").style("color:#c98500")
            rows = [r.__dict__ for r in result.inputs.rows]
            if rows:
                ui.table(rows=rows, columns=[
                    {"name": k, "label": k.replace("_", " ").title(), "field": k, "align": "left"}
                    for k in rows[0]]).classes("w-full").props("dense flat")

        open_f = result.open_findings(baseline)
        done_f = [f for f in result.findings if f not in open_f]

        with ui.card().classes("w-full sx-reveal").style("background:#1a1d24"):
            with ui.tabs().props("dense align=left active-color=primary") as tabs:
                t_open = ui.tab(f"Open ({len(open_f)})")
                t_done = ui.tab(f"Dispositioned ({len(done_f)})")
                t_clear = ui.tab(f"Auto-cleared ({len(result.cleared)})")
            with ui.tab_panels(tabs, value=t_open).classes("w-full") \
                    .props("transition-prev=fade transition-next=fade"):
                with ui.tab_panel(t_open).classes("p-0 pt-2"):
                    if not open_f:
                        ui.label("Nothing open — every finding is dispositioned or cleared.") \
                            .classes("text-sm").style("color:#199e70")
                    for f in open_f:
                        finding_row(f, dispositions)
                with ui.tab_panel(t_done).classes("p-0 pt-2"):
                    for f in done_f:
                        finding_row(f, dispositions)
                with ui.tab_panel(t_clear).classes("p-0 pt-2"):
                    for p in result.cleared[:200]:
                        ui.label(f"{p.inline} · cav {p.cavity} · {p.window}") \
                            .classes("text-xs font-mono opacity-50")

    def finding_row(f, dispositions) -> None:
        d = dispositions.get(f.fingerprint)
        with ui.expansion().classes("w-full sx-reveal") \
                .props("dense expand-icon-toggle switch-toggle-side") as exp:
            with exp.add_slot("header"):
                with ui.row().classes("items-center gap-3 w-full py-1"):
                    sev_chip(f.severity)
                    ui.label(KIND_LABEL.get(f.kind, f.kind)).classes("text-sm font-semibold")
                    ui.label(f"{f.inline}" + (f" · cav {f.cavity}" if f.cavity else "")
                             + (f" · {f.circuit}" if f.circuit else "")) \
                        .classes("text-sm opacity-70")
                    if f.kind == "one_sided_window":
                        ui.label(f"{f.harness_with} → missing on {f.harness_without}") \
                            .classes("text-xs opacity-60 ml-auto")
                    if d:
                        ui.icon("verified").style("color:#199e70").classes("ml-auto")
            ui.label(f.detail).classes("text-sm opacity-80")
            if f.window:
                ui.label(f.window).classes("text-xs font-mono p-2 rounded w-full") \
                    .style("background:#0e1117")
            if f.builds_without:
                ui.label(f"Builds without the wire: {', '.join(f.builds_without)}") \
                    .classes("text-xs").style("color:#e66767")
            if d:
                ui.label(f"{d['verdict']} — {d.get('reason','')} ({d.get('by','')}, {d.get('date','')})") \
                    .classes("text-xs").style("color:#199e70")
            else:
                ui.button("Disposition…", icon="gavel",
                          on_click=lambda f=f: disposition_dialog(f)).props("outline dense")

    def disposition_dialog(f) -> None:
        with ui.dialog() as dialog, ui.card().classes("w-96").style("background:#1a1d24"):
            ui.label("Disposition finding").classes("text-base font-bold")
            with ui.row().classes("items-center gap-2"):
                sev_chip(f.severity)
                ui.label(f"{f.inline} · {f.circuit}").classes("text-sm opacity-70")
            verdict = ui.select(list(health.DISPOSITIONS), value=health.DISPOSITIONS[0],
                                label="Verdict").classes("w-full")
            reason = ui.input("Reason").classes("w-full")
            engineer = ui.input("Engineer", value="SE").classes("w-full")

            def save() -> None:
                baseline = health.load_baseline(BASELINE_PATH)
                health.disposition(baseline, f, verdict.value, reason.value, engineer.value)
                health.save_baseline(BASELINE_PATH, baseline)
                dialog.close()
                ui.notify(f"{f.fingerprint} → {verdict.value}", type="positive")
                render_results.refresh()
                render_metrics.refresh()

            with ui.row().classes("justify-end w-full gap-2"):
                ui.button("Cancel", on_click=dialog.close).props("flat")
                ui.button("Save", on_click=save).props("unelevated")
        dialog.open()

    render_results()


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(port=8503, title="Circuit Health — NiceGUI prototype",
           reload=False, show=False)
