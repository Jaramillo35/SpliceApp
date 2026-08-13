# Automotive Wiring Automation

Automotive Wiring Automation is a Streamlit application that consolidates multiple wiring-engineering workflows into one repeatable, testable toolchain for automotive harness design and change management.

It currently supports:
- Splice generation from harness complexity and option logic.
- DTx old-versus-new comparison with change reporting and PreOrder generation.
- DTCR matching and SECR creation/enrichment.
- VBOM risk-matrix workflow orchestration.
- In-app structured feedback ticketing.

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

    SECR --> DB[(SECR Database)]
    IMP[Bulk SECR import] --> DB
    DB --> BROWSE[SECR Database page]
~~~

Each engine is a plain Python module with typed function signatures that take file paths or raw bytes in and return DataFrames, workbook bytes, or structured dicts out. The Streamlit pages (`pages/*.py`) are thin wrappers that upload a file, call one of these functions, and render the result — none of the business logic lives in the UI layer.

### SECR Database

The **SECR Database** page is the searchable history of every SECR — generated here or
imported from an existing file. It answers the questions engineers otherwise open a
folder of spreadsheets to answer: what changed, on which circuit or connector, under
which DTCR, and what the value was before and after.

| Module | Responsibility |
|---|---|
| `splice/secr/parse.py` | SECR workbook → metadata + one record per changed field |
| `splice/secr/identity.py` | generated-SECR identity: metadata extraction, numbering, filenames |
| `splice/secr/generation.py` | Create New SECR / Update Existing SECR workflows |
| `splice/secr/db.py` | the only module that opens SQLite (save, delete, search, sequences, audit) |
| `splice/secr/importer.py` | bulk import; reports every file as imported / duplicate / failed |
| `splice/secr/api.py` | read-only query surface — also the future local-assistant tool set |
| `ui/pages/secr_database.py` | Browse · Create · Update · Import · Dashboard (thin UI, no SQL) |

**Generated SECRs** are numbered per `Model Year + Phase`, each scope starting at 1000, and
named `SECR_IP_D28X1RU_1000_V1_05072026.xlsx` from structured metadata read out of the DEF
compare. Updating one keeps its number and advances the version; a change of Harness
Family, Model Year, Phase or Program blocks the update and points the engineer at a new
SECR. Imported historical SECRs are never renumbered or renamed.

The database is a single SQLite file at `data/secr_database.db`, overridable with
`SPLICE_SECR_DB_PATH`. Back it up by copying that file. Schema design, the measured
parsing rules, duplicate handling and known data caveats are in
[docs/SECR_DATABASE_DESIGN.md](docs/SECR_DATABASE_DESIGN.md).

Creating or updating a SECR saves it to the database automatically, with its change
records and a copy of the workbook — no export-and-re-import step. Bulk import defaults
to **skipping** duplicates so it can never overwrite history that is already stored.

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

## Verification

Run the automated regression suite and production-source checks before exercising
the affected workflow against known-good engineering inputs:

~~~bash
PYTHONPATH=. pytest -q
python scripts/validate_production.py
~~~

Because every engine in `splice/` is Streamlit-independent, an area can also be
driven directly from a Python shell (for example
`from splice.dtx_compare import generate_dtx_change_report`) to check its output
without going through the UI.

## Windows Production Distribution

The packaged application binds only to `127.0.0.1`. Runtime feedback and SQLite
data are stored in `%LOCALAPPDATA%\SpliceApp`, so upgrades can replace the
application directory without overwriting user data. See
[packaging/windows/README_WINDOWS_INSTALL.md](packaging/windows/README_WINDOWS_INSTALL.md)
and [docs/PRODUCTION_READINESS.md](docs/PRODUCTION_READINESS.md).

## AI Agent Integration for Systems Engineers

Every workflow in this app is exposed as a pure Python function before it ever touches Streamlit, which means an AI agent (Claude, an internal MCP tool, a CI bot, or a scheduled script) can drive the same engines directly — no browser, no manual uploads — and hand a Systems Engineer a reviewed result instead of a blank form.

| Workflow | Engine module | Key entry points | What an agent can do with it |
|---|---|---|---|
| Splice Generation | `splice/splice_gen/` | `run_analysis()`, `run_analysis_from_option_df()`, `validate_generated_expression()`, `validate_results()`, `export_excel()` | Watch a drop folder for new Complexity/OptionPerCkt workbooks, run analysis automatically, and only surface a file to the engineer once validation passes — flagging failures instead of silently forwarding bad data. |
| DTx Compare | `splice/dtx_compare/` | `generate_dtx_change_report()`, `launch_preorder_generation_tool()`, `compare_reports()` | Take a before/after pair of DTx exports, generate the change and PreOrder workbooks unattended, and draft a plain-English summary of what was added, removed, or modified for the engineer to approve. |
| SECR Creation & Enrichment | `splice/secr/` (+ `splice/dtcr/`) | `create_secr_bytes()`, `update_secr_bytes()`, `match_dtcr_to_harness_family()`, `update_secr_reason_for_change()`, `update_secr_dtcr_numbers()` | Match incoming DTCR records to the correct harness family and pre-fill "Reason for Change" and DTCR numbers on the SECR, so the engineer verifies a draft instead of transcribing it by hand. |
| VBOM Risk Matrix | `splice/vbom/` | `run_vbom_workflow()`, `format_workbook_output()` | Orchestrate the VBOM engine end-to-end on a schedule or on file arrival, and hand back a formatted workbook plus a risk summary. |
| Feedback | `feedback_system.py` | `FeedbackStore` | Read submitted local tickets and generate a digest of what broke and what should improve without exposing uploaded workbook contents. |

Practical integration patterns:

1. **Tool-per-function wrapping.** Register the entry points above as individual MCP or function-calling tools. A Systems Engineer can then ask an assistant to "diff these two DTx files and tell me what changed" or "draft a SECR update for harness X913 using these DTCR numbers," and the agent calls the engine directly rather than walking through the Streamlit UI.
2. **Unattended pre-processing.** Because every engine validates its own inputs (`validate_generated_expression`, `validate_can_splices`, `validate_enrichment_inputs`), an agent can run a batch of incoming workbooks overnight and only escalate the ones that fail validation, cutting the volume of manual review to genuine exceptions.
3. **Change-summary drafting.** `compare_reports()` and `build_modified_views()` already return structured added/removed/modified records; an agent can turn that structure into a short natural-language summary attached to the generated workbook, so the engineer opens a change description instead of a raw diff.
4. **Operational reporting.** The local feedback store can be read on a schedule and turned into a standup-style issue summary without exposing uploaded workbook contents.
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
