# Changelog

What changed, for the people using the tool. Newest first. The Admin page
inside the tool renders this file, so an entry here is what an engineer sees
after an update.

## Unreleased

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
- Downloading the circuit chart on a large programme dropped the browser
  connection; the workbook write was quadratic and ran on the UI thread.
- Sales-code applicability is reconciled per harness from its device ends, so
  a `501` ground in one harness no longer erases a condition in another.

## 0.1.0 — 2026-07-07 (`live-2026-07-07`)

The Streamlit toolkit as first distributed: Splice Generation, DTx Compare,
Harness Complexity, HRN Chart Builder, VBOM Risk Matrix, SECR Database.
