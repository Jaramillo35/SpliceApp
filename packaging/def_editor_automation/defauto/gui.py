"""The automation test window: four fields, one button, ten steps.

This is a test harness, not a tool. It answers one question — can this reach a
harness in DEF Editor through UI Automation and filter its circuits? — and the
window is built so the answer is readable at a glance:

* four inputs, because those are the four an engineer knows;
* every step of the run listed with its own PASS/FAIL and a sentence saying
  what happened, so a failure names the step rather than leaving a traceback;
* the run stops at the first failure, because step 7 tells you nothing once
  step 3 did not happen.

tkinter, deliberately: it ships with Python, so building the exe on a
locked-down work PC is one pip install rather than a 150 MB Qt wheel through a
corporate proxy. ``clam`` is the one built-in ttk theme whose colours are
fully settable, which is what makes this a dark workbench rather than a grey
1998 dialog.

Nothing slow runs on the UI thread: the run goes to a worker and each step
comes back through ``after()``. Tk is not thread-safe, so **every widget value
a worker needs is read before the worker starts** — reading one inside the
worker raises "main thread is not in main loop", and because failures are
reported into the log rather than crashing, the symptom is a window that
quietly does nothing.
"""

from __future__ import annotations

import queue
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import tkinter as tk
from tkinter import ttk

from defauto import application, workflow
from defauto.backend import Grid

# --------------------------------------------------------------- palette
BG = "#12151c"
PANEL = "#191d27"
PANEL_HI = "#212736"
LINE = "#2b3242"
TEXT = "#e6e9f0"
MUTED = "#8b93a7"
ACCENT = "#4c8dff"
OK = "#3fb950"
WARN = "#d29922"
BAD = "#f85149"

UI = ("Segoe UI", 10)
UI_BOLD = ("Segoe UI", 10, "bold")
UI_TITLE = ("Segoe UI", 15, "bold")
MONO = ("Consolas", 10)


class Workbench(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("DEF Editor Automation — navigation test")
        self.geometry("1080x780")
        self.minsize(900, 640)
        self.configure(bg=BG)

        self.session: Optional[application.Session] = None
        self.grid_data: Grid = Grid()
        self.out_dir = Path.cwd() / "exports"
        self._queue: "queue.Queue[Callable[[], None]]" = queue.Queue()
        self._step_rows: list = []

        self._style()
        self._build()
        self.after(50, self._drain)
        self.log("Ready. Connect to DEF Editor, or press Demo mode to try the "
                 "run without it.")

    # ------------------------------------------------------------- style
    def _style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=PANEL, foreground=TEXT,
                        fieldbackground=PANEL, bordercolor=LINE, font=UI)
        style.configure("TFrame", background=PANEL)
        style.configure("Ground.TFrame", background=BG)
        style.configure("TLabel", background=PANEL, foreground=TEXT)
        style.configure("Muted.TLabel", background=PANEL, foreground=MUTED)
        style.configure("Title.TLabel", background=PANEL, foreground=TEXT,
                        font=UI_TITLE)
        style.configure("Head.TLabel", background=PANEL, foreground=MUTED,
                        font=("Segoe UI", 9, "bold"))
        style.configure("Ok.TLabel", background=PANEL, foreground=OK,
                        font=("Consolas", 10, "bold"))
        style.configure("Bad.TLabel", background=PANEL, foreground=BAD,
                        font=("Consolas", 10, "bold"))
        style.configure("Wait.TLabel", background=PANEL, foreground=MUTED,
                        font=MONO)
        style.configure("TButton", background=PANEL_HI, foreground=TEXT,
                        borderwidth=0, focuscolor=PANEL_HI, padding=(12, 6))
        style.map("TButton", background=[("active", LINE), ("disabled", PANEL)],
                  foreground=[("disabled", MUTED)])
        style.configure("Accent.TButton", background=ACCENT,
                        foreground="#ffffff", padding=(18, 8), font=UI_BOLD)
        style.map("Accent.TButton", background=[("active", "#3d7ae0"),
                                                ("disabled", LINE)])
        style.configure("TEntry", fieldbackground=PANEL_HI, foreground=TEXT,
                        insertcolor=TEXT, borderwidth=0, padding=6)
        style.configure("TCombobox", fieldbackground=PANEL_HI, foreground=TEXT,
                        arrowcolor=MUTED, borderwidth=0, padding=5)
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL,
                        foreground=TEXT, borderwidth=0, rowheight=24)
        style.configure("Treeview.Heading", background=PANEL_HI,
                        foreground=MUTED, borderwidth=0, font=UI_BOLD,
                        padding=(8, 6))
        style.map("Treeview", background=[("selected", ACCENT)],
                  foreground=[("selected", "#ffffff")])
        style.configure("TPanedwindow", background=BG)
        style.configure("Vertical.TScrollbar", background=PANEL_HI,
                        troughcolor=PANEL, borderwidth=0, arrowcolor=MUTED)

    # ------------------------------------------------------------- build
    def _build(self) -> None:
        self._build_topbar()
        body = ttk.Frame(self, style="Ground.TFrame")
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self._build_form(body)

        panes = ttk.PanedWindow(body, orient="vertical")
        panes.pack(fill="both", expand=True, pady=(12, 0))
        self._build_steps(panes)
        self._build_result(panes)
        self._build_log(panes)

    def _build_topbar(self) -> None:
        bar = ttk.Frame(self, padding=(16, 12))
        bar.pack(fill="x", padx=12, pady=12)
        ttk.Label(bar, text="DEF Editor Automation",
                  style="Title.TLabel").pack(side="left")
        self.status_dot = tk.Canvas(bar, width=10, height=10, bg=PANEL,
                                    highlightthickness=0)
        self.status_dot.pack(side="left", padx=(16, 6))
        self._dot(MUTED)
        self.status = ttk.Label(bar, text="Not attached", style="Muted.TLabel")
        self.status.pack(side="left")
        ttk.Button(bar, text="Demo mode",
                   command=self.on_demo).pack(side="right", padx=6)
        ttk.Button(bar, text="Connect to DEF Editor", style="Accent.TButton",
                   command=self.on_connect).pack(side="right")

    def _dot(self, colour: str) -> None:
        self.status_dot.delete("all")
        self.status_dot.create_oval(1, 1, 9, 9, fill=colour, outline="")

    def _build_form(self, parent) -> None:
        card = ttk.Frame(parent, padding=(16, 14))
        card.pack(fill="x")
        ttk.Label(card, text="WHAT TO OPEN", style="Head.TLabel").grid(
            row=0, column=0, columnspan=6, sticky="w", pady=(0, 10))

        self.field_program = self._field(card, "Program", 1, 0)
        self.field_year = self._field(card, "Model year", 1, 1)
        self.field_phase = self._field(card, "Phase", 1, 2)
        self.field_harness = self._field(card, "Harness", 1, 3, width=24)
        self.field_program.bind("<<ComboboxSelected>>",
                                lambda _e: self._offer_years())
        self.field_year.bind("<<ComboboxSelected>>",
                             lambda _e: self._offer_harnesses())
        self.field_phase.bind("<<ComboboxSelected>>",
                              lambda _e: self._offer_harnesses())

        self.run_button = ttk.Button(
            card, text=f"Run test  →  filter circuit {workflow.TARGET_CIRCUIT}",
            style="Accent.TButton", command=self.on_run)
        self.run_button.grid(row=2, column=4, padx=(16, 0), sticky="w")

        ttk.Label(card, text="The composite is found for you: DEF Editor needs "
                             "one to reach a harness, so the run searches the "
                             "composites this programme returned.",
                  style="Muted.TLabel", wraplength=880, justify="left").grid(
            row=3, column=0, columnspan=6, sticky="w", pady=(10, 0))

    def _field(self, parent, label: str, row: int, column: int,
               width: int = 16) -> ttk.Combobox:
        ttk.Label(parent, text=label, style="Muted.TLabel").grid(
            row=row, column=column, sticky="w", padx=(0, 12))
        # editable on purpose: the values are typed, and once attached the
        # dropdown offers what DEF Editor actually has
        box = ttk.Combobox(parent, width=width, font=UI)
        box.grid(row=row + 1, column=column, sticky="w", padx=(0, 12))
        return box

    def _build_steps(self, panes) -> None:
        frame = ttk.Frame(panes, padding=(16, 14))
        panes.add(frame, weight=2)
        ttk.Label(frame, text="RUN", style="Head.TLabel").pack(anchor="w")
        self.steps_box = ttk.Frame(frame)
        self.steps_box.pack(fill="both", expand=True, pady=(10, 0))
        self.verdict = ttk.Label(frame, text="", style="Muted.TLabel",
                                 wraplength=940, justify="left")
        self.verdict.pack(anchor="w", pady=(10, 0))

    def _build_result(self, panes) -> None:
        frame = ttk.Frame(panes, padding=(16, 12))
        panes.add(frame, weight=2)
        head = ttk.Frame(frame)
        head.pack(fill="x")
        self.result_title = ttk.Label(head, text="RESULT", style="Head.TLabel")
        self.result_title.pack(side="left")
        ttk.Button(head, text="Export CSV",
                   command=self.on_export).pack(side="right")

        holder = ttk.Frame(frame)
        holder.pack(fill="both", expand=True, pady=(10, 0))
        self.tree = ttk.Treeview(holder, show="headings", selectmode="browse")
        vsb = ttk.Scrollbar(holder, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        self.tree.tag_configure("odd", background=PANEL)
        self.tree.tag_configure("even", background="#1d2230")

    def _build_log(self, panes) -> None:
        frame = ttk.Frame(panes, padding=(16, 12))
        panes.add(frame, weight=1)
        head = ttk.Frame(frame)
        head.pack(fill="x")
        ttk.Label(head, text="LOG", style="Head.TLabel").pack(side="left")
        ttk.Button(head, text="Clear",
                   command=lambda: self._set_log("")).pack(side="right")
        self.log_text = tk.Text(frame, height=6, bg="#0d1017", fg=MUTED,
                                insertbackground=TEXT, relief="flat",
                                font=MONO, wrap="none", padx=10, pady=8)
        self.log_text.pack(fill="both", expand=True, pady=(8, 0))
        self.log_text.tag_configure("ok", foreground=OK)
        self.log_text.tag_configure("bad", foreground=BAD)
        self.log_text.tag_configure("warn", foreground=WARN)
        self.log_text.configure(state="disabled")

    # --------------------------------------------------------- threading
    def _drain(self) -> None:
        while True:
            try:
                self._queue.get_nowait()()
            except queue.Empty:
                break
            except Exception:  # noqa: BLE001 - a callback must not kill the pump
                self.log(traceback.format_exc(), "bad")
        self.after(50, self._drain)

    def _post(self, call: Callable[[], None]) -> None:
        self._queue.put(call)

    def _run(self, work: Callable[[], object],
             then: Optional[Callable[[object], None]] = None) -> None:
        """Do something slow off the UI thread and come back safely."""
        if self.session is None:
            return

        def worker() -> None:
            try:
                result = work()
            except Exception as exc:  # noqa: BLE001 - reported in the log pane
                message = f"{type(exc).__name__}: {exc}"
                self._post(lambda: self.log(message, "bad"))
                return
            if then is not None:
                self._post(lambda: then(result))

        threading.Thread(target=worker, daemon=True).start()

    # -------------------------------------------------------------- log
    def log(self, message: str, tag: str = "") -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        for line in str(message).rstrip().splitlines() or [""]:
            self.log_text.insert("end", f"{stamp}  {line}\n", tag or ())
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_log(self, value: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        if value:
            self.log_text.insert("end", value)
        self.log_text.configure(state="disabled")

    # -------------------------------------------------------- connection
    def _attached(self, session, label: str, colour: str) -> None:
        self.session = session
        self.session.reports.out_dir = self.out_dir
        self._dot(colour)
        self.status.configure(text=label)
        self.log(f"Attached: {label}", "ok")
        try:
            lines = session.composite.vehicle_lines()
        except Exception as exc:  # noqa: BLE001 - shown, not raised
            self.log(f"Could not read the program list: {exc}", "warn")
            return
        self.field_program.configure(values=lines)
        if lines and not self.field_program.get():
            self.field_program.set(lines[0])
        self._offer_years()

    def _offer_years(self) -> None:
        """Offer the years and phases this program actually has."""
        program = self.field_program.get().strip()
        if not program:
            return

        def work():
            from defauto import ids
            if program not in self.session.composite.vehicle_lines():
                return None
            self.session.backend.select(ids.COMBO_VEHICLE_LINE, program)
            return (self.session.composite.model_years(),
                    self.session.composite.phases())

        def then(result) -> None:
            if result is None:
                return
            years, phases = result
            self.field_year.configure(values=years)
            self.field_phase.configure(values=phases)
            if years and not self.field_year.get():
                self.field_year.set(years[0])
            if phases and not self.field_phase.get():
                self.field_phase.set(phases[0])
            self._offer_harnesses()

        self._run(work, then)

    def _offer_harnesses(self) -> None:
        """Every harness in this programme, so the field is picked not guessed."""
        program = self.field_program.get().strip()
        year = self.field_year.get().strip()
        phase = self.field_phase.get().strip()
        if not all((program, year, phase)):
            return

        def work():
            self.session.composite.choose_programme(program, year, phase)
            if not len(self.session.composite.search()):
                return []
            names = set()
            for composite in self.session.composite.composites():
                self.session.composite.choose_composite(composite)
                names.update(self.session.composite.harnesses())
            return sorted(names)

        def then(names) -> None:
            self.field_harness.configure(values=names)
            if names and not self.field_harness.get():
                self.field_harness.set(names[0])

        self._run(work, then)

    def on_demo(self) -> None:
        self._attached(application.demo(out_dir=self.out_dir),
                       "Demo mode — scripted DEF Editor, no application", WARN)

    def on_connect(self) -> None:
        self.log("Connecting to DEF Editor…")
        try:
            session = application.connect(out_dir=self.out_dir)
        except ImportError:
            self.log("pywinauto is not installed — that is the Windows-only "
                     "path. pip install -r requirements.txt", "bad")
            return
        except Exception as exc:  # noqa: BLE001 - shown, not raised
            self.log(f"Could not attach: {exc}", "bad")
            self.log("Is DEF Editor running and signed in? Demo mode runs the "
                     "same steps without it.", "warn")
            return
        self._attached(session, "Attached to DEF Editor", OK)

    # ---------------------------------------------------------- the test
    def on_run(self) -> None:
        if self.session is None:
            self.log("Not attached — press Connect or Demo mode first.", "warn")
            return
        # read every field HERE, on the UI thread; see the module docstring
        program = self.field_program.get().strip()
        year = self.field_year.get().strip()
        phase = self.field_phase.get().strip()
        harness = self.field_harness.get().strip()
        blank = [name for name, value in (("program", program), ("year", year),
                                          ("phase", phase),
                                          ("harness", harness)) if not value]
        if blank:
            self.log(f"Fill in: {', '.join(blank)}", "warn")
            return

        self._show_plan(workflow.plan(program, year, phase, harness))
        self.verdict.configure(text="Running…", style="Muted.TLabel")
        self.run_button.state(["disabled"])
        self.tree.delete(*self.tree.get_children())
        self.log(f"Run: {program} / {year} / {phase} / {harness} "
                 f"→ circuit {workflow.TARGET_CIRCUIT}")

        def on_step(step) -> None:
            self._post(lambda s=step: self._update_step(s))

        def then(outcome) -> None:
            self.run_button.state(["!disabled"])
            self._finish(outcome)

        self._run(lambda: workflow.run(self.session, program, year, phase,
                                       harness, on_step=on_step), then)

    def _show_plan(self, steps) -> None:
        for child in self.steps_box.winfo_children():
            child.destroy()
        self._step_rows = []
        for index, step in enumerate(steps):
            row = ttk.Frame(self.steps_box)
            row.pack(fill="x", pady=1)
            mark = ttk.Label(row, text="....", style="Wait.TLabel", width=6)
            mark.pack(side="left")
            ttk.Label(row, text=f"{index + 1}. {step.name}").pack(side="left")
            detail = ttk.Label(row, text="", style="Muted.TLabel")
            detail.pack(side="left", padx=(12, 0))
            self._step_rows.append((step.name, mark, detail))

    def _update_step(self, step) -> None:
        for name, mark, detail in self._step_rows:
            if name == step.name:
                mark.configure(text=step.mark,
                               style="Ok.TLabel" if step.ok else "Bad.TLabel")
                detail.configure(text=step.detail)
                self.log(f"  {step.mark}  {step.name} — {step.detail}",
                         "ok" if step.ok else "bad")
                return

    def _finish(self, outcome) -> None:
        if outcome.ok:
            self.verdict.configure(
                text=f"PASSED — reached {self.field_harness.get()} in "
                     f"{outcome.composite} and filtered "
                     f"{workflow.TARGET_CIRCUIT}: {len(outcome.grid)} row(s).",
                style="Ok.TLabel")
            self.log("Test passed.", "ok")
        else:
            failed = outcome.failed
            where = (f"step {outcome.steps.index(failed) + 1}, {failed.name}"
                     if failed else "an unknown step")
            self.verdict.configure(
                text=(f"FAILED at {where} — {failed.detail}" if failed
                      else "FAILED"), style="Bad.TLabel")
            self.log(f"Test failed at {where}.", "bad")
        self._show(outcome.grid)

    def _show(self, grid: Grid) -> None:
        self.grid_data = grid
        self.result_title.configure(
            text=f"RESULT — circuit {workflow.TARGET_CIRCUIT}: "
                 f"{len(grid)} row(s)")
        self.tree.delete(*self.tree.get_children())
        self.tree.configure(columns=grid.headers)
        for header in grid.headers:
            self.tree.heading(header, text=header)
            self.tree.column(header, anchor="w", stretch=True,
                             width=max(90, min(280, 11 * (len(header) + 8))))
        for index, row in enumerate(grid.rows):
            self.tree.insert("", "end", values=row,
                             tags=("even" if index % 2 else "odd",))

    def on_export(self) -> None:
        if not len(self.grid_data):
            self.log("Nothing to export — run the test first.", "warn")
            return
        try:
            report = self.session.reports.save(
                f"Circuits_{workflow.TARGET_CIRCUIT}", self.grid_data)
        except Exception as exc:  # noqa: BLE001 - shown, not raised
            self.log(f"Export failed: {exc}", "bad")
            return
        self.log(f"Wrote {report.written}", "ok")


def main() -> None:
    Workbench().mainloop()


if __name__ == "__main__":
    main()
