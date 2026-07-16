# Graph Report - Splice  (2026-07-15)

## Corpus Check
- 45 files · ~43,396 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 592 nodes · 1284 edges · 20 communities (13 shown, 7 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 31 edges (avg confidence: 0.65)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `ca8575b1`
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

## God Nodes (most connected - your core abstractions)
1. `MetricsTracker` - 29 edges
2. `RunSetupDialog` - 27 edges
3. `_run_analysis_core()` - 24 edges
4. `SalesCodeReviewDialog` - 23 edges
5. `JsonMetricsStorage` - 21 edges
6. `main()` - 20 edges
7. `parse_sales_code_expression()` - 18 edges
8. `generate_preorder_generation_workbook()` - 16 edges
9. `FeedbackStore` - 16 edges
10. `_auto_enrich_secr_if_requested()` - 14 edges

## Surprising Connections (you probably didn't know these)
- `InMemoryStorage` --uses--> `NoopMetricsStorage`  [INFERRED]
  tests/test_metrics_tracker.py → metrics/storage.py
- `test_submit_ticket_and_sync_invokes_github_sync()` --calls--> `FeedbackStore`  [EXTRACTED]
  tests/test_feedback_system.py → feedback_system.py
- `test_submit_ticket_persists_and_exports()` --calls--> `FeedbackStore`  [EXTRACTED]
  tests/test_feedback_system.py → feedback_system.py
- `test_to_minutes_handles_null_and_zero()` --calls--> `to_minutes()`  [EXTRACTED]
  tests/test_metrics_calculations.py → metrics/calculations.py
- `test_manual_touchpoints_eliminated_bounds_at_zero()` --calls--> `manual_touchpoints_eliminated()`  [EXTRACTED]
  tests/test_metrics_calculations.py → metrics/calculations.py

## Import Cycles
- None detected.

## Communities (20 total, 7 thin omitted)

### Community 0 - "wiring_harness_processor.py"
Cohesion: 0.06
Nodes (95): ExcelFile, test_501_only_expression_matches_all_harnesses(), test_candidate_codes_for_configuration_prefers_endpoint_scope(), test_generate_sales_code_expression_can_drop_standard_501(), test_generate_sales_code_expression_reduces_against_observed_harnesses(), test_generate_splices_reuses_shared_always_present_anchor_for_same_circuit(), test_harmonize_shared_splice_trunk_rows_applies_one_sales_code_to_shared_trunk(), test_parse_sales_code_expression_treats_501_as_always_present() (+87 more)

### Community 1 - "app.py"
Cohesion: 0.05
Nodes (74): _auto_enrich_secr_if_requested(), DataFrame, create_secr_counts(), dtcr_matching_counts(), dtx_compare_counts(), dtx_preorder_counts(), Any, DataFrame (+66 more)

### Community 2 - "MetricsTracker"
Cohesion: 0.07
Nodes (29): BaseException, clamp_optional_count(), manual_touchpoints_eliminated(), time_saved_minutes(), time_savings_percentage(), to_minutes(), render_metrics_dashboard(), _categorize_failure() (+21 more)

### Community 3 - "Any"
Cohesion: 0.08
Nodes (19): build_metrics_storage(), _get_config_value(), _get_streamlit_secret(), JsonMetricsStorage, _mean_or_none(), _median_or_none(), MetricsStorage, NoopMetricsStorage (+11 more)

### Community 4 - "main_app.py"
Cohesion: 0.07
Nodes (52): apply_tie_break_overrides(), ask_my_and_program(), ask_output_folder(), ask_save_folder(), build_outputs(), build_salescode_diff(), build_salescode_statistics(), _build_short_sheet_name() (+44 more)

### Community 5 - "Automotive Wiring Automation"
Cohesion: 0.04
Nodes (42): Architecture, Key Design Principles, Overview, Runtime Data Flow, Anti-patterns, Commit Message Guide, Good examples, Optional body template (+34 more)

### Community 6 - "dtx_compare_engine.py"
Cohesion: 0.13
Nodes (38): Counter, _apply_preorder_workbook_styles(), _build_connector_grouped_frame(), build_dashboard_sheet(), build_modified_views(), _build_output_file_name(), build_output_filename(), _collapse_to_unique_connector_values() (+30 more)

### Community 8 - "RunSetupDialog"
Cohesion: 0.15
Nodes (4): _parse_drop_files(), Startup window for MY/Program and input file selection., Parse tkdnd payload into local file paths (supports macOS file:// URIs)., RunSetupDialog

### Community 9 - "Interview Guide"
Cohesion: 0.09
Nodes (22): Architecture Walkthrough, Before an Interview, Boolean expression parsing and simplification, Business logic outside Streamlit, Deterministic normalization, File-in/file-out processing, How do you prevent incorrect automated output?, How is this related to AI or ML engineering? (+14 more)

### Community 10 - "FeedbackStore"
Cohesion: 0.20
Nodes (11): FeedbackStore, _get_config_value(), get_feedback_area_options(), _get_streamlit_secret(), Any, PathLike, render_feedback_widget(), test_feedback_area_options_include_site_workflows() (+3 more)

### Community 11 - "run_vbom_workflow"
Cohesion: 0.22
Nodes (13): DummyUpload, test_build_short_sheet_name_strips_program_and_phase_tokens(), test_load_vbom_module_succeeds_without_tkinter(), test_run_vbom_workflow_creates_expected_outputs(), _build_short_sheet_name(), format_workbook_output(), _load_vbom_module(), Path (+5 more)

### Community 12 - "secr_engine.py"
Cohesion: 0.29
Nodes (11): _copy_cell_style(), _copy_sheet(), create_secr_bytes(), _find_action_col(), _process_circuit_sheet(), _process_connector_sheet(), _process_def_def_summary(), Any (+3 more)

### Community 14 - "vercel.json"
Cohesion: 0.50
Nodes (3): builds, routes, version

## Knowledge Gaps
- **65 isolated node(s):** `WorkflowRunRecord`, `WorkflowFeedbackRecord`, `run_app.sh script`, `version`, `builds` (+60 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `_build_vin_matrix_from_buildspec()` connect `main_app.py` to `dtx_compare_engine.py`?**
  _High betweenness centrality (0.127) - this node is a cross-community bridge._
- **Why does `load_dataframe()` connect `main_app.py` to `dtx_compare_engine.py`?**
  _High betweenness centrality (0.116) - this node is a cross-community bridge._
- **Why does `MetricsTracker` connect `MetricsTracker` to `app.py`, `Any`?**
  _High betweenness centrality (0.094) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `MetricsTracker` (e.g. with `MetricsStorage` and `InMemoryStorage`) actually correct?**
  _`MetricsTracker` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `WorkflowRunRecord`, `WorkflowFeedbackRecord`, `run_app.sh script` to the rest of the system?**
  _65 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `wiring_harness_processor.py` be split into smaller, more focused modules?**
  _Cohesion score 0.05558728345707215 - nodes in this community are weakly interconnected._
- **Should `app.py` be split into smaller, more focused modules?**
  _Cohesion score 0.05339506172839506 - nodes in this community are weakly interconnected._