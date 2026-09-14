"""The Terminal Material updater: attach, load the Excel, preview, apply.

The engineer navigates DEF Editor by hand to Edit Harness → Circuits. This
window then takes an Excel list — CNUM, Circuit Name, Terminal — and sets
each matching row's Term Matl. It is the one thing in the kit that writes
into DEF Editor, and the window is shaped by that:

* **Preview before apply.** Every Excel row is matched and shown with what
  would happen — change (with the current value), already, not found, no
  value, unknown value — and nothing is touched. Apply is enabled only once
  a preview exists, and applies exactly what the preview said.
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
        self.planned: List[termmatl.Planned] = []
        self.out_dir = Path.cwd() / "exports"
        self._queue: "queue.Queue[Callable[[], None]]" = queue.Queue()
        self._recorder = None
        self._auto_job = None

        self._style()
        self._build()
        self.after(50, self._drain)
        self.log("Ready. In DEF Editor, open Edit Harness → Circuits by hand, then "
                 "Connect here. Demo mode runs the same steps without it.")

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
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        ttk.Button(card, text="Choose Excel…", command=self.on_choose_file) \
            .grid(row=1, column=0, sticky="w")
        self.file_label = ttk.Label(card, text="no file — columns: CNUM, Circuit Name, "
                                               "Terminal (Silver / Gold / Tin / empty)",
                                    style="Muted.TLabel")
        self.file_label.grid(row=1, column=1, sticky="w", padx=(12, 0))
        self.preview_button = ttk.Button(card, text="Preview", command=self.on_preview)
        self.preview_button.grid(row=1, column=2, sticky="w", padx=(16, 0))
        self.apply_button = ttk.Button(card, text="Apply", style="Accent.TButton",
                                       command=self.on_apply)
        self.apply_button.grid(row=1, column=3, sticky="w", padx=(8, 0))
        self.apply_button.state(["disabled"])
        ttk.Label(card, text="Preview matches every row of the list to the circuits "
                             "grid — CNUM to Connector No, Circuit Name to Circuit — and "
                             "touches nothing. Apply sets exactly the rows the preview "
                             "marked 'Will change' and reads each one back.",
                  style="Muted.TLabel", wraplength=960, justify="left").grid(
            row=2, column=0, columnspan=4, sticky="w", pady=(10, 0))

    def _build_preview(self, panes) -> None:
        frame = ttk.Frame(panes, padding=(16, 12))
        panes.add(frame, weight=3)
        head = ttk.Frame(frame)
        head.pack(fill="x")
        self.summary = ttk.Label(head, text="PREVIEW", style="Head.TLabel")
        self.summary.pack(side="left")
        ttk.Button(head, text="Export results CSV",
                   command=self.on_export).pack(side="right")
        holder = ttk.Frame(frame)
        holder.pack(fill="both", expand=True, pady=(10, 0))
        self.columns = ["Excel row", "CNUM", "Circuit", "Terminal", "Current",
                        "Set to", "Rows", "Status", "Detail"]
        self.tree = ttk.Treeview(holder, show="headings", selectmode="browse",
                                 columns=self.columns)
        widths = {"Excel row": 80, "CNUM": 100, "Circuit": 110, "Terminal": 100,
                  "Current": 120, "Set to": 100, "Rows": 60, "Status": 190,
                  "Detail": 320}
        for name in self.columns:
            self.tree.heading(name, text=name)
            self.tree.column(name, width=widths[name], anchor="w",
                             stretch=(name == "Detail"))
        vsb = ttk.Scrollbar(holder, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        self.tree.tag_configure("change", foreground=ACCENT)
        self.tree.tag_configure("ok", foreground=OK)
        self.tree.tag_configure("quiet", foreground=MUTED)
        self.tree.tag_configure("bad", foreground=BAD)

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
        self.planned = []
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

    def on_preview(self) -> None:
        if self.session is None:
            self.log("Not attached — press Connect or Demo mode first.", "warn")
            return
        if not self.updates:
            self.log("Choose the Excel first.", "warn")
            return
        updates = list(self.updates)          # read on the UI thread
        self.log(f"Previewing {len(updates)} row(s) against the circuits grid…")

        def then(planned) -> None:
            self.planned = planned
            self._show_plan()
            n = termmatl.summary(planned)
            self.log(f"Preview: {n[termmatl.CHANGE]} to change · "
                     f"{n[termmatl.ALREADY]} already · {n[termmatl.NO_VALUE]} empty · "
                     f"{n[termmatl.NOT_FOUND]} not found · {n[termmatl.UNKNOWN]} unknown",
                     "ok" if n[termmatl.CHANGE] else "warn")

        self._run(lambda: termmatl.plan(self.session.backend, updates), then)

    def on_apply(self) -> None:
        changes = [p for p in self.planned if p.will_change]
        if not changes:
            self.log("Nothing to apply — preview first, or every row is settled.", "warn")
            return
        planned = list(self.planned)
        self.apply_button.state(["disabled"])
        self.log(f"Applying {len(changes)} change(s)…")

        def on_row(p) -> None:
            self._post(lambda p=p: (self._show_plan(),
                                    self.log(f"  {p.status.upper():8s} row {p.update.line}: "
                                             f"{p.update.cnum} {p.update.circuit} → "
                                             f"{p.target}  {p.detail}",
                                             "ok" if p.status == termmatl.APPLIED else "bad")))

        def then(result) -> None:
            n = termmatl.summary(result)
            self.log(f"Done: {n[termmatl.APPLIED]} applied, {n[termmatl.FAILED]} failed.",
                     "bad" if n[termmatl.FAILED] else "ok")
            self._show_plan()

        self._run(lambda: termmatl.apply(self.session.backend, planned, on_row), then)

    def _show_plan(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for p in self.planned:
            row = p.as_row()
            self.tree.insert("", "end", values=[row[c] for c in self.columns],
                             tags=(STATUS_TAG.get(p.status, "quiet"),))
        if self.planned:
            n = termmatl.summary(self.planned)
            self.summary.configure(
                text=f"PREVIEW — {len(self.planned)} row(s): {n[termmatl.CHANGE]} will "
                     f"change · {n[termmatl.APPLIED]} applied · {n[termmatl.FAILED]} failed "
                     f"· {n[termmatl.ALREADY] + n[termmatl.NO_VALUE]} untouched · "
                     f"{n[termmatl.NOT_FOUND] + n[termmatl.UNKNOWN]} need a look")
            changes = n[termmatl.CHANGE]
            self.apply_button.configure(text=f"Apply {changes} change(s)" if changes
                                        else "Apply")
            self.apply_button.state(["!disabled"] if changes else ["disabled"])
        else:
            self.summary.configure(text="PREVIEW")
            self.apply_button.configure(text="Apply")
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
