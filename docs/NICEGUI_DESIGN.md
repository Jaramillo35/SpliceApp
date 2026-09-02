# Splice on NiceGUI — design & migration

Decision (2026-08-23): the whole app moves to NiceGUI. Engines (`splice/`,
`secrdb/`) are imported unchanged — this is a surface migration, run
side-by-side with Streamlit until parity, then the Streamlit shell retires.

## Information architecture

One fixed left rail grouped by how the engineer works, not by what the code
is (interface schema study, 2026-09-02). Every entry comes from the page
registry in `nicegui_app/components.py` (`PAGES`); the rail, the Overview
grid and the feedback dialog read the same list.

```
  OVERVIEW                 continue where you left off · needs attention

  WORKBENCHES              judgement, saved, signed off
    Circuit Applicability · Circuit Health · Harness Complexity · VBOM Risk Matrix
  CONVERTERS               files in, workbook out
    DTx Compare · Splice Generation · HRN Chart Builder
  RECORDS                  search the history
    SECR Database · Ask the Database
  UTILITIES
    Meeting Transcripts · Downloads
  ---------------------------------------------------------------
  Admin · v0.1.0           rail footer
```

Active state is by route. Below 1024 px the rail hides and a header button
opens it; it never overlays the content column on its own.

## Design language

| Token | Value |
|---|---|
| Canvas / surface | `#0e1117` / `#1a1d24` (dark-first, committed) |
| Brand primary | `#d95926` (Versigent orange) |
| Text / muted | `#e8e8ec` / 60–74% mixes |
| Line | text @ 12–14% |
| Radius | 12px cards, 999px chips |
| Status | blocker `#e66767` · high `#c98500` · review `#d5c04b` · ok `#199e70` · info `#3987e5` — always icon + label |
| Charts | validated orange-first categorical set (see UI_UX_AUDIT.md), via echarts |
| Motion | 140–180ms ease-out reveals; press scale 0.97; `prefers-reduced-motion` honored; nothing decorative |

## Interaction canon (every page obeys)

1. **One flow shape**: inputs card → primary action → results. Uploads read
   bytes immediately (chips confirm each file); engines run via
   `run.io_bound` with a spinner notification; completion is a toast.
2. **No page ever rebuilds** — `@ui.refreshable` sections update in place.
3. **Destructive or judgment actions get dialogs** (dispositions, deletes).
4. **Downloads are buttons with the filename as label** — one convention.
5. **Empty states teach**: what to load, where it comes from, what happens.
6. **Errors are captions under the thing that failed**, not global banners.

## Architecture

```
nicegui_app/
  main.py          entry: theme boot, imports pages (routes), ui.run
  theme.py         tokens + global CSS + apply()
  components.py    frame (rail+header+content), cards, chips, upload zones,
                   engine runner, download helpers, feedback dialog
  pages/           one module per route, thin over the engines
```

- Per-client state lives in closures inside each `@ui.page` builder —
  module-level singletons are shared across users and are only used for
  process-wide things (the transcripts Recorder, baselines on disk).
- Engines run in worker threads (`run.io_bound`); the UI thread never blocks.
- Feedback: one global dialog (header button on every page) writing to the
  existing FeedbackStore.

## Migration waves

1. **Shell + daily drivers** (this commit): frame/theme/components, Home,
   Circuit Health, HRN Chart Builder, DTx Compare, VBOM, Splice Generation
   (core flow), Meeting Transcripts, SECR Browse/Import/Dashboard,
   Ask the Database, global feedback.
2. **SECR parity**: Create/Update SECR forms, DTCR reports library,
   batch tooling, supplier-ticket admin panel on HRN page.
3. **Cutover**: Docker image serves NiceGUI on :8501, Streamlit retires;
   Windows exe spec swaps entry point.

Until wave 3, Streamlit remains the deployed truth; the NiceGUI app runs on
:8504 (`python -m nicegui_app`).
