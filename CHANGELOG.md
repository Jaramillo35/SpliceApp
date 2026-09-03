# Changelog

What changed, for the people using the tool. Newest first. The Admin page
inside the tool renders this file, so an entry here is what an engineer sees
after an update.

## Unreleased

### Changed
- **One interface schema across the toolkit.** The rail is grouped by how you
  work — Workbenches (judgement, saved, signed off), Converters (files in,
  workbook out), Records, Utilities — with Admin and your name in the footer.
  Every page follows one of four shapes. Converters (DTx Compare, Splice
  Generation, HRN Chart Builder) show inputs beside the result, with one
  Run button that says what it still needs. Workbenches (Circuit
  Applicability, Circuit Health, Harness Complexity, VBOM Risk Matrix) have
  a step bar that shows where you are, a row of figures under it, and a
  header line saying who saved the workbench last.
- **Quieter inputs, clearer actions.** Upload boxes are no longer orange;
  the one orange button on a page is the action. Long runs report progress
  under the button, and what a run has to say stays on the page instead of
  disappearing as pop-ups.
- **Readable at a glance.** No text below 12 px; secondary text is a solid
  colour; tables share one style and say when they are showing only part of
  the rows; downloads are always a click and always named after the file.
- **Overview replaces Home.** It lists the last run of each tool (who, when,
  which programme) and what needs attention: cleanup rows not yet exported,
  dispositions, resolved review cases, open feedback tickets.
- **Team-safe saving.** Circuit Applicability (and the VBOM review gate)
  record who saved and refuse to overwrite a change someone else made since
  you loaded the page — you are asked to reload instead. Set your name once
  in the rail footer.
- **Keyboard and screen readers.** Filter chips, list rows and suggestion
  chips are real buttons; severity always shows the word; inputs have labels.
- **Workbooks read the same, whichever tool made them.** Every plain `.xlsx`
  you download now has one header style, frozen headers, filters, sensible
  column widths and a print setup, plus a **Read Me** sheet (last tab) with
  the Versigent mark, who generated it and when, which build of the tool,
  the programme, the input files, and a row count per sheet. The numbers in
  the sheets are exactly what they were. Macro workbooks, the DTx change
  report, the SECR, the DEFE template and the complexity files are left as
  they are.
- **The Complexity Cleanup sheet is now a work list, not a list of findings.**
  Every row leads with what to change and, in its own column, whether the
  correction belongs in the DTx, in the complexity matrix, or whether the two
  documents disagree and the customer has to say which is right. That call is
  made from the data: a condition no build can satisfy whose codes the matrix
  does track is a DTx contradiction; a code this file is missing but a sibling
  file tracks is real, so this file is the one to fix; a code no file tracks
  could be either, so the row asks the question instead of guessing. Rows are
  sorted worst first, carry the affected part numbers as evidence, and leave a
  Status column for you. Sales-code repairs you confirmed during the review are
  listed too — the workbench applied them locally, but unless the customer
  fixes the source they come back with the next export.
- **A 'Customer email' sheet** in the same workbook: the same list as text to
  paste into a mail client, grouped by where the change belongs, with findings
  that share one request collapsed into one numbered line. Read it before you
  send it; nothing is sent for you.
- **Versigent mark in the rail** and on every workbook's Read Me sheet, as
  cropped transparent variants — the shipped logo is mostly black plate,
  which is why it read as an empty box in the rail and would have printed as
  a black rectangle on a white sheet.
- **Downloads are named after the run.** Exports whose names are ours now
  carry the programme, the phase and the moment, so today's and yesterday's
  no longer overwrite each other in a Downloads folder.
- **Overview says what actually comes back.** The Continue list explains that
  uploaded files are never kept, and a reopened workbench names the mapping,
  repairs and selections it restored instead of looking empty.

### Fixed
- **Splice Generation read sales codes differently from the rest of the app.**
  It bound `&` tighter than `/`; every other engine binds `/` tightest, as
  `splice.inline.salescode` documents. So `ERC&CYC/CYF` — a real expression in
  the 2028RU X1 export — selected a part number carrying CYF without ERC. One
  grammar now, pinned by a test that evaluates both engines over every
  combination.
- **The "Display Sales Code" column could carry text that was not an
  expression.** The old simplifier split on `&` ignoring parentheses, so
  `(-AAA&-CCC)/(AAA&CCC)` came out unbalanced with a negation dropped. It now
  uses the same minimiser Circuit Health uses, which verifies the result means
  the same thing before returning it.
- **A malformed sales code no longer aborts the run.** It resolves to no
  harness, and the Validation Report names it under a new rule 7.
- `501` follows the same rule everywhere: universal only when it is the whole
  expression.

### Removed
- **Four hardcoded topologies for a circuit named `D454`** — six connector
  names, five sales codes and a literal connection table, applied to any file
  containing that circuit name. Every circuit now goes through the same path,
  and topology follows the endpoint count.
- **The circuit chart connects circuits it used to leave dangling.** A wire is
  now paired inside the harness it belongs to, instead of across the whole
  study. Two devices in one harness join even when that DTx family is mapped
  to several complexity files — the case that left circuit `A0` in BATTERY
  POSITIVE unconnected in both of its charts. Wired rows went from 89% to 99%.
- **Inline connections are now both connections.** The wire from a device to
  the inline inside its own harness, and the inline-to-inline joint into the
  next one, are separate things and the chart states both. New columns:
  Mates With Harness / CNUM / Cavity.
- **The Versigent mark never appeared.** It was rendered through a component
  that fades itself in once its own load handler fires; in the packaged app
  that handler did not fire, so the logo sat in the page at zero opacity.
- **Status text was too dim to read** on four of the five chip colours — the
  palette was validated for chart marks, not for small text.
- **Long attention lines rendered as chips**, which collapsed into a blob at
  narrow widths; they are notes now.
- **HRN Chart Builder read comma-separated matrix files as one column** and
  built the chart from that. The delimiter is now decided by the header line.
- **Showcase DTx exports** now carry every column the compare engine
  requires, and the demo ships a DTCR report, so DTx Compare runs end to end
  on the demo data.

### Added
- **Splices now follow the harness's own options.** A circuit does not have
  one topology: M34 in Door_Driver_2 reaches an LCF device, a LEQ/LEM device
  and an inline, so the part number carrying LCF needs a splice while the one
  without is a plain wire. The Circuit Chart groups a circuit's ends by which
  part numbers carry them and plans each group with the same engine Splice
  Generation uses, so the two surfaces cannot disagree.
- **Every splice leg carries its own expression** — its end's condition and
  its configuration's, together: `LCF&(LEM/LEQ)` for the LEQ/LEM device's leg,
  `-LCF&(LEM/LEQ)` for the wire that replaces the splice where LCF is absent.
  New chart columns: Leg Sales Code and Configuration.
- An end wired differently in another configuration gets a row for each,
  because one row cannot carry two far ends. Where two configurations reach
  the same ends they are merged into one row and their expressions OR-ed.
- **Admin page** (`/admin`): what version is running, what changed, whether each
  service answers, how much data there is, backups with one-click export and
  restore, the last few hundred log lines, and the feedback inbox.
- **Version identity**: the running commit and build time are stamped into the
  image and shown in the footer of every page and at `/version`.
- **Backups**: dated archives of the data directory, the newest ten kept, with
  a restore that keeps the data it replaces so it can itself be undone.
- **Logs**: engine warnings now go to a rotating file under the data
  directory instead of being discarded.
- **Circuit Applicability — circuit chart** (step 6): which part number
  carries which wire, per harness family, with a flat single-header sheet and
  the Circuit Summary layout Circuit Health reads. Conditions flow through
  each circuit and are restated in each harness's own sales codes; circuits
  reaching three or more cavities get a splice; every row names its far end.
- **Circuit Applicability — data quality** (step 5): a dashboard of what the
  DTx export gets right and what needs fixing at source, with never-built
  circuits, never-built connectors and sales-code gaps pre-selected for the
  customer review.
- **DTx Compare**: programme, phase and export date read from each file's
  title block; when two exports share a phase the dates tell them apart.

### Performance
- **DTx Compare is 6.5× faster**: 14.4 s → 2.2 s on a real 8,600-row pair.
  The comparison loop is vectorised, each file is parsed once instead of
  four times, and cell normalisation is column-wise. Output proven
  identical cell for cell. The test suite runs in 35 s instead of 60.
- The interface starts without pyarrow, altair or streamlit installed
  (0.8 s of a 0.9 s start was pyarrow being probed for nothing).

### Removed
- `splice/secr`, a 5,444-line copy of the SECR engine that no page used.
- The 42 MB recorder executable from git (published as a release instead)
  and a graphing tool's 104-file scratch cache.
- Eight functions nothing called, twelve unused imports, one unreachable block.
- The VBOM engine no longer loads the tkinter desktop app by file path; it is
  a plain module now (`splice/vbom/engine.py`) and the desktop app imports it.

### Changed
- **Launchers open the new interface** (`localhost:8504`). The previous
  Streamlit interface stays available at `localhost:8501`.
- **Update** now always fetches the release branch (`main`) rather than
  whatever branch the clone happened to be on.
- CI runs the whole test suite. It had been running 14 tests of 900+.
- Sales code `501` on its own means "every harness part number" and is no
  longer reported as a gap.

### Fixed
- **The circuit chart no longer treats "No Connect" as a circuit.** `N0` marks
  a cavity wired to nothing — 1,570 of 5,412 rows in a real export. Counting
  it produced 3,120 chart rows that were not wires, joined them into one
  fabricated 269-cavity splice, and gave 3,106 of them a far end. The chart
  now excludes them and says on the sheet how many it left out.

- Downloading the circuit chart on a large programme dropped the browser
  connection; the workbook write was quadratic and ran on the UI thread.
- Sales-code applicability is reconciled per harness from its device ends, so
  a `501` ground in one harness no longer erases a condition in another.

## 0.1.0 — 2026-07-07 (`live-2026-07-07`)

The Streamlit toolkit as first distributed: Splice Generation, DTx Compare,
Harness Complexity, HRN Chart Builder, VBOM Risk Matrix, SECR Database.
