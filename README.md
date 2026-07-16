# Automotive Wiring Automation

Automotive Wiring Automation is a Streamlit application that consolidates multiple wiring-engineering workflows into one repeatable, testable toolchain.

It currently supports:
- Splice generation from harness complexity and option logic.
- DTx old-versus-new comparison with change reporting.
- DTCR matching and SECR enrichment.
- VBOM risk-matrix workflow orchestration.
- In-app structured feedback ticketing.

## Business Problem

Wiring engineering teams often run a fragmented process:
- Spreadsheets are manually transformed and reconciled.
- DTx, DTCR, and SECR traceability is spread across separate tools.
- Hand-built formulas and copy/paste steps are error-prone.
- Turnaround time increases when part counts and harness variants grow.

This project addresses those pain points by standardizing data loading, rule evaluation, and workbook output generation in one application.

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

The dashboard is available at [Splice/pages/3_Metrics_Dashboard.py](pages/3_Metrics_Dashboard.py) and highlights completed workflows, processing time, rows processed, unique sessions, and time-savings coverage once baseline values are present.

The metrics system is intentionally non-confidential: it does not store workbook contents, filenames, circuit names, company identifiers, ticket contents, raw IP addresses, or stack traces.

### Protected Metrics Dashboard

A protected Streamlit page is available at [Splice/pages/3_Metrics_Dashboard.py](pages/3_Metrics_Dashboard.py). It remains disabled until METRICS_ADMIN_TOKEN is configured.

### Limitation: Unique Users vs Sessions

Without authenticated identity, weekly unique users are approximated by weekly unique anonymous sessions.

Full data dictionary: [docs/METRICS.md](docs/METRICS.md)

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

The optional iSpeed integration operates only for users who already have separately authorized access to the Stellantis iSpeed website. This project does not provide credentials, bypass authentication, or grant access to Stellantis systems. Users are responsible for following their organization's access, data-handling, and automation policies.

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
