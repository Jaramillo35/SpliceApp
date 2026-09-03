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

### Added
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
