# SECR Database — Architecture, Requirements & Task Plan

**Date:** 2026-07-21 · **Target app:** `Splice/app.py` (Streamlit) · **DB:** SQLite

---

## 1. How Create SECR and Update SECR work today (as-is analysis)

### Create SECR (`app.py` ~line 1084, engine: `secr_engine.create_secr_bytes`)

1. User uploads a **DEF-to-DEF Compare** file (required) and optionally a **DTCR_Matching_Report** workbook.
2. MY / Program / Phase are auto-extracted from the DEF workbook (fallback: filename parts), and the user fills a form: Subject, Author, DRE, Change Requested By, Version, Phase Implemented, Pull Ahead, dates, SECR # Type (Miscellaneous → `M` prefix, Design Change → `D` prefix).
3. On **Generate SECR**, `create_secr_bytes()`:
   - Builds the SECR number: `{M|D}{MY2}{PROGRAM}{PHASE}_{sequence}` (e.g. `D28RUX1_1000`).
   - Loads `assets/SECR_TEMPLATE.xlsx`, copies all DEF sheets into it, fills Summary cells (`C10` MY, `C11` vehicle line, `F10` phase, `C12` harness family, `I2`/`C8` SECR #, `C7` subject, `I10-I12` people, `I3` version, `I4/I5` dates, `F11/F12`).
   - Scans copied `DEF_DEF_Summary`, `Connector`, `Circuit` sheets by their **Action** column and writes the affected-items blocks: connectors → `C21/C22`, circuits → `C25/C26/C27`, part numbers/symbols → `C30/C31/C32`.
4. If a DTCR_Matching_Report was uploaded, `_auto_enrich_secr_if_requested()` (uses `secr_enrichment_engine`) reads the SECR's harness family from `C12`, filters the DTCR↔harness-family mapping to that family, and writes **Reason for Change** (`C7`/`B17` area) and **DTCR #s** (`C14`) into the SECR.
5. Result bytes go into `st.session_state["secr_result_bytes"]` and the user downloads the .xlsx. **Nothing is persisted** — once the session ends, the record of what was generated is gone.

### Update SECR (`app.py` ~line 1290, engine: `secr_engine.update_secr_bytes`)

Same flow, but requires a **new DEF compare + old SECR baseline**. It rebuilds from the template, copies the old Summary values (except `C8/I2/I3/I4`), carries forward SE Comments on matching Connector/Circuit rows, appends a row to the version-history table (row 34+), then re-runs the affected-items processing. Also not persisted.

### The DTCR Matching Report (input to enrichment)

Sheet `DTCR_Harness_Family_Mapping`, one row per DTCR with columns:
`DTCR#`, `Device Transmittal`, `Extracted Device Control Number`, `Reason for change`, `Status`, `Match Method`, `Matched DTx Value`, `CNUM`, `Harness Family`.
This is the per-DTCR source of affected **devices** (Device Transmittal / Matched DTx Value) and **circuits** (CNUM).

**Gap being solved:** every generated SECR exists only as a downloaded Excel file. There is no searchable history, no way to know the next sequence number, which DTCRs are already covered by a SECR, or which SECRs touched a given circuit/device/PN.

---

## 2. Requirements

### Functional

- FR1: Every successful **Create SECR** run inserts a SECR record automatically (no extra user action).
- FR2: Every successful **Update SECR** run inserts a new SECR record linked to its baseline (revision chain), never overwriting history.
- FR3: Store per-SECR metadata: SECR #, version, filename, MY, program/vehicle line, phase, harness family, subject/reason, author, DRE, change requested by, change type, pull ahead, phase implemented, issue/re-issue dates, source DEF filename, whether it was DTCR-enriched.
- FR4: Store the affected items per SECR by action: devices/connectors (ADD/CHG/DELETE), circuits (ADD/CHG/DELETE), part numbers/symbols (ADD/CHG/DELETE) — as normalized rows, one item per row, not comma strings.
- FR5: Store the per-DTCR detail from the DTCR_Matching_Report used for enrichment: DTCR #, device transmittal, device control number, reason for change, status, match method, matched DTx value, CNUM (circuits), harness family — linked to the SECR it populated.
- FR6: Queryable: "all SECRs for 28 RU X1", "which SECRs include DTCR 50319", "which SECRs touched circuit A111 / device D2784J", "history chain of D50319A".
- FR7: A DB save failure must **not** break workbook generation — the user still gets their download; show a warning instead.
- FR8: Duplicate protection: same SECR # + version is upserted (re-clicking Generate doesn't create duplicate rows).
- FR9 (phase 2): A "SECR Database" page in the app to browse/search records and re-derive the next sequence number.
- FR10: Sequence ranges are reserved per program: `_1000`–`_1999` for **RU**, `_2000`–`_2999` for **DT** (extend the map as programs are added). `next_sequence()` must start from the program's base and never cross into another program's range.

### Non-functional

- NFR1: SQLite single file at `Splice/data/secr_database.db`; no server, no credentials. Add `data/*.db` to `.gitignore`.
- NFR2: WAL mode + busy timeout for concurrent Streamlit sessions.
- NFR3: Schema versioned via `PRAGMA user_version` with a tiny migration runner, so the schema can evolve.
- NFR4: All writes in a single transaction per SECR (record + items + DTCRs commit atomically).
- NFR5: Pure-stdlib `sqlite3` — no new dependencies.
- NFR6: If the app is ever deployed to Streamlit Cloud, the DB file is ephemeral there; plan a swap to Postgres (schema is portable) or a synced backup.

---

## 3. Architecture

```
app.py (Create SECR / Update SECR handlers)
    │  after create_secr_bytes()/update_secr_bytes() succeed
    ▼
secr_db.py  (new module — the only file that touches SQLite)
    ├─ init_db()                     schema create/migrate, WAL
    ├─ save_secr(record) -> secr_id  atomic insert/upsert
    ├─ record_from_workbook(bytes, meta, form, dtcr_df)  parse Summary cells
    └─ queries: list_secrs(), get_secr(), find_by_dtcr(), find_by_item(),
                next_sequence(my, program, phase, type)
    ▼
data/secr_database.db  (SQLite, WAL)
```

Integration is **two calls per button**: build the record (from the generated workbook bytes + form inputs + `dtcr_mapping_df` if enrichment ran), then `save_secr()` inside a `try/except` that only warns on failure (FR7). The engines (`secr_engine.py`, `secr_enrichment_engine.py`) stay untouched.

### Schema (DDL)

```sql
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS secr (
    id                   INTEGER PRIMARY KEY,
    secr_number          TEXT NOT NULL,            -- e.g. D50319A / D28RUX1_1000 (Summary I2)
    version              TEXT NOT NULL DEFAULT 'A',-- Summary I3
    filename             TEXT,                     -- generated .xlsx name
    action               TEXT NOT NULL CHECK (action IN ('create','update')),
    parent_secr_id       INTEGER REFERENCES secr(id),  -- baseline when action='update'
    model_year           TEXT,                     -- C10
    program              TEXT,                     -- C11 (vehicle line)
    phase                TEXT,                     -- F10 (iSpeed phase)
    harness_family       TEXT,                     -- C12 (e.g. IP)
    phase_implemented    TEXT,                     -- F11
    pull_ahead           TEXT,                     -- F12
    change_type          TEXT,                     -- Miscellaneous | Design Change
    subject              TEXT,                     -- C7
    secr_author          TEXT,                     -- I10
    design_release_engineer TEXT,                  -- I11
    change_requested_by  TEXT,                     -- I12
    original_issue_date  TEXT,                     -- I4
    reissue_date         TEXT,                     -- I5
    dtcr_numbers         TEXT,                     -- C14 raw text
    bulletin_numbers     TEXT,                     -- G14 raw text
    ref_secr             TEXT,                     -- C15
    source_def_filename  TEXT NOT NULL,
    enriched             INTEGER NOT NULL DEFAULT 0,
    created_at           TEXT NOT NULL DEFAULT (datetime('now')),
    created_by           TEXT,                     -- OS username / app user
    UNIQUE (secr_number, version)                  -- FR8 upsert key
);

-- FR4: normalized affected items (from Summary blocks / Connector+Circuit sheets)
CREATE TABLE IF NOT EXISTS secr_affected_item (
    id        INTEGER PRIMARY KEY,
    secr_id   INTEGER NOT NULL REFERENCES secr(id) ON DELETE CASCADE,
    category  TEXT NOT NULL CHECK (category IN ('device','circuit','part_number')),
    action    TEXT NOT NULL CHECK (action IN ('ADD','CHG','DELETE')),
    item      TEXT NOT NULL                        -- e.g. D2784J, A111, 'Symbols 447'
);

-- FR5: per-DTCR rows from the DTCR_Matching_Report used for enrichment
CREATE TABLE IF NOT EXISTS secr_dtcr (
    id                    INTEGER PRIMARY KEY,
    secr_id               INTEGER NOT NULL REFERENCES secr(id) ON DELETE CASCADE,
    dtcr_number           TEXT NOT NULL,
    device_transmittal    TEXT,                    -- affected device
    device_control_number TEXT,
    reason_for_change     TEXT,
    status                TEXT,                    -- Complete / Deleted / ...
    match_method          TEXT,
    matched_dtx_value     TEXT,
    cnum                  TEXT,                    -- affected circuits (raw)
    harness_family        TEXT
);

-- circuits exploded from CNUM so 'which SECR touched A111 via which DTCR' is one query
CREATE TABLE IF NOT EXISTS secr_dtcr_circuit (
    secr_dtcr_id INTEGER NOT NULL REFERENCES secr_dtcr(id) ON DELETE CASCADE,
    circuit      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_secr_lookup   ON secr (model_year, program, phase);
CREATE INDEX IF NOT EXISTS ix_item_lookup   ON secr_affected_item (item, category);
CREATE INDEX IF NOT EXISTS ix_dtcr_lookup   ON secr_dtcr (dtcr_number);
CREATE INDEX IF NOT EXISTS ix_dtcr_ckt      ON secr_dtcr_circuit (circuit);
```

### Data-capture notes

- Most fields come free from what the button handlers already hold: `meta` dict (`I2`, `C10`, `C11`, `F10`, `C12`, `filename`), the form inputs, and `dtcr_mapping_df`. Only the affected-items blocks need a re-read of the generated workbook's Summary (`C20-C22`, `C25-C27`, `C30-C32`) — split the comma strings into rows. Cleaner long-term option: have `_process_*_sheet()` return the lists instead of only writing cells.
- For **Update SECR**, resolve `parent_secr_id` by looking up the old SECR's `I2`/`C8` in the DB (nullable if the baseline predates the database).
- `next_sequence()` (for the `_1000` suffix) = `MAX` existing sequence for that MY/program/phase/type + 1 — replaces the hardcoded `sequence=1000` eventually.

---

## 4. Task plan

Work in this order; each task is independently testable.

**Task 1 — DB module skeleton** (~half day)
Create `Splice/secr_db.py`: connection helper (WAL, busy_timeout, foreign_keys ON), `init_db()` with the DDL above, `PRAGMA user_version` migration runner. Add `data/*.db` to `.gitignore`. Test: run `init_db()` twice, inspect with `sqlite3` CLI.

**Task 2 — Record builder** (~half day)
`record_from_workbook(secr_bytes, meta, form_inputs, dtcr_mapping_df, action, source_def_filename)`: open bytes with openpyxl (data_only), read Summary cells listed above, split affected-item comma strings, explode CNUM into circuits. Returns a plain dict. Test: feed it a real generated SECR (e.g. `SECR_28RU_X1_IP_D50319A_V1_05072026.xlsx`) and assert counts (4 added devices, 19 changed circuits, etc.).

**Task 3 — save_secr()** (~half day)
Single-transaction insert/upsert on `(secr_number, version)`; child rows replaced on upsert. Returns `secr_id`. Test: save same record twice → one row; verify cascades.

**Task 4 — Wire into Create SECR** (~half day)
In `app.py` after the result lands in session state (post-enrichment, ~line 1250): build record with `action='create'`, `enriched` flag, `dtcr_mapping_df` when present; call `save_secr()` in try/except → `st.warning` on failure, small `st.caption("Saved to SECR database (#id)")` on success. Test end-to-end in the running app.

**Task 5 — Wire into Update SECR** (~half day)
Same at ~line 1428 with `action='update'`; read old SECR's number from the uploaded baseline to resolve `parent_secr_id`. Test: create → update with the output → verify chain in DB.

**Task 6 — Query API + next_sequence** (~half day)
`list_secrs(filters)`, `get_secr(id)` (with items + DTCRs), `find_by_dtcr(n)`, `find_by_item(value)`, `next_sequence(...)`. Optionally switch the hardcoded `sequence=1000` to `next_sequence()`. Unit tests on a temp DB.

**Task 7 — "SECR Database" browser page** (~1 day)
New entry in the Choose Tool radio / `pages/`: filterable table (MY/program/phase/family/author/date), row expander showing affected items + DTCR detail + revision chain, CSV export. Search box for DTCR #, circuit, device, PN.

**Task 8 — Backfill script** (~half day, optional)
`scripts/backfill_secr_db.py`: point at a folder of previously generated SECR .xlsx files, run the Task-2 parser on each, insert with `action='create'`, `created_by='backfill'`. Seeds history so searches are useful on day one.

**Task 9 — Verification & docs** (~half day)
Pytest suite for tasks 1–6, README section (where the DB lives, how to back it up — copy the file), note the Streamlit-Cloud ephemerality caveat.

---

## 5. Risks / later

- **Deployment**: if the app moves off a local machine to Streamlit Cloud, swap SQLite for Postgres (Supabase/Neon) — schema and queries port directly; only the connection helper changes.
- **Multi-writer** on a shared network drive: SQLite over SMB is unreliable — keep the DB on a local disk or move to Postgres.
- **Excel edits after download**: the DB captures the SECR *as generated*. If engineers edit the workbook afterward, consider a future "Import SECR" upload to sync edits (reuses the Task-2 parser).
