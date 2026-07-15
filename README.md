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

## Metrics to Collect

The application is in active use. The following metrics will be collected before publishing quantified impact claims:
- Baseline engineering hours per workflow before automation.
- Automated processing time for the same workflow.
- Number of workbook rows, circuits, and harness variants processed per run.
- Number of manual touchpoints eliminated.
- Number of validation or spreadsheet-logic errors detected before release.
- Weekly users and completed workflows.

A quantified time-savings percentage will be reported after comparable baseline and automated runs are recorded.

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
