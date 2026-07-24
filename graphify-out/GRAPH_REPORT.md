# Graph Report - Splice  (2026-07-24)

## Corpus Check
- 65 files · ~55,371 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 752 nodes · 1552 edges · 35 communities (21 shown, 14 thin omitted)
- Extraction: 99% EXTRACTED · 1% INFERRED · 0% AMBIGUOUS · INFERRED: 23 edges (avg confidence: 0.58)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `d2685823`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- wiring_harness_processor.py
- app.py
- MetricsTracker
- Any
- main_app.py
- Automotive Wiring Automation
- dtx_compare_engine.py
- SalesCodeReviewDialog
- RunSetupDialog
- Interview Guide
- FeedbackStore
- run_vbom_workflow
- secr_engine.py
- vercel_app.py
- vercel.json
- Z913_example_input_defb8f5d.md
- models.py
- SECR_TEMPLATE_a714dc32.md
- Template_2aa0f431.md
- run_app.sh
- secr_db.py
- dashboard.js
- _auto_enrich_secr_if_requested
- app.py
- SECR Database — Architecture, Requirements & Task Plan
- load_dtcr_matching_report
- PostgreSQL Setup for the SECR Database on Streamlit Cloud
- Windows Install Guide (Local Use)
- iSpeed DTCR Attachment Downloader
- shared.js
- export_dtcr_mapping_styled
- copilot-instructions.md
- build_windows_bundle.sh
- __init__.py
- splice

## God Nodes (most connected - your core abstractions)
1. `RunSetupDialog` - 27 edges
2. `normalize_value()` - 26 edges
3. `_run_analysis_core()` - 24 edges
4. `SalesCodeReviewDialog` - 23 edges
5. `MetricsTracker` - 21 edges
6. `main()` - 20 edges
7. `auto_enrich_secr()` - 18 edges
8. `SpliceInputError` - 17 edges
9. `JsonMetricsStorage` - 16 edges
10. `parse_sales_code_expression()` - 15 edges

## Surprising Connections (you probably didn't know these)
- `_step_dtcr_matching()` --calls--> `load_dtcr_report()`  [EXTRACTED]
  ui/pages/secr_management.py → splice/dtx_compare/engine.py
- `_step_dtcr_matching()` --calls--> `generate_dtcr_matching_report()`  [EXTRACTED]
  ui/pages/secr_management.py → splice/dtx_compare/engine.py
- `_step_enrich()` --calls--> `auto_enrich_secr()`  [EXTRACTED]
  ui/pages/secr_management.py → splice/secr/numbering.py
- `MetricsTracker` --uses--> `MetricsStorage`  [INFERRED]
  metrics/tracker.py → metrics/storage.py
- `WorkflowRunContext` --uses--> `MetricsStorage`  [INFERRED]
  metrics/tracker.py → metrics/storage.py

## Import Cycles
- None detected.

## Communities (35 total, 14 thin omitted)

### Community 0 - "wiring_harness_processor.py"
Cohesion: 0.06
Nodes (90): ExcelFile, Splice generation — harness complexity + option logic -> splice workbook.  The i, _ast_to_postfix(), _build_d454_engineering_configurations(), build_harness_presence_matrix(), _candidate_codes_for_configuration(), _canonical_sd454_name(), _choose_anchor_endpoint() (+82 more)

### Community 1 - "app.py"
Cohesion: 0.10
Nodes (39): _build_secr_code(), _copy_cell_style(), _copy_sheet(), _copy_summary_values(), create_secr_bytes(), _find_action_col(), _find_first_col(), _find_header_map() (+31 more)

### Community 2 - "MetricsTracker"
Cohesion: 0.10
Nodes (19): BaseException, clamp_optional_count(), manual_touchpoints_eliminated(), time_saved_minutes(), time_savings_percentage(), to_minutes(), render_metrics_dashboard(), _categorize_failure() (+11 more)

### Community 3 - "Any"
Cohesion: 0.11
Nodes (15): build_metrics_storage(), _get_config_value(), _get_streamlit_secret(), JsonMetricsStorage, _mean_or_none(), _median_or_none(), MetricsStorage, NoopMetricsStorage (+7 more)

### Community 4 - "main_app.py"
Cohesion: 0.06
Nodes (55): apply_tie_break_overrides(), ask_my_and_program(), ask_output_folder(), ask_save_folder(), build_outputs(), build_salescode_diff(), build_salescode_statistics(), _build_short_sheet_name() (+47 more)

### Community 5 - "Automotive Wiring Automation"
Cohesion: 0.04
Nodes (39): Architecture, Key Design Principles, Overview, Runtime Data Flow, Anti-patterns, Commit Message Guide, Good examples, Optional body template (+31 more)

### Community 6 - "dtx_compare_engine.py"
Cohesion: 0.07
Nodes (67): Counter, ExcelWriter, extract_bulletin_number(), extract_transmittal_number(), normalize_cell(), normalize_match_text(), normalize_value(), Text normalization and field-extraction helpers shared across engines.  These we (+59 more)

### Community 8 - "RunSetupDialog"
Cohesion: 0.16
Nodes (4): _parse_drop_files(), Startup window for MY/Program and input file selection., Parse tkdnd payload into local file paths (supports macOS file:// URIs)., RunSetupDialog

### Community 9 - "Interview Guide"
Cohesion: 0.09
Nodes (22): Architecture Walkthrough, Before an Interview, Boolean expression parsing and simplification, Business logic outside Streamlit, Deterministic normalization, File-in/file-out processing, How do you prevent incorrect automated output?, How is this related to AI or ML engineering? (+14 more)

### Community 10 - "FeedbackStore"
Cohesion: 0.25
Nodes (7): FeedbackStore, _get_config_value(), get_feedback_area_options(), _get_streamlit_secret(), Any, PathLike, render_feedback_widget()

### Community 11 - "run_vbom_workflow"
Cohesion: 0.33
Nodes (10): VBOM risk-matrix workflow.  Thin orchestration over the legacy VBOM desktop modu, _build_short_sheet_name(), format_workbook_output(), _load_vbom_module(), Path, PathLike, _resolve_vbom_root(), run_vbom_workflow() (+2 more)

### Community 12 - "secr_engine.py"
Cohesion: 0.28
Nodes (7): System Engineer Toolkit — Streamlit entry point.  This file is intentionally thi, Logger, configure(), get_logger(), Lightweight logging setup for the splice package.  Engines call :func:`get_logge, Initialize root logging once. Safe to call repeatedly (no-op after first)., Return a module logger (use ``get_logger(__name__)``).

### Community 20 - "secr_db.py"
Cohesion: 0.10
Nodes (37): Connection, get_secret(), _path_from_env(), Path, Environment-specific configuration: filesystem paths, tokens, feature flags.  Ev, Return ``$env_key`` as an expanded path, or ``default`` if unset/empty., Look up a value from the environment, then Streamlit secrets.      Accepts sever, _date_text() (+29 more)

### Community 21 - "dashboard.js"
Cohesion: 0.14
Nodes (31): addLog(), chooseDirectory(), clickBackToResults(), clickRowAndOpen(), collectExistingDtcrNumbers(), delay(), downloadAttachment(), ensureResultsFrame() (+23 more)

### Community 22 - "_auto_enrich_secr_if_requested"
Cohesion: 0.05
Nodes (76): Exception, ValueError, Exception hierarchy for the splice package.  ``SpliceInputError`` subclasses ``V, Base class for every error raised deliberately by the splice package., The user-provided input is invalid — empty upload, unreadable file, etc., A required column or sheet is missing from an uploaded workbook., SpliceError, SpliceInputError (+68 more)

### Community 23 - "app.py"
Cohesion: 0.35
Nodes (11): create_secr_counts(), dtcr_matching_counts(), dtx_compare_counts(), dtx_preorder_counts(), Any, DataFrame, Series, _safe_len() (+3 more)

### Community 24 - "SECR Database — Architecture, Requirements & Task Plan"
Cohesion: 0.14
Nodes (13): 1. How Create SECR and Update SECR work today (as-is analysis), 2. Requirements, 3. Architecture, 4. Task plan, 5. Risks / later, Create SECR (`app.py` ~line 1084, engine: `secr_engine.create_secr_bytes`), Data-capture notes, Functional (+5 more)

### Community 26 - "PostgreSQL Setup for the SECR Database on Streamlit Cloud"
Cohesion: 0.22
Nodes (8): 1. The one thing to understand first, 2. Local Postgres (development), 3. Hosted Postgres (what Streamlit Cloud uses), 4. Secrets — never put the URL in code or git, 5. Dependencies, 6. Code change required in `secr_db.py`, 7. Deployment checklist, PostgreSQL Setup for the SECR Database on Streamlit Cloud

### Community 27 - "Windows Install Guide (Local Use)"
Cohesion: 0.33
Nodes (5): 1. Prerequisites, 2. Install, 3. Run (Local only), 4. Stop, Windows Install Guide (Local Use)

### Community 28 - "iSpeed DTCR Attachment Downloader"
Cohesion: 0.33
Nodes (5): Install locally, iSpeed DTCR Attachment Downloader, Notes, Use, What it does

### Community 29 - "shared.js"
Cohesion: 0.53
Nodes (5): cleanAttachmentName(), csvEscape(), isExcludedStatus(), makeSummaryCsv(), normalizeSpace()

## Knowledge Gaps
- **91 isolated node(s):** `params`, `sourceTabId`, `initialError`, `ui`, `stats` (+86 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **14 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `load_dtcr_report()` connect `dtx_compare_engine.py` to `app.py`, `_auto_enrich_secr_if_requested`?**
  _High betweenness centrality (0.120) - this node is a cross-community bridge._
- **Why does `FeedbackStore` connect `FeedbackStore` to `wiring_harness_processor.py`, `dtx_compare_engine.py`?**
  _High betweenness centrality (0.059) - this node is a cross-community bridge._
- **Why does `render_feedback_widget()` connect `FeedbackStore` to `wiring_harness_processor.py`, `dtx_compare_engine.py`?**
  _High betweenness centrality (0.048) - this node is a cross-community bridge._
- **What connects `params`, `sourceTabId`, `initialError` to the rest of the system?**
  _91 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `wiring_harness_processor.py` be split into smaller, more focused modules?**
  _Cohesion score 0.05785819482432148 - nodes in this community are weakly interconnected._
- **Should `app.py` be split into smaller, more focused modules?**
  _Cohesion score 0.10299003322259136 - nodes in this community are weakly interconnected._
- **Should `MetricsTracker` be split into smaller, more focused modules?**
  _Cohesion score 0.10359408033826638 - nodes in this community are weakly interconnected._