"""The workbench window: drive DEF Editor, or the demo, and watch it work.

tkinter, deliberately. It ships with Python, so the exe is a few megabytes and
building it on a locked-down work PC needs one pip install rather than a
150 MB Qt wheel through a corporate proxy. The theming below is what makes
that a real choice rather than a compromise: ``clam`` is the one built-in ttk
theme whose colours are fully settable, so the window is a dark workbench
rather than a grey 1998 dialog.

Two rules the window obeys, both learned the hard way elsewhere:

* **Nothing slow runs on the UI thread.** Every automation call goes to a
  worker and comes back through ``after()``. A UIA call that takes eight
  seconds against a busy DEF Editor would otherwise freeze the window solid,
  and a frozen window is indistinguishable from a crashed one.
* **Every action is logged with what it did.** The log pane is the point of a
  test harness: when a workflow does the wrong thing you need to see which
  control it touched, not just that the grid looked wrong.
"""

from __future__ import annotations

import queue
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import tkinter as tk
from tkinter import filedialog, ttk

from defauto import application, ids
from defauto.backend import Grid

# --------------------------------------------------------------- palette
BG = "#12151c"          # window ground
PANEL = "#191d27"       # cards and panes
PANEL_HI = "#212736"    # hover / selected
LINE = "#2b3242"        # hairlines
TEXT = "#e6e9f0"
MUTED = "#8b93a7"
ACCENT = "#4c8dff"
OK = "#3fb950"
WARN = "#d29922"
BAD = "#f85149"

MONO = ("Menlo", 11) if hasattr(tk, "_test") else ("Consolas", 10)
UI = ("Segoe UI", 10)
UI_BOLD = ("Segoe UI", 10, "bold")
UI_TITLE = ("Segoe UI", 15, "bold")


class Workbench(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("DEF Editor Automation — prototype")
        self.geometry("1280x820")
        self.minsize(1040, 680)
        self.configure(bg=BG)

        self.session: Optional[application.Session] = None
        self.grid_data: Grid = Grid()
        self.out_dir = Path.cwd() / "exports"
        self._queue: "queue.Queue[Callable[[], None]]" = queue.Queue()

        self._style()
        self._build()
        self.after(50, self._drain)
        self.log("Ready. Connect to DEF Editor, or start in Demo mode.")

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
        style.configure("TButton", background=PANEL_HI, foreground=TEXT,
                        borderwidth=0, focuscolor=PANEL_HI, padding=(12, 6))
        style.map("TButton",
                  background=[("active", LINE), ("disabled", PANEL)],
                  foreground=[("disabled", MUTED)])
        style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff")
        style.map("Accent.TButton", background=[("active", "#3d7ae0"),
                                                ("disabled", LINE)])
        style.configure("Nav.TButton", background=PANEL, foreground=TEXT,
                        anchor="w", padding=(14, 9), borderwidth=0)
        style.map("Nav.TButton", background=[("active", PANEL_HI)])
        style.configure("NavOn.TButton", background=PANEL_HI, foreground=ACCENT,
                        anchor="w", padding=(14, 9), borderwidth=0)
        style.configure("TEntry", fieldbackground=PANEL_HI, foreground=TEXT,
                        insertcolor=TEXT, borderwidth=0, padding=6)
        style.configure("TCombobox", fieldbackground=PANEL_HI, foreground=TEXT,
                        arrowcolor=MUTED, borderwidth=0, padding=5)
        style.map("TCombobox", fieldbackground=[("readonly", PANEL_HI)])
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT,
                        focuscolor=PANEL)
        style.map("TCheckbutton", background=[("active", PANEL)])
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL,
                        foreground=TEXT, borderwidth=0, rowheight=24)
        style.configure("Treeview.Heading", background=PANEL_HI,
                        foreground=MUTED, borderwidth=0, font=UI_BOLD,
                        padding=(8, 6))
        style.map("Treeview.Heading", background=[("active", LINE)])
        style.map("Treeview", background=[("selected", ACCENT)],
                  foreground=[("selected", "#ffffff")])
        style.configure("TPanedwindow", background=BG)
        style.configure("Vertical.TScrollbar", background=PANEL_HI,
                        troughcolor=PANEL, borderwidth=0, arrowcolor=MUTED)
        style.configure("Horizontal.TScrollbar", background=PANEL_HI,
                        troughcolor=PANEL, borderwidth=0, arrowcolor=MUTED)

    # ------------------------------------------------------------- build
    def _build(self) -> None:
        self._build_topbar()
        body = ttk.Frame(self, style="Ground.TFrame")
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self._build_sidebar(body)

        right = ttk.Frame(body, style="Ground.TFrame")
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        self._build_selection(right)

        panes = ttk.PanedWindow(right, orient="vertical")
        panes.pack(fill="both", expand=True, pady=(12, 0))
        self._build_grid(panes)
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

        ttk.Button(bar, text="Diagnose",
                   command=self.on_diagnose).pack(side="right")
        ttk.Button(bar, text="Demo mode",
                   command=self.on_demo).pack(side="right", padx=6)
        ttk.Button(bar, text="Connect to DEF Editor", style="Accent.TButton",
                   command=self.on_connect).pack(side="right")

    def _dot(self, colour: str) -> None:
        self.status_dot.delete("all")
        self.status_dot.create_oval(1, 1, 9, 9, fill=colour, outline="")

    def _build_sidebar(self, parent) -> None:
        side = ttk.Frame(parent, padding=(0, 10, 0, 10), width=210)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)

        ttk.Label(side, text="MODULES", style="Head.TLabel").pack(
            anchor="w", padx=14, pady=(4, 8))
        self.nav_buttons = {}
        for label, handler in (
                ("Harness", self.on_harness),
                ("Devices", self.on_devices),
                ("Circuits", self.on_circuits),
                ("Splices", self.on_splices),
                ("Complexity · Devices", self.on_cx_devices),
                ("Complexity · Circuits", self.on_cx_circuits),
                ("Complexity · Sales Codes", self.on_cx_codes),
                ("Checks · Circuits", self.on_check_circuits),
                ("Checks · Inlines", self.on_check_inlines)):
            button = ttk.Button(side, text=label, style="Nav.TButton",
                                command=handler)
            button.pack(fill="x", padx=8, pady=1)
            self.nav_buttons[label] = button

        ttk.Label(side, text="EXPORT", style="Head.TLabel").pack(
            anchor="w", padx=14, pady=(18, 8))
        ttk.Button(side, text="Export this grid",
                   command=self.on_export).pack(fill="x", padx=8, pady=2)
        ttk.Button(side, text="Choose folder…",
                   command=self.on_choose_folder).pack(fill="x", padx=8, pady=2)

    def _build_selection(self, parent) -> None:
        card = ttk.Frame(parent, padding=(16, 14))
        card.pack(fill="x")

        ttk.Label(card, text="COMPOSITE SELECTION",
                  style="Head.TLabel").grid(row=0, column=0, columnspan=8,
                                            sticky="w", pady=(0, 10))
        self.combo_line = self._combo(card, "Program", 1, 0, self.on_line)
        self.combo_year = self._combo(card, "Model year", 1, 2, self.on_year)
        self.combo_phase = self._combo(card, "Phase", 1, 4, None)
        ttk.Button(card, text="Filter", style="Accent.TButton",
                   command=self.on_filter).grid(row=2, column=6, padx=(12, 0),
                                                sticky="w")

        self.combo_composite = self._combo(card, "Composite", 3, 0,
                                           self.on_composite, width=30)
        self.combo_harness = self._combo(card, "Harness", 3, 2,
                                         self.on_pick_harness, width=24)
        ttk.Button(card, text="Open harness", command=self.on_open_harness) \
            .grid(row=4, column=4, padx=(12, 0), sticky="w")
        for column in range(8):
            card.columnconfigure(column, weight=1 if column in (1, 3, 5) else 0)

    def _combo(self, parent, label: str, row: int, column: int,
               on_change, width: int = 18) -> ttk.Combobox:
        ttk.Label(parent, text=label, style="Muted.TLabel").grid(
            row=row, column=column, sticky="w", padx=(0, 8))
        combo = ttk.Combobox(parent, state="readonly", width=width, font=UI)
        combo.grid(row=row + 1, column=column, sticky="w", padx=(0, 8),
                   pady=(2, 8))
        if on_change is not None:
            combo.bind("<<ComboboxSelected>>", lambda _e: on_change())
        return combo

    def _build_grid(self, panes) -> None:
        frame = ttk.Frame(panes, padding=(16, 14))
        panes.add(frame, weight=3)

        header = ttk.Frame(frame)
        header.pack(fill="x")
        self.grid_title = ttk.Label(header, text="No module open",
                                    style="Title.TLabel")
        self.grid_title.pack(side="left")
        self.grid_count = ttk.Label(header, text="", style="Muted.TLabel")
        self.grid_count.pack(side="left", padx=12)

        self.filter_var = tk.StringVar()
        entry = ttk.Entry(header, textvariable=self.filter_var, width=26,
                          font=UI)
        entry.pack(side="right")
        entry.bind("<Return>", lambda _e: self.on_refilter())
        ttk.Label(header, text="Filter", style="Muted.TLabel").pack(
            side="right", padx=(0, 8))

        self.toggles = ttk.Frame(frame)
        self.toggles.pack(fill="x", pady=(10, 0))
        self.var_missing = tk.BooleanVar()
        self.var_single = tk.BooleanVar()
        self.var_live = tk.BooleanVar()

        holder = ttk.Frame(frame)
        holder.pack(fill="both", expand=True, pady=(10, 0))
        self.tree = ttk.Treeview(holder, show="headings", selectmode="browse")
        vsb = ttk.Scrollbar(holder, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(holder, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        self.tree.tag_configure("odd", background=PANEL)
        self.tree.tag_configure("even", background="#1d2230")
        self.tree.tag_configure("bad", foreground=BAD)

    def _build_log(self, panes) -> None:
        frame = ttk.Frame(panes, padding=(16, 12))
        panes.add(frame, weight=1)
        head = ttk.Frame(frame)
        head.pack(fill="x")
        ttk.Label(head, text="LOG", style="Head.TLabel").pack(side="left")
        ttk.Button(head, text="Clear",
                   command=lambda: self._set_log("")).pack(side="right")
        self.log_text = tk.Text(frame, height=8, bg="#0d1017", fg=MUTED,
                                insertbackground=TEXT, relief="flat",
                                font=MONO, wrap="none", padx=10, pady=8)
        self.log_text.pack(fill="both", expand=True, pady=(8, 0))
        self.log_text.tag_configure("ok", foreground=OK)
        self.log_text.tag_configure("bad", foreground=BAD)
        self.log_text.tag_configure("warn", foreground=WARN)
        self.log_text.configure(state="disabled")

    # --------------------------------------------------------- threading
    def _drain(self) -> None:
        """Run whatever the workers handed back, on the UI thread."""
        while True:
            try:
                self._queue.get_nowait()()
            except queue.Empty:
                break
            except Exception:  # noqa: BLE001 - a callback must not kill the pump
                self.log(traceback.format_exc(), "bad")
        self.after(50, self._drain)

    def run(self, work: Callable[[], object],
            then: Optional[Callable[[object], None]] = None,
            what: str = "") -> None:
        """Do something slow off the UI thread and come back safely."""
        if self.session is None:
            self.log("Not attached — press Connect or Demo mode first.", "warn")
            return
        if what:
            self.log(f"→ {what}")
        # Whatever `work` needs from a widget must be read BEFORE this point.
        # Tk is not thread-safe: `self.filter_var.get()` inside the worker
        # raises "main thread is not in main loop", and because run() reports
        # exceptions into the log rather than crashing, the symptom is a
        # module that quietly shows nothing.

        def worker() -> None:
            try:
                result = work()
            except Exception as exc:  # noqa: BLE001 - reported in the log pane
                message = f"{type(exc).__name__}: {exc}"
                self._queue.put(lambda: self.log(message, "bad"))
                return
            if then is not None:
                self._queue.put(lambda: then(result))

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
        lines = session.composite.vehicle_lines()
        self.combo_line.configure(values=lines)
        if lines:
            self.combo_line.set(lines[0])
            self.on_line()

    def on_demo(self) -> None:
        self._attached(application.demo(out_dir=self.out_dir),
                       "Demo mode — scripted DEF Editor, no application", WARN)

    def on_connect(self) -> None:
        self.log("Connecting to DEF Editor…")
        try:
            session = application.connect(out_dir=self.out_dir)
        except ImportError:
            self.log("pywinauto is not installed — this is the Windows-only "
                     "path. pip install -r requirements.txt", "bad")
            return
        except Exception as exc:  # noqa: BLE001 - shown, not raised
            self.log(f"Could not attach: {exc}", "bad")
            self.log("Is DEF Editor running? Try Demo mode to explore the "
                     "workflow without it.", "warn")
            return
        self._attached(session, "Attached to DEF Editor", OK)

    def on_diagnose(self) -> None:
        if self.session is None:
            self.log("Not attached — press Connect or Demo mode first.", "warn")
            return
        found = self.session.diagnose()
        for auto_id, ok in found:
            self.log(f"  {'found  ' if ok else 'MISSING'}  {auto_id}",
                     "ok" if ok else "bad")
        missing = [a for a, ok in found if not ok]
        if missing:
            self.log(f"{len(missing)} control(s) missing — edit defauto/ids.py",
                     "bad")
        else:
            self.log("All essential controls present.", "ok")

    def on_choose_folder(self) -> None:
        chosen = filedialog.askdirectory(title="Where should exports go?")
        if chosen:
            self.out_dir = Path(chosen)
            if self.session is not None:
                self.session.reports.out_dir = self.out_dir
            self.log(f"Exports will be written to {self.out_dir}")

    # -------------------------------------------------------- selection
    def on_line(self) -> None:
        line = self.combo_line.get()          # read on the UI thread; see run()
        self.run(lambda: self._pick_line(line), self._fill_year,
                 f"select program {line}")

    def _pick_line(self, value: str):
        self.session.backend.select(ids.COMBO_VEHICLE_LINE, value)
        return self.session.composite.model_years()

    def _fill_year(self, years) -> None:
        self.combo_year.configure(values=years)
        self.combo_year.set(years[0] if years else "")
        if years:
            self.on_year()

    def on_year(self) -> None:
        year = self.combo_year.get()
        self.run(lambda: self._pick_year(year), self._fill_phase,
                 f"select model year {year}")

    def _pick_year(self, value: str):
        self.session.backend.select(ids.COMBO_MODEL_YEAR, value)
        return self.session.composite.phases()

    def _fill_phase(self, phases) -> None:
        self.combo_phase.configure(values=phases)
        self.combo_phase.set(phases[0] if phases else "")

    def on_filter(self) -> None:
        phase = self.combo_phase.get()
        self.run(lambda: self._search(phase), self._filtered,
                 f"Filter composites for phase {phase}")

    def _search(self, phase: str):
        self.session.backend.select(ids.COMBO_PHASE, phase)
        grid = self.session.composite.search()
        return grid, self.session.composite.composites()

    def _filtered(self, result) -> None:
        grid, composites = result
        self._show("Composites", grid)
        self.combo_composite.configure(values=composites)
        if composites:
            self.combo_composite.set(composites[0])
            self.on_composite()
        else:
            self.log("No composites came back — check the three combo boxes.",
                     "warn")

    def on_composite(self) -> None:
        name = self.combo_composite.get()
        self.run(lambda: self._pick_composite(name), self._fill_harness,
                 f"select composite {name}")

    def _pick_composite(self, name: str):
        self.session.composite.choose_composite(name)
        return self.session.composite.harnesses()

    def _fill_harness(self, harnesses) -> None:
        self.combo_harness.configure(values=harnesses)
        if harnesses:
            self.combo_harness.set(harnesses[0])

    def on_pick_harness(self) -> None:
        pass    # chosen on Open, so a mis-click does not navigate

    def on_open_harness(self) -> None:
        name = self.combo_harness.get()
        if not name:
            self.log("Pick a harness first.", "warn")
            return
        self.run(lambda: self._open_harness(name),
                 lambda sel: self.log(f"Open: {sel}", "ok"),
                 f"open harness {name}")

    def _open_harness(self, name: str):
        self.session.composite.choose_harness(name)
        self.session.harness.open()
        return self.session.composite.selection

    # ----------------------------------------------------------- modules
    def _mark(self, label: str) -> None:
        for name, button in self.nav_buttons.items():
            button.configure(style="NavOn.TButton" if name == label
                             else "Nav.TButton")

    def _clear_toggles(self) -> None:
        for child in self.toggles.winfo_children():
            child.destroy()

    def _module(self, label: str, work, toggles: bool = False) -> None:
        self._mark(label)
        self._clear_toggles()
        if toggles:
            for text, var, handler in (
                    ("Only missing", self.var_missing, self.on_circuits),
                    ("Only single-ended", self.var_single, self.on_circuits),
                    ("Live checks", self.var_live, self.on_circuits)):
                ttk.Checkbutton(self.toggles, text=text, variable=var,
                                command=handler).pack(side="left", padx=(0, 16))
        self.run(work, lambda grid: self._show(label, grid), f"open {label}")

    def on_harness(self) -> None:
        self._module("Harness", lambda: (self.session.harness.open(),
                                         self.session.composite.search())[1])

    def on_devices(self) -> None:
        needle = self.filter_var.get()
        self._module("Devices", lambda: (self.session.devices.open(),
                                         self.session.devices.read(needle))[1])

    def on_circuits(self) -> None:
        needle = self.filter_var.get()
        live, missing = self.var_live.get(), self.var_missing.get()
        single = self.var_single.get()

        def work():
            self.session.circuits.open()
            self.session.circuits.live_checks(live)
            self.session.circuits.only_missing(missing)
            self.session.circuits.only_single_ended(single)
            return self.session.circuits.read(needle)
        self._module("Circuits", work, toggles=True)

    def on_splices(self) -> None:
        needle = self.filter_var.get()
        self._module("Splices", lambda: (self.session.splices.open(),
                                         self.session.splices.read(needle))[1])

    def on_cx_devices(self) -> None:
        needle = self.filter_var.get()
        self._module("Complexity · Devices",
                     lambda: self.session.complexity.devices(needle))

    def on_cx_circuits(self) -> None:
        needle = self.filter_var.get()
        self._module("Complexity · Circuits",
                     lambda: self.session.complexity.circuits(needle))

    def on_cx_codes(self) -> None:
        needle = self.filter_var.get()

        def work():
            grid = self.session.complexity.sales_codes(needle)
            compare = self.session.complexity.compare_codes()
            self._queue.put(lambda: self.log(
                f"available only: {compare['available_only'] or '—'} · "
                f"used only: {compare['used_only'] or '—'}"))
            return grid
        self._module("Complexity · Sales Codes", work)

    def on_check_circuits(self) -> None:
        def work():
            result = self.session.quality.circuits()
            self._queue.put(lambda: self.log(result.summary,
                                             "ok" if result.passed else "bad"))
            self._queue.put(lambda: self.log(result.text))
            return self.session.circuits.read()
        self._module("Checks · Circuits", work)

    def on_check_inlines(self) -> None:
        self._mark("Checks · Inlines")
        self._clear_toggles()
        ttk.Button(self.toggles, text="Run all pairs",
                   command=self.on_run_inline).pack(side="left")
        ttk.Button(self.toggles, text="Sign off",
                   command=self.on_sign_off).pack(side="left", padx=8)
        self.run(lambda: self.session.quality.inline_pairs(),
                 lambda grid: self._show("Checks · Inlines", grid),
                 "open inline checks")

    def on_run_inline(self) -> None:
        def then(result) -> None:
            self.log(result.summary, "ok" if result.passed else "bad")
            self.log(result.text)
            self._show("Checks · Inlines", result.rows)
        self.run(lambda: self.session.quality.run_inline(), then,
                 "run all inline pairs")

    def on_sign_off(self) -> None:
        self.run(lambda: self.session.quality.sign_off(),
                 lambda r: self.log(r.text, "ok"), "sign off inline check")

    def on_refilter(self) -> None:
        label = next((n for n, b in self.nav_buttons.items()
                      if str(b.cget("style")) == "NavOn.TButton"), None)
        handler = {"Devices": self.on_devices, "Circuits": self.on_circuits,
                   "Splices": self.on_splices,
                   "Complexity · Devices": self.on_cx_devices,
                   "Complexity · Circuits": self.on_cx_circuits,
                   "Complexity · Sales Codes": self.on_cx_codes}.get(label or "")
        if handler:
            handler()

    # -------------------------------------------------------------- grid
    def _show(self, title: str, grid: Grid) -> None:
        self.grid_data = grid
        self.grid_title.configure(text=title)
        self.grid_count.configure(
            text=f"{len(grid)} row(s) · {len(grid.headers)} column(s)")
        self.tree.delete(*self.tree.get_children())
        self.tree.configure(columns=grid.headers)
        for header in grid.headers:
            self.tree.heading(header, text=header)
            width = max(90, min(260, 11 * (len(header) + 6)))
            self.tree.column(header, width=width, anchor="w", stretch=True)
        for index, row in enumerate(grid.rows):
            tags = ["even" if index % 2 else "odd"]
            if any(str(cell).strip().lower() in ("mismatch", "fail", "missing")
                   for cell in row):
                tags.append("bad")
            self.tree.insert("", "end", values=row, tags=tuple(tags))
        self.log(f"   {len(grid)} row(s)")

    def on_export(self) -> None:
        if not len(self.grid_data):
            self.log("Nothing to export — open a module first.", "warn")
            return
        name = self.grid_title.cget("text")
        try:
            report = self.session.reports.save(name, self.grid_data)
        except Exception as exc:  # noqa: BLE001 - shown, not raised
            self.log(f"Export failed: {exc}", "bad")
            return
        self.log(f"Wrote {report.written}", "ok")


def main() -> None:
    Workbench().mainloop()


if __name__ == "__main__":
    main()
