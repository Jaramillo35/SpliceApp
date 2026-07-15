# Architecture

## Overview

The application is a Streamlit front-end that orchestrates domain engines for wiring workflows. Each engine is responsible for one bounded business process and returns deterministic outputs (primarily Excel artifacts).

```mermaid
flowchart TD
    A[User in Streamlit UI] --> B[app.py Router]
    B --> C[wiring_harness_processor.py]
    B --> D[dtx_compare_engine.py]
    B --> E[secr_engine.py]
    B --> F[secr_enrichment_engine.py]
    B --> G[vbom_streamlit_engine.py]
    B --> H[feedback_system.py]

    C --> O1[Splice Workbook Output]
    D --> O2[DTx Change Workbook Output]
    E --> O3[Generated SECR Workbook]
    F --> O4[Enriched SECR + DTCR Mapping]
    G --> O5[VBOM Matrix Outputs]
    H --> O6[data/tickets.json]
```

## Key Design Principles

- Single-responsibility engines: each module maps to one workflow.
- File-in / file-out processing: workflows are easy to test.
- Defensive parsing: validate required columns early.
- Repeatable outputs: deterministic workbook generation.
- CI guardrails: unit tests run on pull requests and pushes.

## Runtime Data Flow

1. User uploads workbook(s) in Streamlit.
2. app.py dispatches to the selected engine.
3. Engine validates schema and processes transformations.
4. Engine emits output bytes + metadata.
5. UI presents downloads and summary tables.
