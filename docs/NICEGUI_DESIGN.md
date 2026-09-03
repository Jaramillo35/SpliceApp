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
| Canvas / surface / surface-2 / surface-3 | `#0e1117` / `#1a1d24` / `#14161c` (rail, header, uploads) / `#21252e` (hover, selected) |
| Brand primary | `#d95926` (Versigent orange) — spent on the primary action, the active nav item and selected rows, nowhere else |
| Text / text-2 / text-3 | `#e8e8ec` / `#a7adb6` / `#767d87` — solid tiers, never opacity |
| Line / grid | text @ 13 % / text @ 8 % |
| Brand mark | `assets/versigent_logo_dark.png` in the rail, `..._light.png` on white paper — both cropped, transparent variants of the shipped JPG (`scripts/make_logo_variants.py`). Rendered as a plain `<img>` off the `/sx-assets` route: `ui.image()` is a Quasar `q-img` that fades in from `opacity: 0` on its own load handler, and in the packaged app that handler never fired, so the mark was in the DOM and invisible. |
| Status | marks and borders take `STATUS`; anything read as text takes `STATUS_TEXT`, the same hues lightened until every pairing clears 4.5:1 |
| Font | system UI (Segoe UI on the Windows hosts, San Francisco on Mac); mono for identifiers |
| Type scale | title 20/600 · section 16/600 · body 14 · data 13 tabular · caption 12 (the floor) · eyebrow 11/600 uppercase +0.08em · KPI 24/600 tabular |
| Space | 4 · 8 · 12 · 16 · 24 · 32 · 48; card padding 16, section gap 24, page padding 24; content max 1,280 |
| Radius | 6 controls · 10 cards · 999 chips |
| Status | blocker `#e66767` · high `#c98500` · review `#d5c04b` · ok `#199e70` · info `#3987e5` — always icon + word, one green |
| Charts | validated orange-first categorical set via `components.echart` (theme axis, grid, tooltip applied once) |
| Motion | 140–180 ms ease-out reveals; press scale 0.97; `prefers-reduced-motion` honoured; nothing decorative |

`tests/test_theme_tokens.py` refuses a colour literal or a sub-12px class
anywhere under `nicegui_app/` except `theme.py`.

## Page archetypes

Every route is exactly one of these. The archetype fixes the layout, where
the primary action lives, what the empty state says, and what the page
contributes to the Overview.

| Archetype | Pages | Shape |
|---|---|---|
| **A · Converter** | DTx Compare, Splice Generation, HRN Chart Builder | `components.converter()`: a narrow sticky inputs panel ending in one gated `action`, beside a `result_panel` that exists from the first paint and teaches until there is a result. Page-specific editors (Splice sales codes, HRN supplier list) sit below the grid at full width. |
| **B · Workbench** | Circuit Applicability, Circuit Health, Harness Complexity, VBOM Risk Matrix | `step_bar(...)` (sticky, states derived from state after every refresh) → `kpi_strip` → `section(step=...)` cards → sign-off. Judgement persists in a store that carries `saved_by`, `saved`, `revision`; the header `envelope` says who saved last; a stale write is refused, never merged. |
| **C · Records** | SECR Database, Ask the Database | Search first; named columns; tabs deep-linkable by query parameter. |
| **D · Utility** | Overview, Meeting Transcripts, Downloads, Admin | Overview reads the activity feed and the workbench stores; Transcripts is per machine; Admin holds the one confirm-dialog (restore). |

## Interaction canon, second edition (every page obeys)

1. **One primary action per page, gated, verb "Run".** `action(label, fn, needs=…)` is disabled until every named input exists and says what is missing. Secondary paths are outline buttons or links, never a second orange button.
2. **The accent is spent on the action.** Uploads are quiet rows; results get the width.
3. **The result panel always exists.** Before a run it teaches; after a run it is the first thing painted. Workbench cards may stay absent until their step is reachable — the step bar shows them waiting.
4. **One toast per action** (the runner's). Everything else the run has to say is a `note` on the page.
5. **Downloads are always a click, always the filename.** Several files become one `downloads` menu. Nothing is pushed on completion.
6. **Twelve pixels is the floor.** Density comes from spacing and tabular figures, not from shrinking.
7. **Status is icon plus word.** One green. Never a single letter, a coloured border alone, or a coloured label as an error.
8. **Every click target is a button or a link.** Filter chips (`toggle_chip`) are buttons with pressed state and the keyboard path charts mirror. Icon-only buttons carry a name.
9. **Caps are announced.** `frame_table(cap=…)` says how many rows it hides and points to the export.
10. **Shared writes carry an author and a revision.** The page shows who saved last; stale writes are refused with a reload prompt.
11. **Long pages have a position.** Workbenches show the step bar; converters fit inputs and result in one viewport above 1,024 px.
12. **Nothing decorative animates.**

## State

| Tier | Examples | Home |
|---|---|---|
| Per client | uploaded bytes, filters, selection, active tab | page closures |
| Per user | your name (rail footer), preferences | `app.storage.user` (cookie signed with `SPLICE_STORAGE_SECRET`) |
| Shared, team | mappings, repairs, cleanup ticks, dispositions, sign-offs, VBOM resolutions, SECR issuance | the stores under `data/`, each with `saved_by` / `saved` / `revision` |
| Per machine | the transcript recorder | the recorder exe (Part B); the page says so |

Every completed engine run is appended to `data/activity.jsonl` by the
runner (tool, route, summary, who, programme); the Overview's Continue list
reads it.

## Accessibility

`tests/test_accessibility.py` is the gate, and it computes rather than eyeballs:

- **Contrast.** Every status colour is checked as text on its own chip wash
  over all four surfaces, and on each surface directly; the three text tiers
  are held to AAA / AA / AA-large. `STATUS` keeps the validated chart steps,
  which read as marks but failed as 12 px text (`ok` was 4.13:1), so
  `STATUS_TEXT` exists for text and the two roles never mix.
- **Keyboard.** No page may attach a click handler to a non-interactive
  element, every icon-only button carries a tooltip or an `aria-label`, and
  filters and queue rows are native buttons with `aria-pressed` — which a
  browser activates on Enter and Space by definition.

Walked in the running app (2026-09-03, Docker image): on Circuit Health with
a finding open, the tab order runs rail → step bar → guide → inputs →
severity, kind and pair chips → search → the queue row → reason → the three
verdict buttons → engineer → download, every one with an accessible name and
nothing skipped. Activation by key press could not be driven from the
automation (it delivers no key events to the page), so that half stays a
manual check: Tab to a chip and press Enter.

## Exports

Every plain `.xlsx` a page hands over goes through `splice.common.workbook.dress`
on the way out (`components.deliver`). The engine's values are untouched — the
golden guard and the cell-diff proofs see exactly what they saw — and the
workbook the engineer opens has:

- one header style (navy `1F3B57`, white bold, wrapped, bottom rule), a
  freeze pane under the header, an autofilter, widths from content (8–60,
  notes columns 70 and wrapped), landscape print fitted to one page wide
  with the header row repeated;
- a **Read Me** sheet, last, with the Versigent mark, the run's envelope
  (tool and version, generated at and by whom, programme and phase, the
  input files), a sheet guide with row counts (so an empty sheet reads as
  "0 rows", not as a failure), and the status legend.

Read Me goes last and the active sheet is never changed, because Circuit
Health and the DTx engine read `wb.active` of the workbooks that feed them.

Not dressed, ever: `.xlsm` (customer macros), workbooks carrying charts or
drawings (an openpyxl round-trip would drop them — the DTx change report),
customer formats by name (`SECR_*`, templates, DEFE, `Harness_Complexity_*`),
and sheets that are forms rather than tables (merged cells, a title block).
`download(..., dress=False)` opts a file out explicitly.

## Architecture

```
nicegui_app/
  main.py          entry: theme boot, imports pages (routes), ui.run
  theme.py         tokens, type scale, global CSS, echart_theme(), apply()
  components.py    page registry (PAGES) · frame (rail + header + envelope)
                   · converter / result_panel · section / step_bar / set_step
                   · upload_row · action · kpi / kpi_strip · frame_table
                   · chip / toggle_chip / note · download / downloads · echart
                   · run_engine / run_engine_progress (log to the activity feed)
  pages/           one module (or package) per route, thin over the engines
```

- Per-client state lives in closures inside each `@ui.page` builder;
  per-client registries (gated actions, steps, header slot) hang off the
  client. Module-level singletons are only for process-wide things (the
  transcripts Recorder).
- Engines run in worker threads (`run.io_bound`); the UI thread never blocks.
- Feedback: one global dialog (header button on every page) writing to the
  existing FeedbackStore; its area list is the page registry.

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
