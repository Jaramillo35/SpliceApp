# Graph Report - Splice  (2026-07-23)

## Corpus Check
- 46 files · ~55,380 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 684 nodes · 1430 edges · 33 communities (24 shown, 9 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 43 edges (avg confidence: 0.65)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `b77868f8`
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

## God Nodes (most connected - your core abstractions)
1. `RunSetupDialog` - 27 edges
2. `_run_analysis_core()` - 24 edges
3. `SalesCodeReviewDialog` - 23 edges
4. `normalize_value()` - 22 edges
5. `MetricsTracker` - 22 edges
6. `main()` - 20 edges
7. `_auto_enrich_secr_if_requested()` - 16 edges
8. `JsonMetricsStorage` - 16 edges
9. `parse_sales_code_expression()` - 15 edges
10. `Automotive Wiring Automation` - 14 edges

## Surprising Connections (you probably didn't know these)
- `_auto_enrich_secr_if_requested()` --calls--> `build_bulletin_numbers_for_secr()`  [EXTRACTED]
  app.py → secr_enrichment_engine.py
- `_auto_enrich_secr_if_requested()` --calls--> `build_dtcr_numbers_for_secr()`  [EXTRACTED]
  app.py → secr_enrichment_engine.py
- `_auto_enrich_secr_if_requested()` --calls--> `build_enrichment_summary()`  [EXTRACTED]
  app.py → secr_enrichment_engine.py
- `_auto_enrich_secr_if_requested()` --calls--> `build_reason_for_change_for_secr()`  [EXTRACTED]
  app.py → secr_enrichment_engine.py
- `_auto_enrich_secr_if_requested()` --calls--> `load_dtcr_matching_report()`  [EXTRACTED]
  app.py → secr_enrichment_engine.py

## Import Cycles
- None detected.

## Communities (33 total, 9 thin omitted)

### Community 0 - "wiring_harness_processor.py"
Cohesion: 0.06
Nodes (88): ExcelFile, _ast_to_postfix(), _build_d454_engineering_configurations(), build_harness_presence_matrix(), _candidate_codes_for_configuration(), _canonical_sd454_name(), _choose_anchor_endpoint(), _choose_anchor_endpoint_with_preference() (+80 more)

### Community 1 - "app.py"
Cohesion: 0.14
Nodes (22): build_dtcr_numbers_for_secr(), build_enrichment_summary(), build_reason_for_change_for_secr(), _derive_device_transmittal_from_attachments(), _find_header_row(), load_dtcr_report(), _load_dtcr_summary_csv(), load_dtx_circuits_report() (+14 more)

### Community 2 - "MetricsTracker"
Cohesion: 0.10
Nodes (20): BaseException, clamp_optional_count(), manual_touchpoints_eliminated(), time_saved_minutes(), time_savings_percentage(), to_minutes(), render_metrics_dashboard(), build_metrics_storage() (+12 more)

### Community 3 - "Any"
Cohesion: 0.11
Nodes (14): _get_config_value(), _get_streamlit_secret(), JsonMetricsStorage, _mean_or_none(), _median_or_none(), MetricsStorage, NoopMetricsStorage, _parse_datetime() (+6 more)

### Community 4 - "main_app.py"
Cohesion: 0.07
Nodes (54): apply_tie_break_overrides(), ask_my_and_program(), ask_output_folder(), ask_save_folder(), build_outputs(), build_salescode_diff(), build_salescode_statistics(), _build_short_sheet_name() (+46 more)

### Community 5 - "Automotive Wiring Automation"
Cohesion: 0.04
Nodes (39): Architecture, Key Design Principles, Overview, Runtime Data Flow, Anti-patterns, Commit Message Guide, Good examples, Optional body template (+31 more)

### Community 6 - "dtx_compare_engine.py"
Cohesion: 0.09
Nodes (59): Counter, _all_changes_record(), _annotate_results_with_dtcr(), _apply_preorder_workbook_styles(), build_all_changes_df(), _build_combined_dtx_frame(), _build_connector_grouped_frame(), build_dashboard_sheet() (+51 more)

### Community 8 - "RunSetupDialog"
Cohesion: 0.15
Nodes (4): _parse_drop_files(), Startup window for MY/Program and input file selection., Parse tkdnd payload into local file paths (supports macOS file:// URIs)., RunSetupDialog

### Community 9 - "Interview Guide"
Cohesion: 0.09
Nodes (22): Architecture Walkthrough, Before an Interview, Boolean expression parsing and simplification, Business logic outside Streamlit, Deterministic normalization, File-in/file-out processing, How do you prevent incorrect automated output?, How is this related to AI or ML engineering? (+14 more)

### Community 10 - "FeedbackStore"
Cohesion: 0.26
Nodes (7): FeedbackStore, _get_config_value(), get_feedback_area_options(), _get_streamlit_secret(), Any, PathLike, render_feedback_widget()

### Community 11 - "run_vbom_workflow"
Cohesion: 0.40
Nodes (9): _build_short_sheet_name(), format_workbook_output(), _load_vbom_module(), Path, PathLike, _resolve_vbom_root(), run_vbom_workflow(), _style_worksheet() (+1 more)

### Community 12 - "secr_engine.py"
Cohesion: 0.20
Nodes (21): _build_secr_code(), _copy_cell_style(), _copy_sheet(), _copy_summary_values(), create_secr_bytes(), _find_action_col(), _find_first_col(), _find_header_map() (+13 more)

### Community 14 - "vercel.json"
Cohesion: 0.50
Nodes (3): builds, routes, version

### Community 20 - "secr_db.py"
Cohesion: 0.13
Nodes (31): Connection, _date_text(), find_by_dtcr(), find_by_item(), get_conn(), get_revision_chain(), get_secr(), init_db() (+23 more)

### Community 21 - "dashboard.js"
Cohesion: 0.14
Nodes (31): addLog(), chooseDirectory(), clickBackToResults(), clickRowAndOpen(), collectExistingDtcrNumbers(), delay(), downloadAttachment(), ensureResultsFrame() (+23 more)

### Community 22 - "_auto_enrich_secr_if_requested"
Cohesion: 0.13
Nodes (22): _auto_enrich_secr_if_requested(), DataFrame, _autosize_cell_for_text(), export_secr_enriched_output(), find_dtcr_number_label_cell(), find_reason_for_change_cell(), get_secr_harness_family_from_c12(), load_generated_secr_workbook() (+14 more)

### Community 23 - "app.py"
Cohesion: 0.19
Nodes (15): _build_secr_number_preview(), _extract_secr_number_inputs_from_def(), Build SECR number preview from form values and selected change type., Extract MY, Program(Vehicle Line), and Phase from DEF_DEF_Summary identifier., create_secr_counts(), dtcr_matching_counts(), dtx_compare_counts(), dtx_preorder_counts() (+7 more)

### Community 24 - "SECR Database — Architecture, Requirements & Task Plan"
Cohesion: 0.14
Nodes (13): 1. How Create SECR and Update SECR work today (as-is analysis), 2. Requirements, 3. Architecture, 4. Task plan, 5. Risks / later, Create SECR (`app.py` ~line 1084, engine: `secr_engine.create_secr_bytes`), Data-capture notes, Functional (+5 more)

### Community 25 - "load_dtcr_matching_report"
Cohesion: 0.17
Nodes (12): build_bulletin_numbers_for_secr(), extract_bulletin_number(), extract_device_control_number(), load_dtcr_matching_report(), match_dtcr_to_harness_family(), normalize_text(), Load a DTCR matching report workbook exported by DTCR Matching Report., Normalize text: uppercase, remove special chars, collapse spaces. (+4 more)

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

### Community 30 - "export_dtcr_mapping_styled"
Cohesion: 0.40
Nodes (5): export_dtcr_mapping_styled(), Apply readable formatting to the DTCR_Harness_Mapping sheet., Export DTCR mapping as a styled standalone workbook (table + autofit)., _style_dtcr_mapping_sheet(), Worksheet

## Knowledge Gaps
- **93 isolated node(s):** `params`, `sourceTabId`, `initialError`, `ui`, `stats` (+88 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **9 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `_build_vin_matrix_from_buildspec()` connect `main_app.py` to `dtx_compare_engine.py`?**
  _High betweenness centrality (0.101) - this node is a cross-community bridge._
- **Why does `load_dataframe()` connect `main_app.py` to `dtx_compare_engine.py`?**
  _High betweenness centrality (0.093) - this node is a cross-community bridge._
- **Why does `RunSetupDialog` connect `RunSetupDialog` to `main_app.py`?**
  _High betweenness centrality (0.050) - this node is a cross-community bridge._
- **Are the 20 inferred relationships involving `ValueError` (e.g. with `_auto_enrich_secr_if_requested()` and `_build_dtcr_lookup_by_cnum()`) actually correct?**
  _`ValueError` has 20 INFERRED edges - model-reasoned connections that need verification._
- **What connects `params`, `sourceTabId`, `initialError` to the rest of the system?**
  _93 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `wiring_harness_processor.py` be split into smaller, more focused modules?**
  _Cohesion score 0.05823068309070549 - nodes in this community are weakly interconnected._
- **Should `app.py` be split into smaller, more focused modules?**
  _Cohesion score 0.1422924901185771 - nodes in this community are weakly interconnected._