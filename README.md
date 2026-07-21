# Automotive Wiring Automation

Automotive Wiring Automation is a Streamlit application that consolidates multiple wiring-engineering workflows into one repeatable, testable toolchain for automotive harness design and change management.

It currently supports:
- Splice generation from harness complexity and option logic.
- DTx old-versus-new comparison with change reporting and PreOrder generation.
- DTCR matching and SECR creation/enrichment.
- VBOM risk-matrix workflow orchestration.
- In-app structured feedback ticketing and usage metrics.

## Business Problem

Wiring engineering teams often run a fragmented process:
- Spreadsheets are manually transformed and reconciled by hand.
- DTx, DTCR, and SECR traceability is spread across separate tools and file versions.
- Hand-built formulas and copy/paste steps are error-prone and hard to audit.
- Turnaround time increases as part counts and harness variants grow.

This project addresses those pain points by standardizing data loading, rule evaluation, and workbook output generation in one application, with every engine built as a deterministic, file-in/file-out module that can be tested and automated independently of the UI.

## Project KPIs

Latest tracked runs and configured baselines show the following outcomes:

| KPI | Value |
|---|---:|
| Completed workflow runs | 4 |
| Failed workflow runs | 2 |
| Rows read | 14,291 |
| Rows processed | 14,267 |
| Circuits processed | 14,198 |
| Harness variants processed | 55 |
| Automatic validation errors | 1 |
| Automatic validation failures | 1 |
| Total automated processing time | 40.06 s |
| Configured baseline manual time | 190 min |
| Estimated time saved | 189.33 min |

Workflow breakdown:

| Workflow | Automated time | Rows processed | Rows read | Baseline minutes | Estimated time saved |
|---|---:|---:|---:|---:|---:|
| Splice Generation | 1.09 s | 27 | 8 | 30 | 29.98 min |
| DTx PreOrder Generation | 3.83 s | 43 | 86 | 60 | 59.94 min |
| DTx Compare Report | 31.61 s | 14,197 | 14,197 | 60 | 59.47 min |
| Create SECR | 3.54 s | n/a | n/a | 40 | 39.94 min |

These KPIs are generated from [data/impact_metrics.json](data/impact_metrics.json) and [data/impact_baselines.json](data/impact_baselines.json).

## Architecture

High-level architecture is documented in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

~~~mermaid
flowchart LR
    UI[Streamlit UI] --> SP[Splice Engine]
    UI --> DTX[DTx Compare Engine]
    UI --> SECR[SECR + DTCR Enrichment]
    UI --> VBOM[VBOM Engine]
    UI --> FB[Feedback Store]

    SP --> XLSX[(Excel Outputs)]
    DTX --> XLSX
    SECR --> XLSX
    VBOM --> XLSX
    FB --> JSON[(data/tickets.json)]
~~~

Each engine is a plain Python module with typed function signatures that take file paths or raw bytes in and return DataFrames, workbook bytes, or structured dicts out. The Streamlit pages (`pages/*.py`) are thin wrappers that upload a file, call one of these functions, and render the result — none of the business logic lives in the UI layer.

## Quick Start

1. Create a Python environment.
2. Install dependencies.
3. Launch Streamlit.

~~~bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m streamlit run app.py
~~~

For the shell launch script:

~~~bash
chmod +x run_app.sh
./run_app.sh
~~~

## Tests

Run unit tests locally:

~~~bash
pytest -q
~~~

GitHub Actions runs the same suite in a clean Python environment on pushes and pull requests.

## Metrics and Dashboard

The app records run metadata automatically and updates the dashboard from the same JSON metrics file used for the KPI table above.

The dashboard is available at [pages/3_Metrics_Dashboard.py](pages/3_Metrics_Dashboard.py) and highlights completed workflows, processing time, rows processed, unique sessions, and time-savings coverage once baseline values are present.

The metrics system is intentionally non-confidential: it does not store workbook contents, filenames, circuit names, company identifiers, ticket contents, raw IP addresses, or stack traces.

### Protected Metrics Dashboard

A protected view of the same page remains disabled until `METRICS_ADMIN_TOKEN` is configured.

### Limitation: Unique Users vs Sessions

Without authenticated identity, weekly unique users are approximated by weekly unique anonymous sessions.

Full data dictionary: [docs/METRICS.md](docs/METRICS.md)

## AI Agent Integration for Systems Engineers

Every workflow in this app is exposed as a pure Python function before it ever touches Streamlit, which means an AI agent (Claude, an internal MCP tool, a CI bot, or a scheduled script) can drive the same engines directly — no browser, no manual uploads — and hand a Systems Engineer a reviewed result instead of a blank form.

| Workflow | Engine module | Key entry points | What an agent can do with it |
|---|---|---|---|
| Splice Generation | `wiring_harness_processor.py` | `run_analysis()`, `run_analysis_from_option_df()`, `validate_generated_expression()`, `validate_results()`, `export_excel()` | Watch a drop folder for new Complexity/OptionPerCkt workbooks, run analysis automatically, and only surface a file to the engineer once validation passes — flagging failures instead of silently forwarding bad data. |
| DTx Compare | `dtx_compare_engine.py` | `generate_dtx_change_report()`, `launch_preorder_generation_tool()`, `compare_reports()` | Take a before/after pair of DTx exports, generate the change and PreOrder workbooks unattended, and draft a plain-English summary of what was added, removed, or modified for the engineer to approve. |
| SECR Creation & Enrichment | `secr_engine.py`, `secr_enrichment_engine.py` | `create_secr_bytes()`, `update_secr_bytes()`, `match_dtcr_to_harness_family()`, `update_secr_reason_for_change()`, `update_secr_dtcr_numbers()` | Match incoming DTCR records to the correct harness family and pre-fill "Reason for Change" and DTCR numbers on the SECR, so the engineer verifies a draft instead of transcribing it by hand. |
| VBOM Risk Matrix | `vbom_streamlit_engine.py` | `run_vbom_workflow()`, `format_workbook_output()` | Orchestrate the VBOM engine end-to-end on a schedule or on file arrival, and hand back a formatted workbook plus a risk summary. |
| Feedback & Metrics | `feedback_system.py`, `data/impact_metrics.json`, `data/tickets.json` | `FeedbackStore`, metrics JSON files | Read submitted tickets and run metrics to generate a weekly digest of what broke, what got faster, and what's still fragile — without exposing any workbook contents, since the metrics store is designed to be non-confidential. |

Practical integration patterns:

1. **Tool-per-function wrapping.** Register the entry points above as individual MCP or function-calling tools. A Systems Engineer can then ask an assistant to "diff these two DTx files and tell me what changed" or "draft a SECR update for harness X913 using these DTCR numbers," and the agent calls the engine directly rather than walking through the Streamlit UI.
2. **Unattended pre-processing.** Because every engine validates its own inputs (`validate_generated_expression`, `validate_can_splices`, `validate_enrichment_inputs`), an agent can run a batch of incoming workbooks overnight and only escalate the ones that fail validation, cutting the volume of manual review to genuine exceptions.
3. **Change-summary drafting.** `compare_reports()` and `build_modified_views()` already return structured added/removed/modified records; an agent can turn that structure into a short natural-language summary attached to the generated workbook, so the engineer opens a change description instead of a raw diff.
4. **Operational reporting.** The append-only JSON metrics and feedback stores are safe for an agent to read on a schedule and turn into a standup-style update (see the `engineering:standup` skill) without any risk of leaking proprietary harness data.
5. **Codebase Q&A.** The repository ships a `graphify-out/graph.json` index (see `.github/copilot-instructions.md`); an agent can query it directly for "where is X handled" or "how do these modules relate" questions instead of re-reading the full source tree.

Guardrails that apply to agent-driven runs exactly as they do to human ones: the optional iSpeed integration still requires a user's own pre-existing, separately authorized access (see below), and any generated artifact should be reviewed before it's treated as a substitute for engineering sign-off — the app accelerates drafting and validation, it does not replace the engineer's approval.

## Anonymized Sample Data

Sample fixtures are available in [samples/anonymized](samples/anonymized):
- feedback_tickets_sample.json
- dtcr_matching_sample.csv
- dtx_compare_summary_sample.csv

## Demonstration

A short text demonstration is available at [docs/DEMO.md](docs/DEMO.md).

## Interview Preparation

The project explanation, design decisions, technical challenges, and practice questions are documented in [docs/INTERVIEW_GUIDE.md](docs/INTERVIEW_GUIDE.md).

## Authorized Access and Usage

The optional iSpeed integration operates only for users who already have separately authorized access to the Stellantis iSpeed website. This project does not provide credentials, bypass authentication, or grant access to Stellantis systems. Users (and any agent acting on their behalf) are responsible for following their organization's access, data-handling, and automation policies.

## Commit Message Quality

Avoid non-descriptive commit messages such as "push" or "fix."

Use structured messages with intent and scope, for example:
- feat(dtx): add connector change summary worksheet
- fix(secr): guard empty DTCR upload in enrichment flow
- docs(readme): add architecture and metrics guidance
- test(ci): run pytest in a clean environment

Full guidance: [docs/COMMIT_MESSAGE_GUIDE.md](docs/COMMIT_MESSAGE_GUIDE.md)

## Confidentiality Notes

The repository avoids hard-coded local machine paths and includes anonymized sample data for public demonstrations. Review third-party inputs before publishing them to ensure that no proprietary workbook content is included.
