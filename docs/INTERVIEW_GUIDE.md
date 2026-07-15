# Interview Guide

Use this document to prepare a concise explanation of the Automotive Wiring Automation project and to rebuild its important concepts from memory.

## Two-Minute Project Explanation

Automotive wiring engineering relies on large workbooks containing circuits, connectors, harness variants, option logic, and change records. Manual comparison and transformation of these files is slow and creates opportunities for copy/paste and formula errors.

I built a Python and Streamlit application that converts those workflows into deterministic file-in/file-out pipelines. Separate domain engines validate workbook schemas, normalize inconsistent values, evaluate sales-code expressions, compare old and new DTx reports, generate splice configurations, enrich SECR workbooks, and export formatted Excel reports.

The processing layer uses Pandas, OpenPyXL, XlsxWriter, and SymPy. The Streamlit interface orchestrates the engines without embedding the business logic in the UI. Pytest tests cover expression parsing, workbook comparison, configuration generation, and output formatting.

The main value is repeatability: the same validated logic can process many configurations while generating traceable outputs. Quantified time and defect-reduction metrics are being collected from comparable manual and automated runs.

## Architecture Walkthrough

1. A user selects a workflow in the Streamlit interface.
2. The application receives one or more uploaded workbooks as bytes.
3. A domain engine validates required sheets and columns.
4. Values are normalized before matching or comparison.
5. Domain rules generate configurations, differences, or enriched records.
6. Output workbooks and summary data are returned to the UI.
7. The user reviews and downloads the generated artifacts.

The processing engines remain separate from the user interface so they can be tested without starting Streamlit.

## Important Design Decisions

### File-in/file-out processing

Why: Uploaded files can be validated and transformed without requiring a persistent database.

Tradeoff: Large workbooks consume memory, so future versions may need streaming or chunked processing.

### Schema validation before transformation

Why: Missing columns should produce an explicit error instead of a partially incorrect report.

Tradeoff: Input formats must be mapped carefully when source systems change column names.

### Deterministic normalization

Why: Excel frequently represents equivalent identifiers as strings, integers, floats, empty cells, or whitespace-padded values.

Tradeoff: Normalization rules must preserve identifiers where leading zeros or formatting carry meaning.

### Business logic outside Streamlit

Why: Domain functions can be unit-tested, reused, and reasoned about independently.

Tradeoff: The UI must translate exceptions and metadata into useful user feedback.

### Boolean expression parsing and simplification

Why: Harness applicability depends on combinations of sales codes, exclusions, and observed vehicle configurations.

Tradeoff: Simplified expressions must always be validated against every known configuration to prevent false matches.

## Technical Challenges

- Detecting workbook headers when reports contain introductory rows or inconsistent sheet names.
- Comparing records when the same key appears more than once.
- Preserving Excel formatting while generating new reports.
- Simplifying option expressions without changing their behavior.
- Handling empty cells, numeric identifiers, and mixed Excel types consistently.
- Keeping workflow-specific rules isolated while sharing normalization utilities.

## Testing Strategy

The suite should cover:
- Valid and invalid sales-code expressions.
- Expression equivalence across observed harness configurations.
- Added, removed, modified, and unchanged DTx records.
- Duplicate keys and collapsed values.
- Missing sheets and required columns.
- Output workbook sheet names, headers, colors, and cell formatting.
- Feedback serialization and configuration fallbacks.
- Fixture-dependent integrations through explicit skip conditions when external samples are unavailable.

GitHub Actions installs dependencies in a clean Python environment and runs the complete pytest suite.

## Likely Interview Questions

### Why use Pandas instead of processing cells directly?

Pandas provides reliable filtering, grouping, joins, normalization, and comparison operations. OpenPyXL is then used when workbook styling or cell-level manipulation is required.

### How do you prevent incorrect automated output?

Validate schemas early, normalize input deterministically, test pure processing functions, validate generated expressions against all observed configurations, and return summaries that engineers can review.

### How would you scale this system?

Separate the UI from a service layer, store uploaded files in object storage, process long jobs asynchronously, add structured logging, version input schemas, and capture workflow metrics.

### What would you refactor next?

Introduce shared schema models, stronger typing for workflow results, property-based tests for expression logic, smaller UI components, and centralized configuration.

### What was the hardest algorithmic problem?

Generating and simplifying sales-code expressions while guaranteeing that the resulting expression selects exactly the intended harness configurations.

### Why Streamlit?

It enabled rapid delivery of an internal engineering interface while keeping the core Python processing code reusable. For broader deployment, the same engines could sit behind an API and a separate frontend.

### How is this related to AI or ML engineering?

It demonstrates the engineering foundation required around ML systems: data validation, reproducible transformations, testing, user workflows, domain modeling, and deployment. A future ML component could prioritize risky changes, but deterministic rules remain appropriate for calculations that require exact traceability.

## Practice Exercises

1. Reimplement the value-normalization function without viewing the source.
2. Explain the sales-expression parser using a small expression and postfix notation.
3. Design a schema-validation layer for a newly introduced workbook version.
4. Write a test for a connector that exists only in the new report.
5. Explain how you would process a workbook too large for memory.
6. Sketch an API endpoint that accepts two workbooks and returns a comparison report.
7. Identify which parts require deterministic rules and which might benefit from ML.

## STAR Story Outline

Situation: Wiring analysis depended on fragmented spreadsheets and repeated manual reconciliation.

Task: Create a repeatable tool that could process domain-specific reports while preserving traceability.

Action: Separated workflow engines from the UI, implemented schema validation and normalization, automated comparison and workbook generation, and added unit tests around the highest-risk logic.

Result: The application is actively used for engineering workflows. Baseline and automated timing, throughput, and defect metrics are being collected before quantified claims are published.

## Before an Interview

- Run the application from a clean environment.
- Execute pytest and review any skipped integration tests.
- Rehearse the two-minute explanation.
- Prepare one concrete debugging story.
- Prepare one example of a design tradeoff.
- Know which parts you wrote and which libraries you selected.
- Bring measured results once the metrics collection is complete.
