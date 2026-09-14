"""The Terminal Material updater: attach, load the Excel, preview, apply.

The engineer navigates DEF Editor by hand to Edit Harness → Circuits. This
window then takes an Excel list — CNUM, Circuit Name, Terminal — and sets
each matching row's Term Matl. It is the one thing in the kit that writes
into DEF Editor, and the window is shaped by that:

* **Read the page first.** The circuits DEF Editor is showing are extracted
  — Connector No, Circuit, Term Matl — and listed. The Excel is matched
  against those and nothing else; a row whose circuit is not on the page is
  counted, kept for the CSV, and left out of the preview.
* **Preview before apply.** Every matched row is shown with what would
  happen — change (with the current value), already, no value, unknown
  value — and nothing is touched. Apply is enabled only once a preview
  exists, and applies exactly what the preview said.
* **One result per row.** After apply, each row says applied or failed
  (read back different), and the whole table exports as CSV for the record.
* **Nothing is guessed.** Silver, Gold and Tin are the only values the
  source list uses; anything else is reported and left alone.

The RECORD STRUCTURE card stays: when a step fails on Windows, the
application's real UI Automation tree is what shows why.

tkinter, deliberately: it ships with Python, so the exe builds on a
locked-down work PC with one pip install. Nothing slow runs on the UI thread;
every widget value a worker needs is read before the worker starts, because
Tk is not thread-safe and a read from the worker fails silently into the log.
"""

from __future__ import annotations

import queue
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

import tkinter as tk
from tkinter import filedialog, ttk

from defauto import application, termmatl

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

#: a row's colour in the preview, by what will happen to it
STATUS_TAG = {termmatl.CHANGE: "change", termmatl.APPLIED: "ok",
              termmatl.ALREADY: "quiet", termmatl.NO_VALUE: "quiet",
              termmatl.NOT_FOUND: "bad", termmatl.UNKNOWN: "bad",
              termmatl.FAILED: "bad"}


class Workbench(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("DEF Editor Automation — Terminal Material")
        self.geometry("1120x800")
        self.minsize(940, 660)
        self.configure(bg=BG)

        self.session: Optional[application.Session] = None
        self.updates: List[termmatl.Update] = []
        self.updates_name: str = ""
        self.circuits: Optional[termmatl.Circuits] = None
        self.planned: List[termmatl.Planned] = []
        self.out_dir = Path.cwd() / "exports"
        self._queue: "queue.Queue[Callable[[], None]]" = queue.Queue()
        self._recorder = None
        self._auto_job = None

        self._style()
        self._build()
        self.after(50, self._drain)
        self.log("Ready. In DEF Editor, open Edit Harness → Circuits by hand, then "
                 "Connect here and Read circuits. Demo mode runs the same steps "
                 "without it.")

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
        style.configure("Ok.TLabel", background=PANEL, foreground=OK, font=UI_BOLD)
        style.configure("Bad.TLabel", background=PANEL, foreground=BAD, font=UI_BOLD)
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
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT,
                        focuscolor=PANEL)
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
        self._build_inputs(body)
        panes = ttk.PanedWindow(body, orient="vertical")
        panes.pack(fill="both", expand=True, pady=(12, 0))
        self._build_preview(panes)
        self._build_log(panes)
        self._build_recorder(body)

    def _build_topbar(self) -> None:
        bar = ttk.Frame(self, padding=(16, 12))
        bar.pack(fill="x", padx=12, pady=12)
        ttk.Label(bar, text="DEF Editor Automation — Terminal Material",
                  style="Title.TLabel").pack(side="left")
        self.status_dot = tk.Canvas(bar, width=10, height=10, bg=PANEL,
                                    highlightthickness=0)
        self.status_dot.pack(side="left", padx=(16, 6))
        self._dot(MUTED)
        self.status = ttk.Label(bar, text="Not attached", style="Muted.TLabel")
        self.status.pack(side="left")
        ttk.Button(bar, text="Demo mode", command=self.on_demo).pack(side="right", padx=6)
        ttk.Button(bar, text="Connect to DEF Editor", style="Accent.TButton",
                   command=self.on_connect).pack(side="right")

    def _dot(self, colour: str) -> None:
        self.status_dot.delete("all")
        self.status_dot.create_oval(1, 1, 9, 9, fill=colour, outline="")

    def _build_inputs(self, parent) -> None:
        card = ttk.Frame(parent, padding=(16, 14))
        card.pack(fill="x")
        ttk.Label(card, text="UPDATE LIST", style="Head.TLabel").grid(
            row=0, column=0, columnspan=5, sticky="w", pady=(0, 8))
        self.read_button = ttk.Button(card, text="1  Read circuits",
                                      command=self.on_read_circuits)
        self.read_button.grid(row=1, column=0, sticky="w")
        ttk.Button(card, text="2  Choose Excel…", command=self.on_choose_file) \
            .grid(row=1, column=1, sticky="w", padx=(8, 0))
        self.file_label = ttk.Label(card, text="no file — columns: CNUM, Circuit Name, "
                                               "Terminal (Silver / Gold / Tin / empty)",
                                    style="Muted.TLabel")
        self.file_label.grid(row=1, column=2, sticky="w", padx=(12, 0))
        self.preview_button = ttk.Button(card, text="3  Preview", command=self.on_preview)
        self.preview_button.grid(row=1, column=3, sticky="w", padx=(16, 0))
        self.apply_button = ttk.Button(card, text="4  Apply", style="Accent.TButton",
                                       command=self.on_apply)
        self.apply_button.grid(row=1, column=4, sticky="w", padx=(8, 0))
        self.apply_button.state(["disabled"])
        ttk.Label(card, text="Read circuits extracts what DEF Editor's Circuits page "
                             "shows — Connector No, Circuit, Term Matl — and lists it. "
                             "Preview matches the Excel to those circuits only — CNUM to "
                             "Connector No, Circuit Name to Circuit — and touches "
                             "nothing; a row whose circuit is not on the page is counted "
                             "and left out. Apply sets exactly the rows marked 'Will "
                             "change' and reads each one back.",
                  style="Muted.TLabel", wraplength=1000, justify="left").grid(
            row=2, column=0, columnspan=5, sticky="w", pady=(10, 0))

    def _build_preview(self, panes) -> None:
        frame = ttk.Frame(panes, padding=(16, 12))
        panes.add(frame, weight=3)
        head = ttk.Frame(frame)
        head.pack(fill="x")
        self.summary = ttk.Label(head, text="PREVIEW", style="Head.TLabel")
        self.summary.pack(side="left")
        ttk.Button(head, text="Export results CSV",
                   command=self.on_export).pack(side="right")
        # Both tables at once, the page above the preview: what DEF Editor
        # shows is the frame of reference for what the list would change.
        # (Two stacked frames, not a ttk.Notebook: a Notebook in this window
        # hung Tk's event loop on macOS when a second window was built in the
        # same process — the test suite — and nothing here needs tabs.)
        split = ttk.PanedWindow(frame, orient="vertical")
        split.pack(fill="both", expand=True, pady=(10, 0))

        circuits_box = ttk.Frame(split)
        split.add(circuits_box, weight=1)
        self.circuits_head = ttk.Label(circuits_box, text="CIRCUITS ON THIS PAGE — "
                                                          "press Read circuits",
                                       style="Head.TLabel")
        self.circuits_head.pack(anchor="w", pady=(0, 6))
        self.circuits_columns = ["Row", "Connector No", "Circuit", "Term Matl",
                                 "The list says"]
        self.circuits_tree = self._table(
            circuits_box, self.circuits_columns,
            {"Row": 60, "Connector No": 140, "Circuit": 140, "Term Matl": 140,
             "The list says": 320}, stretch="The list says")

        preview_box = ttk.Frame(split)
        split.add(preview_box, weight=1)
        self.preview_head = ttk.Label(preview_box, text="PREVIEW — rows of the list "
                                                        "that are on this page",
                                      style="Head.TLabel")
        self.preview_head.pack(anchor="w", pady=(8, 6))
        self.columns = ["Excel row", "CNUM", "Circuit", "Terminal", "Current",
                        "Set to", "Rows", "Status", "Detail"]
        self.tree = self._table(
            preview_box, self.columns,
            {"Excel row": 80, "CNUM": 100, "Circuit": 110, "Terminal": 100,
             "Current": 120, "Set to": 100, "Rows": 60, "Status": 190, "Detail": 320},
            stretch="Detail")

    def _table(self, parent, columns, widths, stretch: str) -> ttk.Treeview:
        holder = ttk.Frame(parent)
        holder.pack(fill="both", expand=True)
        tree = ttk.Treeview(holder, show="headings", selectmode="browse",
                            columns=columns)
        for name in columns:
            tree.heading(name, text=name)
            tree.column(name, width=widths[name], anchor="w", stretch=(name == stretch))
        vsb = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        tree.tag_configure("change", foreground=ACCENT)
        tree.tag_configure("ok", foreground=OK)
        tree.tag_configure("quiet", foreground=MUTED)
        tree.tag_configure("bad", foreground=BAD)
        return tree

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
        for tag, colour in (("ok", OK), ("bad", BAD), ("warn", WARN)):
            self.log_text.tag_configure(tag, foreground=colour)
        self.log_text.configure(state="disabled")

    def _build_recorder(self, parent) -> None:
        card = ttk.Frame(parent, padding=(16, 12))
        card.pack(fill="x", pady=(12, 0))
        ttk.Label(card, text="RECORD STRUCTURE", style="Head.TLabel").grid(
            row=0, column=0, columnspan=5, sticky="w", pady=(0, 8))
        ttk.Label(card, text="Label", style="Muted.TLabel").grid(row=1, column=0, sticky="w")
        self.rec_label = ttk.Entry(card, width=28, font=UI)
        self.rec_label.insert(0, "circuits page")
        self.rec_label.grid(row=2, column=0, sticky="w", padx=(0, 12))
        ttk.Button(card, text="Snapshot now", command=self.on_snapshot) \
            .grid(row=2, column=1, sticky="w", padx=(0, 8))
        self.rec_auto = tk.BooleanVar(value=False)
        ttk.Checkbutton(card, text="Auto: snapshot whenever the window changes",
                        variable=self.rec_auto, command=self.on_auto_toggle) \
            .grid(row=2, column=2, sticky="w", padx=(0, 8))
        self.rec_redact = tk.BooleanVar(value=True)
        ttk.Checkbutton(card, text="Redact values (keep on)",
                        variable=self.rec_redact).grid(row=2, column=3, sticky="w")
        self.rec_status = ttk.Label(card, text="Attach first. Snapshots go to the "
                                               "'structure' folder next to the exe.",
                                    style="Muted.TLabel", wraplength=900, justify="left")
        self.rec_status.grid(row=3, column=0, columnspan=5, sticky="w", pady=(8, 0))

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
        """Do something slow off the UI thread and come back safely. Read
        every widget value BEFORE calling this; see the module docstring."""
        if self.session is None:
            return

        def worker() -> None:
            try:
                result = work()
            except Exception as exc:  # noqa: BLE001 - reported in the log pane
                message = f"{type(exc).__name__}: {exc}"
                self._post(lambda: self.log(message, "bad"))
                if "ControlNotFound" in type(exc).__name__ or "no column" in str(exc):
                    self._post(lambda: self.log(
                        "The grid was not found or has different columns. Take a "
                        "RECORD STRUCTURE snapshot with the circuits grid on screen "
                        "and send the structure folder — the snapshot now records "
                        "deep enough to reach it.", "warn"))
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
        self._recorder = None
        self._dot(colour)
        self.status.configure(text=label)
        self.log(f"Attached: {label}", "ok")
        self.circuits = None
        self.planned = []
        self._show_circuits()
        self._show_plan()

    def on_demo(self) -> None:
        from defauto.fake import FakeBackend

        def attach(_handle, out_dir):
            return self._demo_session(out_dir)

        self.log("Demo mode: the picker over an invented desktop.", "warn")
        self._pick_window(FakeBackend.list_windows(), attach)

    def on_demo_direct(self) -> None:
        """Attach to the demo without the picker — what --demo and the
        headless drive use."""
        self._attached(self._demo_session(self.out_dir),
                       "Demo mode — scripted DEF Editor, no application", WARN)

    def _demo_session(self, out_dir):
        """The demo, already on a harness's Circuits page — which is where the
        engineer has navigated DEF Editor to by hand before using this."""
        session = application.demo(out_dir=out_dir)
        session.composite.choose_programme("2031ZR", "2031", "V1_A")
        session.composite.search()
        session.composite.choose_composite(session.composite.composites()[0])
        session.composite.choose_harness(session.composite.harnesses()[0])
        session.circuits.open()
        return session

    def on_connect(self) -> None:
        self.log("Listing the desktop's windows…")
        try:
            found = application.windows()
        except ImportError:
            self.log("pywinauto is not installed — that is the Windows-only path. "
                     "pip install -r requirements.txt", "bad")
            self.log("Demo mode shows the same picker over an invented desktop.", "warn")
            return
        except Exception as exc:  # noqa: BLE001 - shown, not raised
            self.log(f"Could not list windows: {exc}", "bad")
            return
        self._pick_window(found, application.connect_window)

    def _pick_window(self, found, attach) -> None:
        if not found:
            self.log("No windows with a title were found on this desktop.", "warn")
            return
        likely = [w for w in found if w.likely]
        self.log(f"{len(found)} window(s); {len(likely)} look like DEF Editor.",
                 "ok" if likely else "warn")
        top = tk.Toplevel(self)
        top.title("Which window is DEF Editor?")
        top.configure(bg=BG)
        top.geometry("760x420")
        top.transient(self)
        frame = ttk.Frame(top, padding=(16, 14))
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Every window on this desktop. The ones that look like "
                              "DEF Editor are listed first and marked; pick the one "
                              "showing Edit Harness → Circuits.",
                  style="Muted.TLabel", wraplength=700, justify="left").pack(anchor="w")
        box = tk.Listbox(frame, bg="#0d1017", fg=TEXT, selectbackground=ACCENT,
                         selectforeground="#ffffff", relief="flat", font=MONO,
                         activestyle="none", highlightthickness=0)
        box.pack(fill="both", expand=True, pady=(10, 8))
        for w in found:
            box.insert("end", str(w))
            if w.likely:
                box.itemconfig("end", foreground=OK)
        if likely:
            box.selection_set(0)
            box.see(0)

        def refresh_list() -> None:
            top.destroy()
            self.on_connect()

        def choose(_e=None) -> None:
            picked = box.curselection()
            if not picked:
                self.log("Pick a window first.", "warn")
                return
            w = found[picked[0]]
            top.destroy()
            self.log(f"Attaching to {w.title!r} (pid {w.pid})…")
            try:
                session = attach(w.handle, out_dir=self.out_dir)
            except Exception as exc:  # noqa: BLE001 - shown, not raised
                self.log(f"Could not attach: {exc}", "bad")
                return
            self._attached(session, f"Attached: {w.title}", OK)

        box.bind("<Double-Button-1>", choose)
        row = ttk.Frame(frame)
        row.pack(fill="x")
        ttk.Button(row, text="Attach to selected", style="Accent.TButton",
                   command=choose).pack(side="left")
        ttk.Button(row, text="Refresh", command=refresh_list).pack(side="left", padx=8)
        ttk.Button(row, text="Cancel", command=top.destroy).pack(side="right")
        top.grab_set()

    # ------------------------------------------------------- the updater
    def on_choose_file(self) -> None:
        path = filedialog.askopenfilename(
            title="The update list", filetypes=[("Excel", "*.xlsx *.xlsm"), ("All", "*")])
        if not path:
            return
        self.load_updates(Path(path).read_bytes(), Path(path).name)

    def load_updates(self, data: bytes, name: str) -> None:
        """Read the Excel; what the file-picker and the headless drive share."""
        try:
            self.updates = termmatl.read_updates(data, name)
        except Exception as exc:  # noqa: BLE001 - shown, not raised
            self.updates, self.updates_name = [], ""
            self.file_label.configure(text=f"{name}: {exc}", style="Bad.TLabel")
            self.log(f"{name}: {exc}", "bad")
            return
        self.updates_name = name
        self.file_label.configure(text=f"{name} — {len(self.updates)} row(s)",
                                  style="Muted.TLabel")
        self.log(f"Loaded {len(self.updates)} row(s) from {name}", "ok")
        self.planned = []
        self._show_plan()

    def _log_notes(self) -> None:
        """What the backend had to do to find things — worth seeing before Apply."""
        notes = getattr(self.session.backend, "notes", None)
        if not notes:
            return
        for note in notes:
            self.log(f"note: {note}", "warn")
        notes.clear()

    def _progress(self, done: int, total: int) -> None:
        if done == total or done % 100 == 1:
            self._post(lambda: self.log(f"  reading the page: {done} of {total} rows"))

    def on_read_circuits(self) -> None:
        """Step 1: extract the circuits DEF Editor is showing."""
        if self.session is None:
            self.log("Not attached — press Connect or Demo mode first.", "warn")
            return
        self.log("Reading the circuits on DEF Editor's page…")

        def then(circuits) -> None:
            self.circuits = circuits
            self.planned = []
            self._show_circuits()
            self._show_plan()
            self._log_notes()
            self.log(f"{len(circuits)} circuit row(s) on this page.",
                     "ok" if len(circuits) else "warn")
            if not len(circuits):
                self.log("The grid read empty. Is DEF Editor on Edit Harness → "
                         "Circuits, with the circuits listed? If it is, take a RECORD "
                         "STRUCTURE snapshot and send the structure folder.", "warn")

        self._run(lambda: termmatl.read_circuits(self.session.backend, self._progress),
                  then)

    def on_preview(self) -> None:
        """Step 3: match the Excel to the circuits read in step 1 (reading
        them now if step 1 was skipped)."""
        if self.session is None:
            self.log("Not attached — press Connect or Demo mode first.", "warn")
            return
        if not self.updates:
            self.log("Choose the Excel first.", "warn")
            return
        updates = list(self.updates)          # read on the UI thread
        circuits = self.circuits
        self.log(f"Previewing {len(updates)} row(s) against "
                 + (f"the {len(circuits)} circuit(s) read from the page…" if circuits
                    else "the page (reading it first)…"))

        def work():
            found = circuits or termmatl.read_circuits(self.session.backend,
                                                       self._progress)
            return found, termmatl.plan(self.session.backend, updates, circuits=found)

        def then(result) -> None:
            self.circuits, self.planned = result
            self._show_circuits()
            self._show_plan()
            self._log_notes()
            n = termmatl.summary(self.planned)
            shown = len(termmatl.on_page(self.planned))
            self.log(f"Preview: {shown} of {len(self.planned)} list row(s) are on this "
                     f"page — {n[termmatl.CHANGE]} to change · {n[termmatl.ALREADY]} "
                     f"already · {n[termmatl.NO_VALUE]} empty · {n[termmatl.UNKNOWN]} "
                     "unknown", "ok" if n[termmatl.CHANGE] else "warn")
            if n[termmatl.NOT_FOUND]:
                self.log(f"{n[termmatl.NOT_FOUND]} list row(s) are not on this page — "
                         "left out of the preview, listed in the CSV with what the "
                         "page has instead.", "warn")
            if n[termmatl.NOT_FOUND] == len(self.planned) and len(self.circuits):
                first = self.circuits.rows()[0]
                self.log(f"None of the list is on this page. The page's first row "
                         f"reads Connector No {first.cnum!r}, Circuit {first.circuit!r} — "
                         "compare that with the Excel's CNUM and Circuit Name.", "warn")

        self._run(work, then)

    def on_apply(self) -> None:
        changes = [p for p in self.planned if p.will_change]
        if not changes:
            self.log("Nothing to apply — preview first, or every row is settled.", "warn")
            return
        planned = list(self.planned)
        self.apply_button.state(["disabled"])
        self.log(f"Applying {len(changes)} change(s)…")

        def on_row(p) -> None:
            self._post(lambda p=p: (self._show_circuits(), self._show_plan(),
                                    self.log(f"  {p.status.upper():8s} row {p.update.line}: "
                                             f"{p.update.cnum} {p.update.circuit} → "
                                             f"{p.target}  {p.detail}",
                                             "ok" if p.status == termmatl.APPLIED else "bad")))

        def then(result) -> None:
            n = termmatl.summary(result)
            self.log(f"Done: {n[termmatl.APPLIED]} applied, {n[termmatl.FAILED]} failed.",
                     "bad" if n[termmatl.FAILED] else "ok")
            self._show_circuits()
            self._show_plan()

        circuits = self.circuits
        self._run(lambda: termmatl.apply(self.session.backend, planned, on_row,
                                         circuits=circuits), then)

    def _show_circuits(self) -> None:
        """The page as read, with what the list says about each row."""
        tree = self.circuits_tree
        tree.delete(*tree.get_children())
        says: dict = {}
        for p in self.planned:
            for r in p.rows:
                says[r] = (f"{p.target or p.update.terminal or '(empty)'} — "
                           f"{termmatl.STATUS_LABEL.get(p.status, p.status)}"
                           f" (Excel row {p.update.line})", STATUS_TAG.get(p.status, "quiet"))
        rows = self.circuits.rows() if self.circuits else []
        for c in rows:
            text, tag = says.get(c.row, ("", "quiet"))
            tree.insert("", "end", values=[c.row + 1, c.cnum, c.circuit, c.terminal, text],
                        tags=(tag if text else "",))
        self.circuits_head.configure(
            text=f"CIRCUITS ON THIS PAGE — {len(rows)} row(s) read from DEF Editor"
            if self.circuits else "CIRCUITS ON THIS PAGE — press Read circuits")

    def _show_plan(self) -> None:
        self.tree.delete(*self.tree.get_children())
        shown = termmatl.on_page(self.planned)
        for p in shown:
            row = p.as_row()
            self.tree.insert("", "end", values=[row[c] for c in self.columns],
                             tags=(STATUS_TAG.get(p.status, "quiet"),))
        self.preview_head.configure(
            text=f"PREVIEW — {len(shown)} of {len(self.planned)} row(s) of the list are "
                 "on this page" if self.planned
            else "PREVIEW — rows of the list that are on this page")
        if self.planned:
            n = termmatl.summary(self.planned)
            self.summary.configure(
                text=f"PREVIEW — {len(shown)} of {len(self.planned)} list row(s) on this "
                     f"page: {n[termmatl.CHANGE]} will change · {n[termmatl.APPLIED]} "
                     f"applied · {n[termmatl.FAILED]} failed · "
                     f"{n[termmatl.ALREADY] + n[termmatl.NO_VALUE]} untouched · "
                     f"{n[termmatl.UNKNOWN]} unknown value · "
                     f"{n[termmatl.NOT_FOUND]} not on this page")
            changes = n[termmatl.CHANGE]
            self.apply_button.configure(text=f"4  Apply {changes} change(s)" if changes
                                        else "4  Apply")
            self.apply_button.state(["!disabled"] if changes else ["disabled"])
        else:
            self.summary.configure(text="PREVIEW")
            self.apply_button.configure(text="4  Apply")
            self.apply_button.state(["disabled"])

    def on_export(self) -> None:
        if not self.planned:
            self.log("Nothing to export — preview first.", "warn")
            return
        self.out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.out_dir / f"TermMatl_{stamp}.csv"
        path.write_text(termmatl.results_csv(self.planned), encoding="utf-8")
        self.log(f"Wrote {path}", "ok")

    # ---------------------------------------------------------- recorder
    def _get_recorder(self):
        if self.session is None:
            self.log("Not attached — press Connect or Demo mode first.", "warn")
            return None
        redact = bool(self.rec_redact.get())
        if self._recorder is None or self._recorder.redact != redact:
            self._recorder = self.session.recorder(self.out_dir.parent / "structure",
                                                   redact=redact)
        return self._recorder

    def on_snapshot(self) -> None:
        rec = self._get_recorder()
        if rec is None:
            return
        label = self.rec_label.get().strip() or "snapshot"
        try:
            path = rec.snapshot(label)
        except Exception as exc:  # noqa: BLE001 - shown, not raised
            self.log(f"Snapshot failed: {exc}", "bad")
            return
        self.log(f"Saved structure → {path.name}" + ("" if rec.redact else "  (UNREDACTED)"),
                 "ok")
        self.rec_status.configure(text=f"{len(rec.taken)} snapshot(s) in {rec.out_dir}")

    def on_auto_toggle(self) -> None:
        if self.rec_auto.get():
            if self._get_recorder() is None:
                self.rec_auto.set(False)
                return
            self.log("Auto-snapshot on: navigate DEF Editor; each change is recorded.", "ok")
            self._auto_tick()
        else:
            if self._auto_job is not None:
                self.after_cancel(self._auto_job)
                self._auto_job = None
            self.log("Auto-snapshot off.")

    def _auto_tick(self) -> None:
        if not self.rec_auto.get():
            return
        rec = self._recorder
        label = self.rec_label.get().strip() or "auto"

        def then(path) -> None:
            if path is not None:
                self.log(f"Change seen → {path.name}", "ok")
                self.rec_status.configure(text=f"{len(rec.taken)} snapshot(s) in {rec.out_dir}")

        self._run(lambda: rec.tick(label), then)
        self._auto_job = self.after(2000, self._auto_tick)


def main() -> None:
    Workbench().mainloop()


if __name__ == "__main__":
    main()
