# UI/UX Audit & Upgrade Plan — `ui-ux-upgrade` branch

Audited 2026-08-23 against three references: Emil Kowalski's design-engineering
principles (details compound; good defaults beat options; restraint), Apple's
design foundations (hierarchy, consistency, direct labels, feedback in four
kinds), and the dataviz method (color is computed, never eyeballed). Walked all
ten pages in the running app plus their source.

## The verdict in one line

The app's *engines* are consistent; its *surface* is ten pages built at
different times with different habits. Nothing is broken — but nothing
compounds, either. The fix is a small design system applied everywhere, not a
page-by-page repaint.

---

## Cross-cutting findings (ranked)

### 1. No theme — the app wears Streamlit's defaults, and fights them
- There is no `.streamlit/config.toml` theme. Primary color is **Streamlit
  red** (visible on every `type="primary"` button — VBOM's "Generate" is red),
  which clashes with the **Versigent orange** identity in the logo.
- The app renders light or dark depending on each user's browser — but
  `home.py` hardcodes a **light-only** palette (white `#ffffff` cards, pale
  hero gradient, dark ink). In dark mode the home page is a wall of glaring
  light panels on a near-black canvas. Worst single visual defect.
- Fix: define the theme once (dark-base brand theme, orange primary), and make
  all custom CSS read **Streamlit's own CSS variables**
  (`--primary-color`, `--background-color`, `--secondary-background-color`,
  `--text-color`) so custom surfaces follow the theme automatically.

### 2. Two feedback systems compete in the sidebar
- Older pages (Splice Gen, DTx, VBOM) mount the **feedback widget** ("Report an
  issue or feedback", GitHub-syncing tickets). SECR pages mount the **support
  panel** ("Report a problem", diagnostic export). Same job, two faces, and a
  user sees a different one depending on the page.
- Fix: one sidebar component, everywhere — the ticket store underneath is
  already shared.

### 3. Page identity is inconsistent
- Nav says *Splice Generation*; the page's H1 says *Wiring Harness Splice
  Generator*. Some pages have captions, some don't; icons appear in nav but
  never on pages; only Circuit Health numbers its sections ("1 · Inputs").
- Fix: a `page_header(title, caption, icon)` component; title always equals
  the nav name.

### 4. Layout rhythm varies page to page
- Global `layout="wide"`, but older pages pour widgets into one narrow column
  (VBOM's form floats in the left sixth of a wide window); newer pages use
  tabs, sections, and column grids. Upload→run→results is the same flow on
  seven pages, laid out five different ways.
- Fix: one flow scaffold — inputs card → primary action → results — with a
  bounded form width, adopted by every converter-style page.

### 5. Charts wear default colors, illegibly in places
- SECR dashboard (altair) and DTx family chart (`st.bar_chart`) use library
  defaults: unvalidated hues, no fixed category order, no legend discipline.
- Fix: one validated categorical palette (below), applied via a shared altair
  theme; `st.bar_chart` replaced with themed altair.

### 6. Status language is ad-hoc per page
- Circuit Health invented 🟥🟧🟨; Inline Continuity prints verdict strings;
  DTx shows bare metrics. Same concept — severity/status — three dialects.
- Fix: one `status_chip()` component (icon + label, never color alone — the
  dataviz status rule) reused by all three.

### 7. Small drift that reads as carelessness (Emil: details compound)
- Mixed `use_container_width=True` and `width="stretch"` (deprecation drift).
- Long runs (Circuit Health ≈1 min on real data) show a generic spinner with
  no progress narration; `st.status` with staged updates exists for this.
- Empty states range from a friendly icon'd `st.info` to nothing.
- Download buttons: five different label conventions ("Download X", "⬇ X",
  "Download all as ZIP"…).

---

## Per-page notes

| Page | State | Specific issues |
|---|---|---|
| Home | Worst offender | Light-only hardcoded colors; cards fight dark theme; hero text near-invisible contrast in dark |
| Splice Generation | Oldest habits | Title ≠ nav name; long single column; feedback widget |
| DTx Compare Report | Mixed | Two actions (PreOrder + Compare) interleaved confusingly; default-color bar chart; metrics row fine |
| SECR Database | Best reference | Tabs, search-first, altair charts (recolor only); support panel |
| Ask the Database | Good | Chat pattern fine; align header/caption |
| VBOM Risk Matrix | Sparse | Narrow floating form; red primary button; no results preview structure |
| Inline Continuity | Good bones | To be merged into Circuit Health (already agreed) |
| Circuit Health | Newest patterns | Numbered sections + guide are the model; adopt its patterns app-wide |
| HRN Chart Builder | Good | Pairing preview table good; unify download labels; admin expander styling |
| Meeting Transcripts | Good | Fragment status card is the model for live status; align buttons with system |

---

## The design system (what Phase 1 builds)

**Theme** (`.streamlit/config.toml`): dark base, brand orange primary
`#d95926`, neutral dark surfaces; light values chosen so both modes work.

**Tokens** (`ui/theme.py`): brand + semantic constants, the chart palette, and
one CSS injection (cards, badges, chips, hero) expressed in Streamlit CSS
variables — theme-correct in both modes by construction.

**Components** (`ui/components.py`): `page_header`, `section`, `card`,
`status_chip`, `empty_state`, `download_row`, `run_flow` scaffold. Pages
become thin again.

**Chart palette** — validated with the dataviz six-checks validator (not
eyeballed), orange-first for brand:

| Slot | Light | Dark |
|---|---|---|
| 1 orange | `#eb6834` | `#d95926` |
| 2 blue | `#2a78d6` | `#3987e5` |
| 3 aqua | `#1baf7a` | `#199e70` |
| 4 yellow | `#eda100` | `#c98500` |
| 5 magenta | `#e87ba4` | `#d55181` |
| 6 green | `#008300` | `#008300` |
| 7 violet | `#4a3aa7` | `#9085e9` |
| 8 red | `#e34948` | `#e66767` |

Validator results: **all hard gates pass in both modes** (worst adjacent CVD
ΔE 8.4 dark / 9.1 light ≥ 8; normal-vision 19.3/19.6 ≥ 15; chroma ≥ 0.1).
Light mode carries a contrast WARN on aqua/yellow/magenta → obligation:
charts using them keep visible labels or a table view (our pages already
render dataframes alongside charts — keep that).

**Motion**: per Emil/Apple — restraint. Streamlit limits animation anyway; we
spend the budget on *feedback*, not decoration: staged `st.status` narration
for long runs, `st.toast` on completions, and no gratuitous transitions.

---

## Phased plan

1. **Foundation** — theme config, `ui/theme.py`, `ui/components.py`, rebuild
   Home theme-aware, unify page titles with nav names. *(Biggest visible win.)*
2. **Adoption** — migrate all pages to the components; one feedback sidebar;
   kill width/deprecation drift; standardize download labels and empty states.
3. **Dataviz** — altair theme with the validated palette; replace
   `st.bar_chart`; recolor SECR dashboard; status chips in Circuit Health /
   Inline verdicts.
4. **Flows** — the upload→run→results scaffold on all converter pages; staged
   progress for long runs; merge Inline Continuity into Circuit Health.

Each phase lands as its own commit(s) on `ui-ux-upgrade`, verified in both
light and dark mode before moving on; `secr-database` (and the deployed host)
stays on the stable UI until the branch merges.
