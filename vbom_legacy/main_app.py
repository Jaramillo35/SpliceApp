
# The engine lives in splice.vbom.engine; this file is only the desktop window
# around it. Run standalone from the repo (python vbom_legacy/main_app.py) or
# frozen — the shim below finds the package either way.
import sys as _sys
from pathlib import Path as _Path
_repo = _Path(__file__).resolve().parent.parent
if str(_repo) not in _sys.path:
    _sys.path.insert(0, str(_repo))

import os
import re
import pandas as pd
from splice.vbom.engine import *  # noqa: F401,F403 — the engine, one copy
from splice.vbom import engine as _engine
from splice.vbom.engine import _format_stats_sheets, _parse_drop_files  # noqa: F401 — private, not carried by *

try:
    import tkinter as tk
    from tkinter import Tk, filedialog, messagebox
    from tkinter import ttk
except Exception:  # headless (Streamlit/deploy) has no display/tk
    tk = None
    Tk = None
    filedialog = None
    messagebox = None
    ttk = None
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_TK_DND = True
except Exception:
    DND_FILES = None
    TkinterDnD = None
    HAS_TK_DND = False
def _require_tkinter_runtime():
    """Guard for desktop-only GUI entry points. The Streamlit/web VBOM
    workflow never calls these, so headless environments import cleanly."""
    if tk is None or Tk is None or filedialog is None or messagebox is None or ttk is None:
        raise RuntimeError(
            "Tkinter GUI support is not available in this environment. "
            "The web VBOM workflow does not need the GUI, but the desktop UI entry points do."
        )
def pick_file(title="Select VIN/spec file"):
    root = Tk(); root.withdraw(); root.attributes('-topmost', True)
    filetypes = [("Excel files", "*.xlsx *.xls *.xlsm"), ("CSV files", "*.csv"), ("All files", "*.*")]
    path = filedialog.askopenfilename(title=title, filetypes=filetypes)
    root.destroy()
    return path
def pick_multiple_files(title="Select one or more Harness Complexity files"):
    root = Tk(); root.withdraw(); root.attributes('-topmost', True)
    filetypes = [("Excel files", "*.xlsx *.xls *.xlsm"), ("All files", "*.*")]
    paths = filedialog.askopenfilenames(title=title, filetypes=filetypes)
    root.destroy()
    return list(paths)
class RunSetupDialog:
    """Startup window for MY/Program and input file selection."""

    BRAND_NAVY = "#11314f"
    BRAND_ORANGE = "#d9851f"
    BRAND_WHITE = "#ffffff"
    BRAND_MIST = "#eef3f8"
    BRAND_TEXT = "#173552"

    def __init__(self):
        self.result = None
        self.dnd_ready = False
        if HAS_TK_DND and TkinterDnD is not None:
            try:
                self.root = TkinterDnD.Tk()
                self.dnd_ready = True
            except Exception:
                # Continue without drag-and-drop if tkdnd runtime assets are unavailable.
                self.root = Tk()
        else:
            self.root = Tk()
        self.root.title("VBOM Generator")
        self.root.geometry("1100x920")
        self.root.minsize(1000, 840)
        self.root.configure(bg=self.BRAND_NAVY)
        self.root.protocol("WM_DELETE_WINDOW", self._on_cancel)

        self.my_var = tk.StringVar()
        self.program_var = tk.StringVar()
        self.doall_var = tk.StringVar()
        self.buildspec_var = tk.StringVar()
        self.doall_confirmed = False
        self.buildspec_confirmed = False
        self.active_spec_source = None
        self.harness_confirmed = False
        self.harness_files = []
        self.logo_img = None
        self.start_btn_top = None
        self.last_selected_folder = os.getcwd()

        self._build_ui()
        self.root.mainloop()

    def _build_ui(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("Card.TLabelframe", background=self.BRAND_WHITE)
        style.configure("Card.TLabelframe.Label", background=self.BRAND_WHITE, foreground=self.BRAND_TEXT, font=("Segoe UI", 13, "bold"))
        style.configure("Card.TFrame", background=self.BRAND_WHITE)
        style.configure("Brand.TButton", font=("Segoe UI", 10, "bold"), padding=8)

        outer = tk.Frame(self.root, bg=self.BRAND_NAVY, padx=16, pady=16)
        outer.pack(fill="both", expand=True)

        hero = tk.Frame(outer, bg=self.BRAND_NAVY)
        hero.pack(fill="x", pady=(0, 14))
        hero_top = tk.Frame(hero, bg=self.BRAND_NAVY)
        hero_top.pack(fill="x")
        self._render_logo(hero_top)
        self.start_btn_top = tk.Button(
            hero_top,
            text="Start Analysis",
            command=self._on_start,
            bg=self.BRAND_ORANGE,
            fg="#ffffff",
            activebackground="#bf7417",
            activeforeground="#ffffff",
            relief="flat",
            padx=14,
            pady=6,
            state="disabled"
        )
        self.start_btn_top.pack(side="right", anchor="ne")
        tk.Label(
            hero,
            text="VBOM TOOL",
            bg=self.BRAND_NAVY,
            fg=self.BRAND_WHITE,
            font=("Segoe UI", 22, "bold")
        ).pack(anchor="w", pady=(8, 2))
        tk.Label(
            hero,
            text="Enter MY/Program, upload files, confirm each section, then start analysis.",
            bg=self.BRAND_NAVY,
            fg="#d9e4ef",
            font=("Segoe UI", 11)
        ).pack(anchor="w")

        body = tk.Frame(outer, bg=self.BRAND_MIST, bd=0, relief="flat")
        body.pack(fill="both", expand=True)

        form = ttk.LabelFrame(body, text="Program Information", padding=12, style="Card.TLabelframe")
        form.pack(fill="x")
        ttk.Label(form, text="Model Year (MY):").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=4)
        ttk.Entry(form, textvariable=self.my_var, width=18).grid(row=0, column=1, sticky="w", pady=4, padx=(0, 14))
        ttk.Label(form, text="Program:").grid(row=0, column=2, sticky="w", padx=(16, 6), pady=4)
        ttk.Entry(form, textvariable=self.program_var, width=20).grid(row=0, column=3, sticky="w", pady=4)
        ttk.Label(form, text="Example: MY=27, Program=RU", foreground="#4a6178").grid(row=1, column=0, columnspan=4, sticky="w", pady=(2, 0))

        spec_sections = tk.Frame(body, bg=self.BRAND_MIST)
        spec_sections.pack(fill="x", pady=(12, 0))

        doall_box = ttk.LabelFrame(spec_sections, text="DoAll (columns: VIN, Salescodes)", padding=12, style="Card.TLabelframe")
        doall_box.pack(side="left", fill="both", expand=True, padx=(0, 6))
        doall_row = ttk.Frame(doall_box, style="Card.TFrame")
        doall_row.pack(fill="x")
        self.doall_entry = ttk.Entry(doall_row, textvariable=self.doall_var)
        self.doall_entry.pack(side="left", fill="x", expand=True)
        self.doall_browse_btn = ttk.Button(doall_row, text="Browse", command=self._browse_doall)
        self.doall_browse_btn.pack(side="left", padx=(8, 0))
        self.doall_confirm_btn = ttk.Button(doall_row, text="Confirm DoAll", command=self._confirm_doall)
        self.doall_confirm_btn.pack(side="left", padx=(8, 0))

        self.doall_drop = tk.Label(
            doall_box,
            text="Drag and drop DoAll file here (.xlsx/.xls/.xlsm/.csv)",
            bg="#ffffff", fg=self.BRAND_TEXT, relief="ridge", bd=1, padx=10, pady=16
        )
        self.doall_drop.pack(fill="x", pady=(8, 0))
        self.doall_status_lbl = tk.Label(doall_box, text="Pending", fg="#a65000", bg=self.BRAND_WHITE, anchor="w")
        self.doall_status_lbl.pack(fill="x", pady=(6, 0))

        buildspec_box = ttk.LabelFrame(spec_sections, text="BuildSpec File", padding=12, style="Card.TLabelframe")
        buildspec_box.pack(side="left", fill="both", expand=True, padx=(6, 0))
        buildspec_row = ttk.Frame(buildspec_box, style="Card.TFrame")
        buildspec_row.pack(fill="x")
        self.buildspec_entry = ttk.Entry(buildspec_row, textvariable=self.buildspec_var)
        self.buildspec_entry.pack(side="left", fill="x", expand=True)
        self.buildspec_browse_btn = ttk.Button(buildspec_row, text="Browse", command=self._browse_buildspec)
        self.buildspec_browse_btn.pack(side="left", padx=(8, 0))
        self.buildspec_confirm_btn = ttk.Button(buildspec_row, text="Confirm BuildSpec", command=self._confirm_buildspec)
        self.buildspec_confirm_btn.pack(side="left", padx=(8, 0))

        self.buildspec_drop = tk.Label(
            buildspec_box,
            text="Drag and drop BuildSpec file here (.xlsx/.xls/.xlsm)",
            bg="#ffffff", fg=self.BRAND_TEXT, relief="ridge", bd=1, padx=10, pady=16
        )
        self.buildspec_drop.pack(fill="x", pady=(8, 0))
        self.buildspec_status_lbl = tk.Label(buildspec_box, text="Pending", fg="#a65000", bg=self.BRAND_WHITE, anchor="w")
        self.buildspec_status_lbl.pack(fill="x", pady=(6, 0))

        harness_box = ttk.LabelFrame(body, text="Harness Complexity Files (multiple)", padding=12, style="Card.TLabelframe")
        harness_box.pack(fill="both", expand=True, pady=(12, 0))

        bar = ttk.Frame(harness_box, style="Card.TFrame")
        bar.pack(fill="x")
        ttk.Button(bar, text="Add Files", command=self._browse_harness).pack(side="left")
        ttk.Button(bar, text="Remove Selected", command=self._remove_selected_harness).pack(side="left", padx=6)
        ttk.Button(bar, text="Clear", command=self._clear_harness).pack(side="left")
        ttk.Button(bar, text="Confirm Harness Files", command=self._confirm_harness).pack(side="left", padx=8)
        self.harness_count_lbl = ttk.Label(bar, text="0 file(s)")
        self.harness_count_lbl.pack(side="right")

        list_frame = ttk.Frame(harness_box, style="Card.TFrame")
        list_frame.pack(fill="both", expand=True, pady=(8, 0))
        self.harness_list = tk.Listbox(
            list_frame,
            selectmode="extended",
            bg="#ffffff",
            fg=self.BRAND_TEXT,
            highlightbackground="#c7d4e2",
            relief="flat"
        )
        ysb = ttk.Scrollbar(list_frame, orient="vertical", command=self.harness_list.yview)
        self.harness_list.configure(yscrollcommand=ysb.set)
        self.harness_list.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")

        self.harness_drop = tk.Label(
            harness_box,
            text="Drag and drop one or many Harness Complexity files here (.xlsx/.xls/.xlsm)",
            bg="#ffffff", fg=self.BRAND_TEXT, relief="ridge", bd=1, padx=10, pady=14
        )
        self.harness_drop.pack(fill="x", pady=(8, 0))
        self.harness_status_lbl = tk.Label(harness_box, text="Pending", fg="#a65000", bg=self.BRAND_WHITE, anchor="w")
        self.harness_status_lbl.pack(fill="x", pady=(6, 0))

        if self.dnd_ready and DND_FILES is not None:
            self._enable_dnd()
        else:
            self.doall_drop.configure(text="Drag-and-drop unavailable (install tkinterdnd2). Use Browse.", fg="#8a4f00")
            self.buildspec_drop.configure(text="Drag-and-drop unavailable (install tkinterdnd2). Use Browse.", fg="#8a4f00")
            self.harness_drop.configure(text="Drag-and-drop unavailable (install tkinterdnd2). Use Add Files.", fg="#8a4f00")

        actions = tk.Frame(outer, bg=self.BRAND_NAVY)
        actions.pack(fill="x", pady=(12, 0))
        self.readiness_lbl = tk.Label(
            actions,
            text="Waiting for confirmations",
            bg=self.BRAND_NAVY,
            fg="#d9e4ef",
            font=("Segoe UI", 10)
        )
        self.readiness_lbl.pack(side="left")
        tk.Button(
            actions,
            text="Cancel",
            command=self._on_cancel,
            bg="#8c3b2a",
            fg="#ffffff",
            activebackground="#762d1e",
            activeforeground="#ffffff",
            relief="flat",
            padx=14,
            pady=8
        ).pack(side="right")
        self.start_btn = tk.Button(
            actions,
            text="Start Analysis",
            command=self._on_start,
            bg=self.BRAND_ORANGE,
            fg="#ffffff",
            activebackground="#bf7417",
            activeforeground="#ffffff",
            relief="flat",
            padx=18,
            pady=8,
            state="disabled"
        )
        self.start_btn.pack(side="right", padx=8)

        self.my_var.trace_add("write", lambda *_: self._refresh_start_state())
        self.program_var.trace_add("write", lambda *_: self._refresh_start_state())
        self.doall_var.trace_add("write", lambda *_: self._on_doall_changed())
        self.buildspec_var.trace_add("write", lambda *_: self._on_buildspec_changed())
        self._refresh_spec_source_state()
        self._refresh_start_state()

    def _render_logo(self, parent):
        logo_path = os.path.join(os.path.dirname(__file__), "logo.png")
        if not os.path.exists(logo_path):
            return
        try:
            # Works on Tk versions that support SVG directly.
            raw = tk.PhotoImage(file=logo_path)
            self.logo_img = raw.subsample(2, 2)
            tk.Label(parent, image=self.logo_img, bg=self.BRAND_NAVY).pack(anchor="w")
            return
        except Exception:
            pass

        try:
            import io
            from cairosvg import svg2png
            from PIL import Image, ImageTk

            png_bytes = svg2png(url=logo_path, output_width=130)
            pil = Image.open(io.BytesIO(png_bytes))
            self.logo_img = ImageTk.PhotoImage(pil)
            tk.Label(parent, image=self.logo_img, bg=self.BRAND_NAVY).pack(anchor="w")
        except Exception:
            tk.Label(parent, text="VERSIGENT", bg=self.BRAND_NAVY, fg=self.BRAND_WHITE, font=("Segoe UI", 18, "bold")).pack(anchor="w")

    def _enable_dnd(self):
        self.doall_drop.drop_target_register(DND_FILES)
        self.doall_drop.dnd_bind('<<Drop>>', self._on_drop_doall)
        self.doall_drop.dnd_bind('<<DragEnter>>', lambda _e: self.doall_drop.configure(bg="#fff3e1"))
        self.doall_drop.dnd_bind('<<DragLeave>>', lambda _e: self.doall_drop.configure(bg="#ffffff"))
        self.buildspec_drop.drop_target_register(DND_FILES)
        self.buildspec_drop.dnd_bind('<<Drop>>', self._on_drop_buildspec)
        self.buildspec_drop.dnd_bind('<<DragEnter>>', lambda _e: self.buildspec_drop.configure(bg="#fff3e1"))
        self.buildspec_drop.dnd_bind('<<DragLeave>>', lambda _e: self.buildspec_drop.configure(bg="#ffffff"))
        self.harness_drop.drop_target_register(DND_FILES)
        self.harness_drop.dnd_bind('<<Drop>>', self._on_drop_harness)
        self.harness_drop.dnd_bind('<<DragEnter>>', lambda _e: self.harness_drop.configure(bg="#fff3e1"))
        self.harness_drop.dnd_bind('<<DragLeave>>', lambda _e: self.harness_drop.configure(bg="#ffffff"))

    def _browse_doall(self):
        path = filedialog.askopenfilename(
            title="Select DoAll file",
            filetypes=[("DoAll", "*.xlsx *.xls *.xlsm *.csv"), ("All files", "*.*")],
        )
        if path:
            self._select_input_source("doall", path)
            self.last_selected_folder = os.path.dirname(path)
            self.doall_drop.configure(bg="#ffffff")

    def _browse_buildspec(self):
        path = filedialog.askopenfilename(
            title="Select BuildSpec file",
            filetypes=[("BuildSpec", "*.xlsx *.xls *.xlsm"), ("All files", "*.*")],
        )
        if path:
            self._select_input_source("buildspec", path)
            self.last_selected_folder = os.path.dirname(path)
            self.buildspec_drop.configure(bg="#ffffff")

    def _browse_harness(self):
        paths = filedialog.askopenfilenames(
            title="Select one or more Harness Complexity files",
            filetypes=[("Excel files", "*.xlsx *.xls *.xlsm"), ("All files", "*.*")],
        )
        if paths:
            self.last_selected_folder = os.path.dirname(paths[-1])
        self._add_harness_files(list(paths))

    def _on_drop_doall(self, event):
        files = _parse_drop_files(event.data)
        if not files:
            return
        if self.active_spec_source == "buildspec":
            self.doall_status_lbl.configure(text="Unavailable while BuildSpec is selected", fg="#8a4f00")
            return
        allowed = {".xlsx", ".xls", ".xlsm", ".csv"}
        chosen = None
        for p in files:
            if os.path.splitext(p)[1].lower() in allowed:
                chosen = p
                break
        if not chosen:
            self.doall_status_lbl.configure(text="No valid DoAll file dropped", fg="#b52a2a")
            return
        self._select_input_source("doall", chosen)
        self.last_selected_folder = os.path.dirname(chosen)
        self.doall_drop.configure(bg="#ffffff")

    def _on_drop_buildspec(self, event):
        files = _parse_drop_files(event.data)
        if not files:
            return
        if self.active_spec_source == "doall":
            self.buildspec_status_lbl.configure(text="Unavailable while DoAll is selected", fg="#8a4f00")
            return
        allowed = {".xlsx", ".xls", ".xlsm"}
        chosen = None
        for p in files:
            if os.path.splitext(p)[1].lower() in allowed:
                chosen = p
                break
        if not chosen:
            self.buildspec_status_lbl.configure(text="No valid BuildSpec file dropped", fg="#b52a2a")
            return
        self._select_input_source("buildspec", chosen)
        self.last_selected_folder = os.path.dirname(chosen)
        self.buildspec_drop.configure(bg="#ffffff")

    def _on_drop_harness(self, event):
        files = _parse_drop_files(event.data)
        self.harness_drop.configure(bg="#ffffff")
        self._add_harness_files(files)

    def _add_harness_files(self, files):
        allowed = {".xlsx", ".xls", ".xlsm"}
        added = False
        invalid = 0
        last_added_folder = None
        for p in files:
            ext = os.path.splitext(p)[1].lower()
            if ext not in allowed:
                invalid += 1
                continue
            norm = os.path.normpath(p)
            if norm not in self.harness_files:
                self.harness_files.append(norm)
                last_added_folder = os.path.dirname(norm)
                added = True
        if added:
            if last_added_folder:
                self.last_selected_folder = last_added_folder
            self.harness_confirmed = False
            self._refresh_harness_list()
        if invalid:
            self.harness_status_lbl.configure(text=f"Ignored {invalid} non-Excel file(s)", fg="#b56f00")

    def _refresh_harness_list(self):
        self.harness_list.delete(0, tk.END)
        for p in self.harness_files:
            self.harness_list.insert(tk.END, p)
        self.harness_count_lbl.configure(text=f"{len(self.harness_files)} file(s)")
        if self.harness_files:
            self.harness_status_lbl.configure(text=f"{len(self.harness_files)} file(s) loaded. Click Confirm Harness Files.", fg="#4a6178")
        else:
            self.harness_status_lbl.configure(text="Pending", fg="#a65000")
        self._refresh_start_state()

    def _remove_selected_harness(self):
        sel = list(self.harness_list.curselection())
        if not sel:
            return
        for idx in reversed(sel):
            if 0 <= idx < len(self.harness_files):
                self.harness_files.pop(idx)
        self.harness_confirmed = False
        self._refresh_harness_list()

    def _clear_harness(self):
        self.harness_files = []
        self.harness_confirmed = False
        self._refresh_harness_list()

    def _on_cancel(self):
        self.result = None
        self.root.destroy()

    def _select_input_source(self, source: str, path: str):
        if source == "doall":
            self.doall_var.set(path)
            self.doall_confirmed = False
            self.doall_status_lbl.configure(text="File selected. Click Confirm DoAll.", fg="#4a6178")
            self.buildspec_var.set("")
            self.buildspec_confirmed = False
            self.buildspec_status_lbl.configure(text="Unavailable while DoAll is selected", fg="#8a4f00")
            self.active_spec_source = "doall"
        else:
            self.buildspec_var.set(path)
            self.buildspec_confirmed = False
            self.buildspec_status_lbl.configure(text="File selected. Click Confirm BuildSpec.", fg="#4a6178")
            self.doall_var.set("")
            self.doall_confirmed = False
            self.doall_status_lbl.configure(text="Unavailable while BuildSpec is selected", fg="#8a4f00")
            self.active_spec_source = "buildspec"
        self._refresh_spec_source_state()
        self._refresh_start_state()

    def _refresh_spec_source_state(self):
        doall_available = self.active_spec_source in (None, "doall")
        buildspec_available = self.active_spec_source in (None, "buildspec")

        self.doall_entry.configure(state=("normal" if doall_available else "disabled"))
        self.doall_browse_btn.configure(state=("normal" if doall_available else "disabled"))
        self.doall_confirm_btn.configure(state=("normal" if doall_available else "disabled"))

        self.buildspec_entry.configure(state=("normal" if buildspec_available else "disabled"))
        self.buildspec_browse_btn.configure(state=("normal" if buildspec_available else "disabled"))
        self.buildspec_confirm_btn.configure(state=("normal" if buildspec_available else "disabled"))

        if doall_available and not self.doall_var.get().strip() and self.active_spec_source is None:
            self.doall_status_lbl.configure(text="Pending", fg="#a65000")
        if buildspec_available and not self.buildspec_var.get().strip() and self.active_spec_source is None:
            self.buildspec_status_lbl.configure(text="Pending", fg="#a65000")

    def _on_doall_changed(self):
        if self.doall_var.get().strip():
            if self.active_spec_source != "doall":
                self.active_spec_source = "doall"
                self.buildspec_var.set("")
                self.buildspec_confirmed = False
                self.buildspec_status_lbl.configure(text="Unavailable while DoAll is selected", fg="#8a4f00")
            self.doall_confirmed = False
            self.doall_status_lbl.configure(text="File selected. Click Confirm DoAll.", fg="#4a6178")
        elif self.active_spec_source == "doall":
            self.active_spec_source = None
            self.doall_confirmed = False
            self.doall_status_lbl.configure(text="Pending", fg="#a65000")
        self._refresh_spec_source_state()
        self._refresh_start_state()

    def _on_buildspec_changed(self):
        if self.buildspec_var.get().strip():
            if self.active_spec_source != "buildspec":
                self.active_spec_source = "buildspec"
                self.doall_var.set("")
                self.doall_confirmed = False
                self.doall_status_lbl.configure(text="Unavailable while BuildSpec is selected", fg="#8a4f00")
            self.buildspec_confirmed = False
            self.buildspec_status_lbl.configure(text="File selected. Click Confirm BuildSpec.", fg="#4a6178")
        elif self.active_spec_source == "buildspec":
            self.active_spec_source = None
            self.buildspec_confirmed = False
            self.buildspec_status_lbl.configure(text="Pending", fg="#a65000")
        self._refresh_spec_source_state()
        self._refresh_start_state()

    def _confirm_doall(self):
        path = self.doall_var.get().strip()
        if not path:
            messagebox.showerror("Missing file", "Please select a DoAll file first.", parent=self.root)
            return
        if not os.path.isfile(path):
            messagebox.showerror("Invalid file", "DoAll file does not exist.", parent=self.root)
            return
        self.doall_confirmed = True
        self.active_spec_source = "doall"
        self.doall_status_lbl.configure(text="DoAll confirmed", fg="#1f7a1f")
        self.buildspec_status_lbl.configure(text="Unavailable while DoAll is selected", fg="#8a4f00")
        self._refresh_spec_source_state()
        self._refresh_start_state()

    def _confirm_buildspec(self):
        path = self.buildspec_var.get().strip()
        if not path:
            messagebox.showerror("Missing file", "Please select a BuildSpec file first.", parent=self.root)
            return
        if not os.path.isfile(path):
            messagebox.showerror("Invalid file", "BuildSpec file does not exist.", parent=self.root)
            return
        self.buildspec_confirmed = True
        self.active_spec_source = "buildspec"
        self.buildspec_status_lbl.configure(text="BuildSpec confirmed", fg="#1f7a1f")
        self.doall_status_lbl.configure(text="Unavailable while BuildSpec is selected", fg="#8a4f00")
        self._refresh_spec_source_state()
        self._refresh_start_state()

    def _confirm_harness(self):
        if not self.harness_files:
            messagebox.showerror("Missing files", "Please add at least one Harness file first.", parent=self.root)
            return
        missing = [p for p in self.harness_files if not os.path.isfile(p)]
        if missing:
            messagebox.showerror("Invalid files", "Some selected Harness files no longer exist.", parent=self.root)
            return
        self.harness_confirmed = True
        self.harness_status_lbl.configure(text=f"Harness files confirmed ({len(self.harness_files)})", fg="#1f7a1f")
        self._refresh_start_state()

    def _refresh_start_state(self):
        missing = []
        if not self.my_var.get().strip():
            missing.append("Model Year")
        if not self.program_var.get().strip():
            missing.append("Program")
        if self.active_spec_source == "doall":
            if not self.doall_confirmed:
                missing.append("DoAll confirmation")
        elif self.active_spec_source == "buildspec":
            if not self.buildspec_confirmed:
                missing.append("BuildSpec confirmation")
        else:
            missing.append("DoAll or BuildSpec confirmation")
        if not self.harness_confirmed:
            missing.append("Harness Files confirmation")

        ready = len(missing) == 0
        new_state = ("normal" if ready else "disabled")
        self.start_btn.configure(state=new_state)
        if self.start_btn_top is not None:
            self.start_btn_top.configure(state=new_state)
        if ready:
            self.readiness_lbl.configure(text="Ready to run")
        else:
            self.readiness_lbl.configure(text=f"Missing: {', '.join(missing)}")

    def _on_start(self):
        my = self.my_var.get().strip()
        program = self.program_var.get().strip()
        doall_path = self.doall_var.get().strip()
        buildspec_path = self.buildspec_var.get().strip()

        if not my or not program:
            messagebox.showerror("Missing data", "Please enter both Model Year and Program.", parent=self.root)
            return

        input_type = self.active_spec_source
        if input_type == "doall":
            input_path = doall_path
            if not input_path:
                messagebox.showerror("Missing file", "Please select a DoAll file.", parent=self.root)
                return
            if not os.path.isfile(input_path):
                messagebox.showerror("Invalid file", "DoAll file does not exist.", parent=self.root)
                return
            if not self.doall_confirmed:
                messagebox.showerror("Not confirmed", "Please confirm DoAll before starting.", parent=self.root)
                return
        elif input_type == "buildspec":
            input_path = buildspec_path
            if not input_path:
                messagebox.showerror("Missing file", "Please select a BuildSpec file.", parent=self.root)
                return
            if not os.path.isfile(input_path):
                messagebox.showerror("Invalid file", "BuildSpec file does not exist.", parent=self.root)
                return
            if not self.buildspec_confirmed:
                messagebox.showerror("Not confirmed", "Please confirm BuildSpec before starting.", parent=self.root)
                return
        else:
            messagebox.showerror("Missing file", "Please select and confirm either DoAll or BuildSpec.", parent=self.root)
            return

        if not self.harness_files:
            messagebox.showerror("Missing files", "Please add at least one Harness Complexity file.", parent=self.root)
            return
        if not self.harness_confirmed:
            messagebox.showerror("Not confirmed", "Please confirm Harness Files before starting.", parent=self.root)
            return

        self.result = {
            "my": my,
            "program": program,
            "input_type": input_type,
            "input_file": input_path,
            "harness_files": list(self.harness_files),
            "output_dir": self.last_selected_folder or os.path.dirname(input_path),
        }
        self.root.destroy()
class HarnessTieRevisionDialog:
    def __init__(self, parent, ties):
        self.result = None
        self._parent = parent
        self._ties = ties
        self._choices = {}
        self._options_by_key = {}
        self._check_vars_by_key = {}
        self._build_window()

    def _build_window(self):
        win = tk.Toplevel(self._parent)
        self._win = win
        win.title("Harness PN Tie Revision")
        win.geometry("1380x800")
        win.minsize(980, 620)
        win.attributes("-topmost", True)
        win.grab_set()

        # Explicit colors — override macOS dark mode
        BG       = "#F0F2F5"
        BOX_BG   = "#FFFFFF"
        BAR_BG   = "#2C3E50"
        BAR_FG   = "#FFFFFF"
        LABEL_FG = "#1A1A1A"
        SUB_FG   = "#555555"
        SCORE_FG = "#1A6FBF"
        HDR_BG   = "#E8EEF5"
        HDR_FG   = "#1F2D3D"
        ROW_ALT  = "#EBF3FB"
        BOLD_F   = ("Segoe UI", 10, "bold")
        NORM_F   = ("Segoe UI", 9)

        win.configure(bg=BG)

        tk.Label(win,
             text="Review tied top-score cases grouped by Harness Family. Select exactly one Harness PN per VIN.",
                 font=BOLD_F, bg=BG, fg=LABEL_FG,
                 ).pack(fill="x", padx=12, pady=(12, 4))

        outer = tk.Frame(win, bg=BG)
        outer.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        canvas = tk.Canvas(outer, borderwidth=0, highlightthickness=0, bg=BG)
        ysb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=BG)
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win_id, width=e.width))
        canvas.configure(yscrollcommand=ysb.set)
        ysb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        ties_by_family = {}
        for vin, family, cand_df in self._ties:
            ties_by_family.setdefault(family, []).append((vin, cand_df))

        for family_idx, family in enumerate(sorted(ties_by_family.keys()), start=1):
            family_items = ties_by_family[family]
            card = tk.Frame(inner, bg=BOX_BG, relief="solid", bd=1)
            card.pack(fill="x", padx=6, pady=6)

            title_bar = tk.Frame(card, bg=BAR_BG)
            title_bar.pack(fill="x")
            tk.Label(title_bar,
                     text=f"  Family Group {family_idx}:  {family}  |  VIN ties: {len(family_items)}  ",
                     font=BOLD_F, bg=BAR_BG, fg=BAR_FG, anchor="w",
                     ).pack(side="left", padx=4, pady=5)

            content = tk.Frame(card, bg=BOX_BG, padx=10, pady=8)
            content.pack(fill="x")

            for vin_idx, (vin, cand_df) in enumerate(sorted(family_items, key=lambda x: str(x[0])), start=1):
                group_key = (vin, family)
                top_score = cand_df["Score"].max()

                vin_box = tk.Frame(content, bg=BOX_BG, relief="groove", bd=1)
                vin_box.pack(fill="x", pady=(0, 10))

                vin_hdr = tk.Frame(vin_box, bg=HDR_BG)
                vin_hdr.pack(fill="x")
                tk.Label(
                    vin_hdr,
                    text=f" VIN {vin_idx}: {vin}   |   Top score: {top_score}",
                    font=BOLD_F,
                    bg=HDR_BG,
                    fg=HDR_FG,
                    anchor="w",
                ).pack(fill="x", padx=6, pady=4)

                row_hdr = tk.Frame(vin_box, bg=BOX_BG)
                row_hdr.pack(fill="x", padx=6, pady=(6, 2))
                tk.Label(row_hdr, text="Pick", width=5, anchor="w", bg=BOX_BG, fg=LABEL_FG, font=BOLD_F).grid(row=0, column=0, sticky="w")
                tk.Label(row_hdr, text="PN", width=16, anchor="w", bg=BOX_BG, fg=LABEL_FG, font=BOLD_F).grid(row=0, column=1, sticky="w")
                tk.Label(row_hdr, text="Score", width=8, anchor="w", bg=BOX_BG, fg=LABEL_FG, font=BOLD_F).grid(row=0, column=2, sticky="w")
                tk.Label(row_hdr, text="Giveaway", width=20, anchor="w", bg=BOX_BG, fg=LABEL_FG, font=BOLD_F).grid(row=0, column=3, sticky="w")
                tk.Label(row_hdr, text="MissingSalesCodes", width=32, anchor="w", bg=BOX_BG, fg=LABEL_FG, font=BOLD_F).grid(row=0, column=4, sticky="w")
                tk.Label(row_hdr, text="ExtraSalesCodes", width=32, anchor="w", bg=BOX_BG, fg=LABEL_FG, font=BOLD_F).grid(row=0, column=5, sticky="w")

                current_best = cand_df[cand_df["IsBest"] == True]
                default_pn = str(current_best.iloc[0]["PN"]) if not current_best.empty else str(cand_df.iloc[0]["PN"])
                options = [str(x) for x in cand_df["PN"].tolist()]

                choice_var = tk.StringVar(value=default_pn)
                self._choices[group_key] = choice_var
                self._options_by_key[group_key] = options
                self._check_vars_by_key[group_key] = {}

                for row_i, (_, r) in enumerate(cand_df.iterrows()):
                    pn = str(r.get("PN", ""))
                    is_default = pn == default_pn
                    check_var = tk.BooleanVar(value=is_default)
                    self._check_vars_by_key[group_key][pn] = check_var

                    row_bg = BOX_BG if row_i % 2 == 0 else ROW_ALT
                    row = tk.Frame(vin_box, bg=row_bg)
                    row.pack(fill="x", padx=6, pady=1)

                    cb = tk.Checkbutton(
                        row,
                        variable=check_var,
                        bg=row_bg,
                        activebackground=row_bg,
                        command=lambda k=group_key, p=pn: self._on_candidate_toggle(k, p),
                    )
                    cb.grid(row=0, column=0, sticky="w")
                    tk.Label(row, text=pn, width=16, anchor="w", bg=row_bg, fg=LABEL_FG, font=NORM_F).grid(row=0, column=1, sticky="w")
                    tk.Label(row, text=str(r.get("Score", "")), width=8, anchor="w", bg=row_bg, fg=LABEL_FG, font=NORM_F).grid(row=0, column=2, sticky="w")
                    tk.Label(row, text=(r.get("Giveaway") or ""), width=20, anchor="w", bg=row_bg, fg=LABEL_FG, font=NORM_F).grid(row=0, column=3, sticky="w")
                    tk.Label(row, text=(r.get("MissingSalesCodes") or ""), width=32, anchor="w", bg=row_bg, fg=LABEL_FG, font=NORM_F).grid(row=0, column=4, sticky="w")
                    tk.Label(row, text=(r.get("ExtraSalesCodes") or ""), width=32, anchor="w", bg=row_bg, fg=LABEL_FG, font=NORM_F).grid(row=0, column=5, sticky="w")

        bar = tk.Frame(win, bg=BG)
        bar.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(bar, text="Auto Select First Occurrence",
                   command=self._auto_select_first).pack(side="left", padx=4)
        ttk.Button(bar, text="Cancel", command=self._on_cancel).pack(side="right", padx=4)
        ttk.Button(bar, text="Apply Selections", command=self._on_apply).pack(side="right", padx=4)

        win.wait_window()

    def _on_candidate_toggle(self, key, chosen_pn):
        vars_by_pn = self._check_vars_by_key.get(key, {})
        chosen_var = vars_by_pn.get(chosen_pn)
        if chosen_var is None:
            return

        if chosen_var.get():
            for pn, var in vars_by_pn.items():
                if pn != chosen_pn:
                    var.set(False)
            self._choices[key].set(chosen_pn)
            return

        # Enforce one selection minimum: do not allow all unchecked.
        if not any(var.get() for var in vars_by_pn.values()):
            chosen_var.set(True)
            self._choices[key].set(chosen_pn)

    def _auto_select_first(self):
        for key, opts in self._options_by_key.items():
            if not opts:
                continue
            first = opts[0]
            self._choices[key].set(first)
            for pn, var in self._check_vars_by_key.get(key, {}).items():
                var.set(pn == first)

    def _on_cancel(self):
        self.result = None
        self._win.destroy()

    def _on_apply(self):
        self.result = {k: v.get() for k, v in self._choices.items()}
        self._win.destroy()
class SalesCodeReviewDialog:


    _STATUS_BG = {
        "STANDARD": "#C6EFCE",
        "OPTIONAL": "#FFEB9C",
        "UNUSED":    "#FFC7CE",
    }
    _STATUS_FG = {
        "STANDARD": "#276221",
        "OPTIONAL": "#7D6608",
        "UNUSED":    "#9C0006",
    }

    def __init__(self, parent,
                 family_stats_df: "pd.DataFrame",
                 global_code_df:  "pd.DataFrame"):
        self.result = None
        self._family_stats = family_stats_df
        self._parent        = parent

        self._families = sorted(self._family_stats["HarnessFamily"].unique().tolist())
        self._current_family = tk.StringVar(value=self._families[0] if self._families else "")
        self._profile_loaded = False

        # Build family -> status -> sorted codes map.
        self._family_status_codes = {}
        self._family_code_vars = {}
        self._family_reviewed = {}
        for fam in self._families:
            sub = self._family_stats[self._family_stats["HarnessFamily"] == fam]
            std_codes = sorted(sub[sub["Status"] == "STANDARD"]["SalesCode"].unique().tolist())
            opt_codes = sorted(sub[sub["Status"] == "OPTIONAL"]["SalesCode"].unique().tolist())
            self._family_status_codes[fam] = {
                "STANDARD": std_codes,
                "OPTIONAL": opt_codes,
            }
            all_codes = sorted(set(std_codes + opt_codes))
            self._family_code_vars[fam] = {c: tk.BooleanVar(value=True) for c in all_codes}
            self._family_reviewed[fam] = False

        self._status_lbl = None
        self._continue_btn_bottom = None
        self._continue_btn_tab = None
        self._export_btn = None
        self._progress_tree = None
        self._codes_inner = None

        self._build_window()

    # ------------------------------------------------------------------ build
    def _build_window(self):
        win = tk.Toplevel(self._parent)
        self._win = win
        win.title("SalesCode Analysis & Selection")
        win.geometry("1300x820")
        win.minsize(960, 640)
        win.resizable(True, True)
        win.attributes('-topmost', True)
        win.grab_set()

        # style tweaks
        style = ttk.Style(win)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Heading.TLabel", font=("Segoe UI", 10, "bold"))

        nb = ttk.Notebook(win)
        nb.pack(fill="both", expand=True, padx=6, pady=(6, 0))

        t1 = ttk.Frame(nb); nb.add(t1, text="  Per-Family Analysis  ")
        t2 = ttk.Frame(nb); nb.add(t2, text="  Code Selection  ")

        self._build_family_tab(t1)
        self._build_selection_tab(t2)

        # bottom bar
        bar = ttk.Frame(win, relief="groove")
        bar.pack(fill="x", padx=6, pady=6)

        self._status_lbl = ttk.Label(bar, text="", font=("Segoe UI", 9))
        self._status_lbl.pack(side="left", padx=10)
        self._refresh_status_label()

        ttk.Button(bar, text="Cancel",
                   command=win.destroy).pack(side="right", padx=6, pady=3)
        self._continue_btn_bottom = ttk.Button(bar, text="✓  Continue",
                               command=self._on_proceed)
        self._continue_btn_bottom.pack(side="right", padx=2, pady=3)

        self._refresh_selection_readiness()
        win.wait_window()

    # --------------------------------------------------- Per-Family tab
    def _build_family_tab(self, parent):
        top = ttk.Frame(parent)
        top.pack(fill="x", padx=8, pady=6)

        ttk.Label(top, text="Harness Family:").pack(side="left")
        families = ["(All)"] + sorted(self._family_stats["HarnessFamily"].unique())
        self._fam_filter_var = tk.StringVar(value="(All)")
        cb = ttk.Combobox(top, textvariable=self._fam_filter_var,
                          values=families, width=42, state="readonly")
        cb.pack(side="left", padx=6)
        cb.bind("<<ComboboxSelected>>", lambda _e: self._refresh_family_tree())

        ttk.Label(top, text="Status:").pack(side="left", padx=(14, 4))
        self._fam_status_var = tk.StringVar(value="(All)")
        sf = ttk.Combobox(top, textvariable=self._fam_status_var,
                          values=["(All)", "STANDARD", "OPTIONAL", "UNUSED"],
                          width=14, state="readonly")
        sf.pack(side="left")
        sf.bind("<<ComboboxSelected>>", lambda _e: self._refresh_family_tree())

        # legend
        leg = ttk.Frame(parent)
        leg.pack(fill="x", padx=8)
        for status, bg in self._STATUS_BG.items():
            fr = tk.Frame(leg, bg=bg, width=14, height=14)
            fr.pack(side="left", padx=(0, 2))
            ttk.Label(leg, text=status, foreground=self._STATUS_FG[status],
                      font=("Segoe UI", 8, "bold")).pack(side="left", padx=(0, 12))

        cols = ("HarnessFamily", "SalesCode", "PNsWithCode", "TotalPNs", "Coverage_Pct", "Status")
        tree = self._make_tree(parent, cols, {
            "HarnessFamily": 220, "SalesCode": 90, "PNsWithCode": 110,
            "TotalPNs": 90, "Coverage_Pct": 110, "Status": 110,
        })
        self._family_tree = tree
        for s, bg in self._STATUS_BG.items():
            tree.tag_configure(s, background=bg, foreground=self._STATUS_FG[s])
        self._refresh_family_tree()

    def _refresh_family_tree(self):
        tree = self._family_tree
        tree.delete(*tree.get_children())
        df = self._family_stats
        fsel = self._fam_filter_var.get()
        ssel = self._fam_status_var.get()
        if fsel != "(All)":
            df = df[df["HarnessFamily"] == fsel]
        if ssel != "(All)":
            df = df[df["Status"] == ssel]
        for _, row in df.iterrows():
            st = row["Status"]
            tree.insert("", "end", values=(
                row["HarnessFamily"], row["SalesCode"],
                row["PNsWithCode"], row["TotalPNs"],
                f"{row['Coverage_Pct']:.1f}%", st,
            ), tags=(st,))

    # --------------------------------------------------- Code Selection tab
    def _build_selection_tab(self, parent):
        top = ttk.Frame(parent)
        top.pack(fill="x", padx=8, pady=6)

        ttk.Label(top, text="Review each harness family box and mark it reviewed.",
                  font=("Segoe UI", 10, "bold")).pack(side="left")

        right_actions = ttk.Frame(top)
        right_actions.pack(side="right")
        ttk.Button(right_actions, text="Mark All Reviewed", command=self._mark_all_reviewed).pack(side="left", padx=2)
        ttk.Button(right_actions, text="Load Selection Profile", command=self._load_selection_profile).pack(side="left", padx=2)
        self._export_btn = ttk.Button(right_actions, text="Export Selection Profile", command=self._export_selection_profile)
        self._export_btn.pack(side="left", padx=2)
        self._continue_btn_tab = ttk.Button(right_actions, text="Continue", command=self._on_proceed)
        self._continue_btn_tab.pack(side="left", padx=2)

        self._selection_summary_lbl = ttk.Label(parent, text="", font=("Segoe UI", 9))
        self._selection_summary_lbl.pack(fill="x", padx=8)

        outer = ttk.Frame(parent)
        outer.pack(fill="both", expand=True, padx=8, pady=4)

        self._codes_canvas = tk.Canvas(outer, borderwidth=0, highlightthickness=0, bg="#f8f8f8")
        ysb = ttk.Scrollbar(outer, orient="vertical", command=self._codes_canvas.yview)
        self._codes_inner = ttk.Frame(self._codes_canvas)
        self._codes_inner.bind(
            "<Configure>",
            lambda _e: self._codes_canvas.configure(scrollregion=self._codes_canvas.bbox("all"))
        )

        # Keep the inner frame stretched to the full visible canvas width.
        self._codes_window = self._codes_canvas.create_window((0, 0), window=self._codes_inner, anchor="nw")
        self._codes_canvas.bind(
            "<Configure>",
            lambda e: self._codes_canvas.itemconfigure(self._codes_window, width=e.width)
        )
        self._codes_canvas.configure(yscrollcommand=ysb.set)
        ysb.pack(side="right", fill="y")
        self._codes_canvas.pack(side="left", fill="both", expand=True)

        self._render_all_family_boxes()
        self._refresh_selection_readiness()

    def _render_all_family_boxes(self):
        if self._codes_inner is None:
            return
        for w in self._codes_inner.winfo_children():
            w.destroy()

        for fam in self._families:
            reviewed = self._family_reviewed.get(fam, False)
            mark = "✅" if reviewed else "⬜"
            fam_box = tk.LabelFrame(self._codes_inner, text=f"{mark} {fam}", bg="#ffffff", padx=8, pady=6)
            fam_box.pack(fill="x", padx=8, pady=6)

            # Explicit heading inside the card so family name is always obvious.
            tk.Label(
                fam_box,
                text=f"Harness Family: {fam}",
                bg="#ffffff",
                fg="#11314f",
                font=("Segoe UI", 10, "bold")
            ).pack(anchor="w", pady=(0, 4))

            head = ttk.Frame(fam_box)
            head.pack(fill="x", pady=(0, 4))
            ttk.Button(head, text="Select all", command=lambda f=fam: self._set_family_checks(f, True)).pack(side="left", padx=2)
            ttk.Button(head, text="Deselect all", command=lambda f=fam: self._set_family_checks(f, False)).pack(side="left", padx=2)
            ttk.Button(head, text="Mark Reviewed", command=lambda f=fam: self._mark_family_reviewed(f)).pack(side="left", padx=8)

            vars_map = self._family_code_vars.get(fam, {})
            std_codes = self._family_status_codes[fam]["STANDARD"]
            opt_codes = self._family_status_codes[fam]["OPTIONAL"]

            self._render_family_code_group(fam_box, fam, "STANDARD SalesCodes", std_codes, vars_map, "#C6EFCE")
            self._render_family_code_group(fam_box, fam, "OPTIONAL SalesCodes", opt_codes, vars_map, "#FFEB9C")

        self._update_selection_summary()

    def _render_family_code_group(self, parent, family_name, title, codes, vars_map, bg):
        box = tk.LabelFrame(parent, text=title, bg=bg, padx=8, pady=6)
        box.pack(fill="x", padx=4, pady=4)
        if not codes:
            tk.Label(box, text="(none)", bg=bg).pack(anchor="w")
            return
        cols = 6
        for i, code in enumerate(codes):
            r, c = divmod(i, cols)
            tk.Checkbutton(
                box,
                text=code,
                variable=vars_map[code],
                bg=bg,
                activebackground=bg,
                command=lambda f=family_name: self._on_family_code_toggle(f),
            ).grid(row=r, column=c, sticky="w", padx=4, pady=2)

    def _on_family_code_toggle(self, family_name: str):
        self._family_reviewed[family_name] = False
        self._profile_loaded = False
        self._render_all_family_boxes()
        self._refresh_status_label()
        self._refresh_selection_readiness()

    def _set_family_checks(self, family_name: str, value: bool):
        for var in self._family_code_vars.get(family_name, {}).values():
            var.set(value)
        self._family_reviewed[family_name] = False
        self._profile_loaded = False
        self._render_all_family_boxes()
        self._refresh_status_label()
        self._refresh_selection_readiness()

    def _mark_family_reviewed(self, family_name: str):
        self._family_reviewed[family_name] = True
        self._render_all_family_boxes()
        self._refresh_status_label()
        self._refresh_selection_readiness()

    def _mark_all_reviewed(self):
        for fam in self._families:
            self._family_reviewed[fam] = True
        self._render_all_family_boxes()
        self._refresh_status_label()
        self._refresh_selection_readiness()

    def _update_selection_summary(self):
        reviewed = sum(1 for fam in self._families if self._family_reviewed.get(fam, False))
        total_codes = sum(len(self._family_code_vars.get(fam, {})) for fam in self._families)
        selected_codes = sum(
            sum(1 for v in self._family_code_vars.get(fam, {}).values() if v.get())
            for fam in self._families
        )
        if hasattr(self, "_selection_summary_lbl") and self._selection_summary_lbl is not None:
            self._selection_summary_lbl.config(
                text=f"Harnesses reviewed: {reviewed}/{len(self._families)}   |   "
                     f"Selected: {selected_codes}/{total_codes}"
            )

    def _all_reviewed(self):
        return bool(self._families) and all(self._family_reviewed.get(f, False) for f in self._families)

    def _refresh_selection_readiness(self):
        ready = self._all_reviewed() or self._profile_loaded
        state = "normal" if ready else "disabled"
        if self._continue_btn_tab is not None:
            self._continue_btn_tab.configure(state=state)
        if self._continue_btn_bottom is not None:
            self._continue_btn_bottom.configure(state=state)
        if self._export_btn is not None:
            self._export_btn.configure(state=("normal" if self._all_reviewed() else "disabled"))

    def _build_profile_dataframe(self):
        rows = []
        for fam in self._families:
            vars_map = self._family_code_vars.get(fam, {})
            std_set = set(self._family_status_codes[fam]["STANDARD"])
            opt_set = set(self._family_status_codes[fam]["OPTIONAL"])
            for code in sorted(vars_map.keys()):
                if code in std_set:
                    status = "STANDARD"
                elif code in opt_set:
                    status = "OPTIONAL"
                else:
                    status = "UNKNOWN"
                rows.append({
                    "HarnessFamily": fam,
                    "SalesCode": code,
                    "Status": status,
                    "Selected": bool(vars_map[code].get()),
                    "Reviewed": bool(self._family_reviewed.get(fam, False)),
                })
        return pd.DataFrame(rows)

    def _export_selection_profile(self):
        if not self._all_reviewed():
            messagebox.showinfo("Not Ready", "Review all harness families before exporting.", parent=self._win)
            return
        path = filedialog.asksaveasfilename(
            title="Export SalesCode Selection Profile",
            defaultextension=".xlsx",
            initialfile="SalesCode_Selection_Profile.xlsx",
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")],
            parent=self._win,
        )
        if not path:
            return
        df = self._build_profile_dataframe()
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Family_Code_Selection", index=False)
        messagebox.showinfo("Exported", f"Selection profile saved:\n{path}", parent=self._win)

    def _load_selection_profile(self):
        path = filedialog.askopenfilename(
            title="Load SalesCode Selection Profile",
            filetypes=[("Excel files", "*.xlsx *.xlsm *.xls"), ("All files", "*.*")],
            parent=self._win,
        )
        if not path:
            return
        try:
            df = pd.read_excel(path, sheet_name="Family_Code_Selection", engine="openpyxl")
        except Exception:
            df = pd.read_excel(path, engine="openpyxl")

        required = {"HarnessFamily", "SalesCode", "Selected"}
        if not required.issubset(set(df.columns)):
            messagebox.showerror("Invalid File", "Profile must include columns: HarnessFamily, SalesCode, Selected", parent=self._win)
            return

        # Reset current selections first.
        for fam in self._families:
            for var in self._family_code_vars.get(fam, {}).values():
                var.set(False)

        for _, row in df.iterrows():
            fam = str(row.get("HarnessFamily", "")).strip()
            code = str(row.get("SalesCode", "")).strip().upper()
            sel = row.get("Selected", False)
            if fam in self._family_code_vars and code in self._family_code_vars[fam]:
                is_selected = bool(sel)
                if isinstance(sel, str):
                    is_selected = sel.strip().upper() in ("TRUE", "1", "YES", "Y")
                self._family_code_vars[fam][code].set(is_selected)

        for fam in self._families:
            self._family_reviewed[fam] = True

        self._profile_loaded = True
        self._render_all_family_boxes()
        self._refresh_status_label()
        self._refresh_selection_readiness()
        messagebox.showinfo("Loaded", "Selection profile loaded successfully.", parent=self._win)

    def _refresh_status_label(self):
        total = 0
        selected = 0
        for fam in self._families:
            vars_map = self._family_code_vars.get(fam, {})
            total += len(vars_map)
            selected += sum(1 for v in vars_map.values() if v.get())
        reviewed = sum(1 for fam in self._families if self._family_reviewed.get(fam, False))
        if self._status_lbl is None:
            return
        self._status_lbl.config(
            text=f"Reviewed harnesses: {reviewed}/{len(self._families)}   |   "
                 f"Selected codes: {selected}/{total}   |   Excluded: {total - selected}")

    # --------------------------------------------------- Treeview helper
    def _make_tree(self, parent, cols, col_widths=None):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True, padx=6, pady=4)
        vsb = ttk.Scrollbar(frame, orient="vertical")
        hsb = ttk.Scrollbar(frame, orient="horizontal")
        tree = ttk.Treeview(frame, columns=cols, show="headings",
                            yscrollcommand=vsb.set, xscrollcommand=hsb.set,
                            selectmode="browse")
        vsb.configure(command=tree.yview)
        hsb.configure(command=tree.xview)
        for col in cols:
            w = (col_widths or {}).get(col, 100)
            tree.heading(col, text=col,
                         command=lambda c=col: self._sort_tree(tree, c, False))
            tree.column(col, width=w, minwidth=50, anchor="center")
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        tree.pack(fill="both", expand=True)
        return tree

    def _sort_tree(self, tree, col, reverse):
        data = [(tree.set(k, col), k) for k in tree.get_children("")]
        try:
            data.sort(key=lambda t: float(t[0].rstrip('%')), reverse=reverse)
        except ValueError:
            data.sort(key=lambda t: t[0].lower(), reverse=reverse)
        for idx, (_, k) in enumerate(data):
            tree.move(k, "", idx)
        tree.heading(col, command=lambda: self._sort_tree(tree, col, not reverse))

    # --------------------------------------------------- proceed / cancel
    def _on_proceed(self):
        if not (self._all_reviewed() or self._profile_loaded):
            messagebox.showinfo("Not Ready", "Review all harness families or load a profile before continuing.", parent=self._win)
            return
        self.result = {
            fam: {code for code, var in self._family_code_vars.get(fam, {}).items() if var.get()}
            for fam in self._families
        }
        self._win.destroy()
def ask_save_folder():
    """Prompt user to select folder to save the populated template."""
    root = Tk(); root.withdraw(); root.attributes('-topmost', True)
    folder = filedialog.askdirectory(
        title="Select folder to save the populated template"
    )
    root.destroy()
    return folder
def ask_output_folder(default_dir: str = ""):
    """Prompt user to select where all output files should be saved."""
    root = Tk(); root.withdraw(); root.attributes('-topmost', True)
    folder = filedialog.askdirectory(
        title="Select folder to save output files",
        initialdir=(default_dir or os.getcwd())
    )
    root.destroy()
    return folder
def main():
    # Startup setup window (MY + Program + input files)
    setup = collect_run_setup_inputs()
    if not setup:
        try:
            root = Tk(); root.withdraw()
            messagebox.showinfo("Canceled", "Setup canceled. Exiting.")
            root.destroy()
        except Exception:
            pass
        return

    my = setup["my"]
    program = setup["program"]
    input_type = setup.get("input_type", "doall")
    path = setup.get("input_file") or setup.get("build_spec")
    complexity_files = setup["harness_files"]
    out_dir = setup.get("output_dir") or os.path.dirname(path)

    print("\n" + "="*80)
    if input_type == "buildspec":
        print("STEP 1/5: LOAD BUILDSPEC FILE")
    else:
        print("STEP 1/5: LOAD DOALL FILE")
    print("="*80)
    print(f"✓ Loaded: {os.path.basename(path)}")

    # 2) VIN matrix
    print("\nProcessing VIN specifications...")
    vin_matrix_df, vin_codes_sorted = build_vin_matrix(path, source_type=input_type)
    print(f"✓ Found {len(vin_matrix_df)} VINs with {len(vin_codes_sorted)} unique sales codes")

    # 4) Harness files were selected in startup setup window
    print("\n" + "="*80)
    print("STEP 2/5: LOAD HARNESS COMPLEXITY FILES")
    print("="*80)
    if not complexity_files:
        try:
            root = Tk(); root.withdraw()
            messagebox.showinfo("No files selected", "No Complexity files selected. Done with VIN/spec only.")
            root.destroy()
        except Exception:
            pass
        return

    # 5) Read each Complexity and build data for master + outputs
    print("\nProcessing complexity files...")
    per_file_master = []  # (file, df_complexity)
    per_file_families = []  # dicts for selections/candidates
    all_complexity_codes = set()

    for f in complexity_files:
        try:
            df_comp, header_codes, pn_rows = read_complexity_sheet(f)
            family = try_get_harness_family(f)
            per_file_master.append((f, df_comp))
            per_file_families.append({
                "family": family,
                "header_codes": set(header_codes),
                "pns": pn_rows
            })
            all_complexity_codes.update(header_codes)
            print(f"✓ {os.path.basename(f)} | {family} | {len(header_codes)} codes | {len(pn_rows)} PNs")
        except Exception as e:
            print(f"✗ SKIPPED '{os.path.basename(f)}': {e}")

    if not per_file_master:
        print("No valid Complexity sheets read. Exiting.")
        return

    # 6) Prepare all output datasets (files are written after final output folder selection)
    print("\n" + "="*80)
    print("STEP 3/5: PROCESS DATA")
    print("="*80)
    print("✓ Data prepared for output files")

    # 7) SalesCode_Diff dataset (sheet is written after final output folder selection)
    vin_code_set = set(vin_codes_sorted)
    complexity_code_set = set(all_complexity_codes)
    diff_df = build_salescode_diff(vin_code_set, complexity_code_set)
    print(f"✓ SalesCode_Diff prepared")

    # Excluded_SalesCodes
    excluded_codes = sorted(list(vin_code_set - complexity_code_set))
    excluded_df = pd.DataFrame({"SalesCode_Not_In_Any_Harness": excluded_codes})

    # SalesCode statistics — computed BEFORE user review so the dialog can show them
    print("\nComputing sales code statistics...")
    family_stats_df, global_code_df = build_salescode_statistics(per_file_families)
    if not family_stats_df.empty:
        standard_pairs = int((family_stats_df["Status"] == "STANDARD").sum())
        unused_pairs    = int((family_stats_df["Status"] == "UNUSED").sum())
        print(f"✓ Stats: {standard_pairs} standard code/family pairs, "
              f"{unused_pairs} unused code/family pairs")

    # Show interactive review & code-selection dialog
    print("\nOpening SalesCode Analysis & Selection window...")
    _rev_root = Tk(); _rev_root.withdraw(); _rev_root.attributes('-topmost', True)
    if not family_stats_df.empty:
        _dialog = SalesCodeReviewDialog(_rev_root, family_stats_df,
                                        global_code_df)
        selected_codes_by_family = _dialog.result
    else:
        selected_codes_by_family = {
            fam["family"]: set(fam["header_codes"])
            for fam in per_file_families
        }
    _rev_root.destroy()

    if selected_codes_by_family is None:
        print("User cancelled the review. Exiting.")
        try:
            root = Tk(); root.withdraw()
            messagebox.showinfo("Cancelled", "Process cancelled at code-review step.")
            root.destroy()
        except Exception:
            pass
        return

    families_for_matching = filter_per_file_families(per_file_families, selected_codes_by_family)
    selected_union = set()
    for codes in selected_codes_by_family.values():
        selected_union.update(codes)
    excluded_by_user = all_complexity_codes - selected_union
    if excluded_by_user:
        print(f"✓ User excluded {len(excluded_by_user)} sales code(s) from matching: "
              f"{', '.join(sorted(excluded_by_user))}")

    # 8) Build Selections, AllCandidates, Final_BOM
    print("\nMatching harnesses to VINs...")
    selections_df, all_candidates_df, final_bom_df = build_outputs(
        vin_matrix_df, families_for_matching)
    print(f"✓ Generated selections for {len(selections_df)} VIN-Family pairs")

    # 8b) Ties are no longer resolved in a modal dialog. They are carried into
    # the macro-enabled SE review workbook together with incomplete and
    # ambiguous-N/A cases.
    ties = find_same_score_ties(all_candidates_df)
    if ties:
        print(f"✓ Found {len(ties)} tie case(s) — flagged for SE workbook review")
    else:
        print("✓ No ties detected")

    # Final output location prompt (after processing, before writing files)
    chosen_out_dir = ask_output_folder(out_dir)
    if chosen_out_dir:
        out_dir = chosen_out_dir
        print(f"✓ Output folder selected: {out_dir}")
    else:
        print(f"✓ Output folder not changed (using): {out_dir}")

    # Program-qualified naming: every output for this run carries the
    # {MY}_{Program} tag captured in the startup setup window (e.g. 27_KX),
    # matching the DEFE template name. Decided in exactly one place here.
    my_short = my[-2:] if len(my) >= 2 else my
    tag = f"{my_short}_{program}"
    master_file     = f"Master_Combined_Harness_Complexity_{tag}.xlsx"
    vin_matrix_file = f"VIN_Salescode_matrix_{tag}.xlsx"
    selections_file = f"VIN_to_Harness_Selection_{tag}.xlsx"
    review_file     = f"Harness_Selection_Review_{tag}.xlsm"
    defe_output_name = f"{tag}_VBOM_Template_for_DEFE.xlsx"

    # Resolve final output paths only after user picks destination.
    master_path = os.path.join(out_dir, master_file)
    vin_out_path = os.path.join(out_dir, vin_matrix_file)
    selections_out = os.path.join(out_dir, selections_file)

    # Write Master workbook in final selected folder.
    used_sheetnames = set()
    with pd.ExcelWriter(master_path, engine="openpyxl") as writer:
        for f, df_comp in per_file_master:
            sheet = safe_sheetname(os.path.basename(f), used_sheetnames)
            df_comp.to_excel(writer, sheet_name=sheet, index=False, header=False)
    format_workbook_output(master_path)
    print(f"✓ Created: {master_file}")

    # Write VIN matrix and append SalesCode_Diff in final selected folder.
    vin_matrix_df.to_excel(vin_out_path, index=False, engine="openpyxl")
    write_df_to_excel_append(vin_out_path, "SalesCode_Diff", diff_df)
    print(f"✓ Created: {vin_matrix_file} (with SalesCode_Diff)")

    # 9) Save VIN_to_Harness_Selection.xlsx
    print("\n" + "="*80)
    print("STEP 4/5: GENERATE OUTPUT FILES")
    print("="*80)
    with pd.ExcelWriter(selections_out, engine="openpyxl") as writer:
        selections_df.to_excel(writer, sheet_name="Selections", index=False)
        all_candidates_df.to_excel(writer, sheet_name="AllCandidates", index=False)
        excluded_df.to_excel(writer, sheet_name="Excluded_SalesCodes", index=False)
        final_bom_df.to_excel(writer, sheet_name="Final_BOM_By_VIN", index=False)
        if not family_stats_df.empty:
            family_stats_df.to_excel(writer, sheet_name="Family_Code_Stats", index=False)
            global_code_df.to_excel(writer, sheet_name="Global_Code_Overview", index=False)
    format_workbook_output(selections_out)
    print(f"✓ Created: {selections_file}")
    print("✓ Applied workbook formatting and highlights")

    # Format SalesCode statistics sheets
    try:
        _format_stats_sheets(selections_out)
        print(f"✓ Formatted SalesCode statistics sheets")
    except Exception as e:
        print(f"✓ Statistics sheets created (note: {e})")

    # 9.5) Create the macro-enabled review gate. The DEFE template is generated
    # only from this workbook after every uncertainty is explicitly resolved.
    print("\n" + "="*80)
    print("STEP 5/5: CREATE SELECTION REVIEW WORKBOOK")
    print("="*80)
    review_path = os.path.join(out_dir, review_file)
    template_src_path = os.path.join(os.path.dirname(__file__), TEMPLATE_SOURCE_FILE)
    if not os.path.exists(template_src_path):
        template_src_path = os.path.join(out_dir, TEMPLATE_SOURCE_FILE)
    vba_project_path = os.path.join(os.path.dirname(__file__), REVIEW_VBA_PROJECT_FILE)
    review_df = build_selection_review_cases(
        selections_df, all_candidates_df, families_for_matching)
    create_selection_review_workbook(
        review_path,
        review_df,
        selections_df,
        template_src_path,
        vba_project_path,
        defe_output_name=defe_output_name,
    )
    print(f"✓ Created: {review_file}")
    print(f"✓ Flagged {len(review_df)} VIN/family decision(s) for SE review")

    # Final completion dialog
    print("\n" + "="*80)
    print("✅ PROCESS COMPLETE!")
    print("="*80)
    
    try:
        root = Tk()
        root.withdraw()
        
        completion_msg = f"""✅ PROCESS COMPLETE!

📊 SUMMARY:
  • VINs Processed: {len(vin_matrix_df)}
  • Harness Families: {len(per_file_families)}
  • Selections Created: {len(selections_df)}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📁 OUTPUT LOCATIONS:

Main Output Folder:
  {out_dir}

Data Files:
  • {master_file}
  • {selections_file}
  • {vin_matrix_file}
  • {review_file}

Review Required:
  • Open {review_file}
  • Resolve all {len(review_df)} flagged decision(s)
  • Use its Generate DEFE Template button (creates {defe_output_name})

The DEFE template is intentionally withheld until the review is complete."""
        
        messagebox.showinfo("✅ Success", completion_msg)
        root.destroy()
    except Exception as e:
        print(f"Completion message: {e}")
if __name__ == "__main__":
    main()


# Moved back from the engine: these open dialogs, so they are GUI.
def collect_run_setup_inputs():
    """Open startup setup window and return run inputs or None if cancelled."""
    dlg = RunSetupDialog()
    return dlg.result

def ask_my_and_program():
    """Prompt user for MY (model year) and Program (e.g., RU)."""
    from tkinter import simpledialog
    root = Tk(); root.withdraw(); root.attributes('-topmost', True)
    
    my = simpledialog.askstring(
        "Model Year",
        "Enter Model Year (MY):\n(e.g., 27)",
        parent=root
    )
    if not my:
        root.destroy()
        return None, None
    
    program = simpledialog.askstring(
        "Program",
        "Enter Program:\n(e.g., RU)",
        parent=root
    )
    root.destroy()
    return my.strip() if my else None, program.strip() if program else None
