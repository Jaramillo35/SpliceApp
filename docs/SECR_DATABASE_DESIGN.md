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

- NFR1: SQLite single file at `data/secr_database.db` in source mode and
  `%LOCALAPPDATA%\SpliceApp\secr_database.db` in the Windows executable; no
  server or credentials.
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
data/secr_database.db  (source mode) / %LOCALAPPDATA%\SpliceApp\secr_database.db (Windows)
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

---

# Part II — Schema v2: the SECR Database MVP

**Date:** 2026-08-07 · Supersedes nothing in Part I; v2 is applied additively on top of it.

Part I built a *record of what was generated*. Part II makes the database the main
concept of the application: an engineer imports historical SECR files, searches them,
and reads the actual engineering change — what it was, which object it touched, and
what the value was before and after.

## 1. What v1 could not answer

`secr_affected_item` stores `(category, action, item)` — an identifier and a verb.
There was no old value, no new value, no field name, and no way to import a SECR that
this app did not generate. The questions the tool exists to answer ("what was the
previous value?", "which SECRs changed this connector's part number?") had no data
behind them.

## 2. Where the change data actually lives

Verified against 27 historical SECR workbooks:

| Sheet | Grain | How the old value is recovered |
|---|---|---|
| `Add_Remove_Report_Summary` | **two tables** — connectors, then circuits | paired `(Old)` columns |
| `Connector` | one row per FCA-CNUM | `DEF_Connector_PN(Old)`, `Suffix(Old)` |
| `Circuit` | one row per CKT NBR | paired `(Old)` column where one exists, otherwise the cell comment `"Old DEF :X350A|17"` on the yellow-filled cell |
| `DEF_DEF_Summary` | one row per DEF symbol | `Harness PN (Old)` |

Rules that were **measured, not assumed**:

- **Connector adds/deletes** live in `Add_Remove_Report_Summary`, which is a superset of
  the `Connector` sheet's add/delete rows in every file checked. The `Connector` sheet
  contributes its `CHG` / `COMP CHG` rows. Rows are unioned and deduped on
  `(action, CNUM)`, so a change is counted once but nothing is dropped if a file
  disagrees.
- **Circuit identity is `CKT NBR` + `CKT Suffix`** (`A937` + `F` → `A937F`) — that is what
  the generator writes into the Summary roll-up and what engineers search for.
- A `DELETE` and an `ADD` of the same CNUM in one SECR is how the workbooks express a
  connector part-number replacement; it is stored as a single derived `PN CHANGE`.
- Action vocabulary in the files is exactly `ADD`, `DELETE`, `CHG`, `COMP CHG`. Only
  `PN CHANGE` is derived, and it is the only invented term.
- Per-change DTCR attribution comes from the `SE Comment` column, which carries forms
  like `DTCR 49793`, `DTCR's 50315, 50317`, and `... per complexity. DTCR 50277`.

## 3. Schema additions (user_version 1 → 2)

```sql
CREATE TABLE secr_change (          -- one row per CHANGED FIELD
    id INTEGER PRIMARY KEY,
    secr_id INTEGER NOT NULL REFERENCES secr(id) ON DELETE CASCADE,
    object_type TEXT NOT NULL,      -- connector | circuit | part_number | harness
    object_id   TEXT NOT NULL,      -- FCA-CNUM | CKT NBR+Suffix | DEF Symbol
    action      TEXT NOT NULL,      -- ADD | DELETE | CHG | COMP CHG | PN CHANGE
    field       TEXT,               -- NULL for whole-object ADD/DELETE
    old_value   TEXT,
    new_value   TEXT,
    dtcr_number TEXT,
    harness_pn  TEXT,
    sales_code  TEXT,
    se_comment  TEXT,
    source_sheet TEXT NOT NULL,     -- provenance: exact sheet + row
    source_row   INTEGER NOT NULL
);

CREATE TABLE secr_source_file (     -- the original workbook, for traceability
    secr_id INTEGER PRIMARY KEY REFERENCES secr(id) ON DELETE CASCADE,
    filename TEXT NOT NULL, sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL, content BLOB,
    stored_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE secr_audit (           -- saved / replaced / import_skipped / deleted
    id INTEGER PRIMARY KEY, secr_number TEXT NOT NULL, version TEXT,
    event TEXT NOT NULL, detail TEXT,
    at TEXT NOT NULL DEFAULT (datetime('now','localtime')), by_user TEXT
);

ALTER TABLE secr ADD COLUMN import_origin  TEXT NOT NULL DEFAULT 'generated';
ALTER TABLE secr ADD COLUMN imported_at    TEXT;
ALTER TABLE secr ADD COLUMN source_sha256  TEXT;
ALTER TABLE secr ADD COLUMN parse_warnings TEXT;
```

The migration is additive and idempotent, and was verified against a copy of the real
`data/secr_database.db`: all 4 SECRs, 923 affected items, 13 DTCR rows and 40 DTCR
circuits survive unchanged, and `PRAGMA user_version` moves 1 → 2.

**Deliberately not normalized.** No `PROGRAM` / `MODEL_YEAR` / `HARNESS_FAMILY` /
`CIRCUIT` / `CONNECTOR` dimension tables. At this data volume they buy nothing — filter
dropdowns are `SELECT DISTINCT`, and inventing surrogate keys for values that are plain
strings in the source files adds joins without adding truth.

## 4. Modules

```
splice/secr/parse.py     workbook bytes -> ParsedSecr (metadata + ParsedChange rows)
splice/secr/db.py        the only module that opens SQLite; save/delete/search/audit
splice/secr/importer.py  many files -> ImportSummary (imported/duplicate/failed)
splice/secr/api.py       READ-ONLY query surface — the future assistant's tool set
ui/pages/secr_database.py  Streamlit UI: Browse / Import / Dashboard
```

`record_from_workbook()` now delegates to `parse.py`, so a SECR looks identical in the
database whether it was generated here or imported as a file.

## 5. Duplicate handling

Identity is `(secr_number, version)`; `secr_source_file.sha256` additionally identifies a
byte-identical re-import. `save_secr(..., on_conflict=...)` takes:

- `skip` — **the import default.** Keeps the stored record, returns its id, writes an
  `import_skipped` audit row. An import can never overwrite engineering history.
- `replace` — used by Create/Update SECR, where re-generating the same SECR # + version
  is intentional. Writes a `replaced` audit row.
- `error` — raises `DuplicateSecrError`.

## 6. Data-integrity rules

- Nothing is discarded silently. A file that cannot be parsed is reported with its
  reason; a change row whose changed field cannot be attributed is stored with
  `field = NULL` rather than dropped.
- Nothing is invented. An unrecoverable old value is `NULL`, never a guess.
- Every change row carries `source_sheet` + `source_row` back to the workbook.
- Summary roll-up entries with no backing change row raise a parse warning, surfaced in
  the detail view and the import report. (One real file, `..._BODY_RIGHT_D49957B_V2...`,
  lists circuit `R372` in its Summary that appears on no change sheet — a source-data
  inconsistency, now visible instead of hidden.)
- All writes are single-transaction; deletes cascade and are audited.

## 7. Known issues carried over from v1

- `secr_dtcr_circuit.circuit` is populated by splitting the **CNUM** column, so it holds
  connector numbers under a column named `circuit`. Left as-is (the data is preserved and
  `find_by_item()` still behaves as before); `secr_change` supersedes it for all new
  search paths. Worth fixing when that table next changes.
- `secr.version` defaults to `'A'`, but real workbooks store `'1'` in `Summary!I3`. Both
  forms coexist. Identity is still unambiguous because it is the pair, not the version
  alone.

## 8. Toward the local assistant

`splice/secr/api.py` exposes `READ_ONLY_TOOLS` — `search_secrs`, `get_secr_summary`,
`get_changes_by_secr/dtcr/harness/cnum/circuit`, `get_connector_changes`,
`get_program_summary`, `get_model_year_summary`, `get_database_summary`,
`get_revision_chain`. A future Ollama/Qwen assistant calls these and **nothing else**:
no arbitrary SQL, no write path. The deterministic result is the evidence; the model only
summarizes it.

---

# Part III — Generated SECR identity, numbering, naming and versioning

**Date:** 2026-08-07 · Applies **only** to SECRs generated from a DEF→DEF compare.
Imported historical SECRs keep the identifiers and filenames they arrived with and are
never renumbered or renamed.

## 1. Four separate concepts

| Concept | Value | Where it lives |
|---|---|---|
| **Identity** | `MY28 / X1 / 1000` | `scope_model_year`, `scope_phase`, `secr_sequence_number` |
| **SECR number** | `D28X1RU_1000` | `secr_number`, and `Summary!I2` / `C8` in the workbook |
| **Version** | `V1 → V2 → V3` | `version_number` (one row per version) |
| **Filename** | `SECR_IP_D28X1RU_1000_V1_05072026.xlsx` | `filename` — *derived*, never parsed back |

`MY28/X1/1000` and `MY28/X2/1000` are two different SECRs. The SECR number embeds the
model year and phase so the code stays unique even though the sequence restarts at 1000
in every scope.

Filename format: `SECR_<HARNESS>_<TYPE><MY><PHASE><PROGRAM>_<NUMBER>_V<VERSION>_<MMDDYYYY>`
— `D` = Design Change, `M` = Miscellaneous Change.

## 2. Metadata extraction — and one correction to the spec

Harness Family, Model Year, Phase and Program are read from the `DEF_DEF_Summary`
identifier lines, which carry both sides of the compare:

```
DEF_New (Identifier) := 2028 RU X1_A 05_07_26_09_25_34 IP  ID: 11430
DEF_Old (Identifier) := 2028 RU X0_A 05_06_26_08_43_41 IP  ID: 11184
```

The SECR is scoped to the **NEW** DEF — that is the state it describes.

> **A phase difference between OLD and NEW is the normal case, not a conflict.** Every
> real compare in the sample set runs across phases (`X0_A` vs `X1_A`); treating that as
> a blocking metadata conflict, as the original requirement described, would block every
> generation. It is reported as an informational note instead.

What *is* treated as a blocking conflict:

- Program, Model Year or Harness Family differing between OLD and NEW — that means the
  wrong pair of DEFs was compared.
- The DEF filename and the DEF_New identifier disagreeing about the harness family.
- Any of the four fields missing.

Nothing is guessed and no number is reserved while a conflict is unresolved. The engineer
picks only the **Change Type**.

## 3. Numbering

Sequences are scoped to `model_year + phase`, stored in their own table:

```sql
CREATE TABLE secr_sequence (
    model_year  TEXT NOT NULL,   -- normalized to 2 digits
    phase       TEXT NOT NULL,   -- normalized, revision letter dropped (X1_A -> X1)
    next_number INTEGER NOT NULL,
    PRIMARY KEY (model_year, phase)
);
```

`reserve_next_secr_number(model_year, phase)` runs `BEGIN IMMEDIATE` before reading, so
two simultaneous generations cannot receive the same number (covered by a threaded test).
`peek_next_secr_number()` previews without consuming — the form preview never burns a
number; it is reserved at confirmed generation.

The sequence is a stored counter rather than `MAX(secr_number) + 1` precisely so that
**deleting a SECR does not release its number**. Delete `MY28/X1/1005` and the next SECR
is still `1006`.

Identity uniqueness is enforced by a partial index, so imported SECRs (no sequence
number) are unaffected:

```sql
CREATE UNIQUE INDEX ux_secr_generated_identity
    ON secr (scope_model_year, scope_phase, secr_sequence_number, version)
    WHERE secr_sequence_number IS NOT NULL;
```

## 4. Versioning and the scope-change rule

Updating an existing generated SECR re-runs the same deterministic engine and compares
the new DEF's scope against the stored SECR:

- **Scope matches** → same number, `version_number + 1`, new filename with the new date.
  The previous version is a separate row with its own stored workbook and is never
  touched.
- **Scope changed** (Harness Family, Model Year, Phase or Program) → the update is
  **blocked**. `plan_secr_update()` comes back with `scope_changed = True` and a
  field-by-field table; `generate_secr_update()` raises `SecrScopeChanged`. There is no
  override in the MVP — the engineer creates a new SECR, which draws from the sequence of
  its *own* `MY + Phase` scope (1000 if that scope has never issued a number).

`MY28/X1/1000` is never silently converted into `MY28/X2/1000 V2`.

## 5. Modules

```
splice/secr/identity.py    metadata extraction, validation, comparison, numbers, filenames
splice/secr/generation.py  plan_new_secr / generate_new_secr
                           plan_secr_update / generate_secr_update
splice/secr/db.py          reserve_next_secr_number (transactional), peek, get_versions,
                           list_generated_secrs, list_sequences
```

The generation engine (`splice/secr/generate.py`) gained three **optional** parameters —
`secr_number_override`, `filename_override`, `summary_overrides` — all defaulting to
empty. Existing callers (the SECR Management page) are byte-for-byte unaffected. The SECR
Database workflow passes validated metadata through them, so the workbook's Summary
records the resolved scope instead of whatever the DEF filename happened to encode
positionally.

## 6. Origin

`import_origin` doubles as the spec's `origin_type` (`generated` / `imported`) rather than
adding a second column meaning the same thing. Automatic numbering, naming and versioning
apply only to `generated` records; the Update workflow refuses an imported SECR with a
clear message.

## 7. Traceability

Every generated version stores: the reserved number and its scope, the version, the
generation date, the generated filename, the OLD and NEW DEF identifier strings, the DEF
compare filename, per-field metadata provenance, the full change records, and a copy of
the generated workbook.

## 8. DTCR enrichment and DTCR → CNUM assignment

Both generation workflows accept an optional **DTCR Matching Report** (the workbook from
*SECR Management → 1 · DTCR Matching*). Supplying it runs
`splice.secr.numbering.auto_enrich_secr` — the same call the SECR Management page makes —
so the behaviour is identical:

- `Summary!B17` Reason for Change, `C14` DTCR #, `G14` Bulletin # are filled from the
  rows whose Status is *Complete* or *Draft* and whose Harness Family matches the SECR's
  `C12`.
- The per-DTCR rows for that family are stored in `secr_dtcr`.

On top of that, the database assigns each DTCR to the connector it was matched to:

```
DTCR Matching Report          secr_change
  DTCR#  CNUM                   object_type = 'connector'
  49754  SD401        ---->     object_id   = 'SD401'
  50319  SD401, D2996B          dtcr_number = '49754, 50319'
```

Rules (`assign_dtcrs_to_cnums`):

- Only `object_type = 'connector'` rows are assigned; a CNUM is a connector number.
- **A DTCR already parsed from the row's SE comment is never overwritten** — what the
  engineer wrote about that specific row outranks the report's heuristic CNUM match
  (`Match Method` is Device Name / Suffix / DCN). The assignment is still reported, with
  `source = "SE comment"`, so the engineer can see the report agreed or disagreed.
- When the report maps several DTCRs to one CNUM they are recorded together
  (`"49754, 50319"`) rather than one being chosen arbitrarily.
- A CNUM the report does not mention is left alone; nothing is invented.

Either way the SECR remains findable by any DTCR in the report, because `search_secrs`
also joins `secr_dtcr` — the row-level assignment sharpens *which change* a DTCR touched,
it is not the only path to the SECR.

Failure handling: enrichment can never cost the engineer the SECR. An unreadable or
mismatched report leaves the unenriched workbook generated and stored, with the reason as
a warning. A report that loads but has **no Complete/Draft rows for this harness family**
would otherwise enrich to silently empty cells, so that case raises its own warning
naming the family.

## 9. The Browse tab

Browse shows four things, in reading order:

```
Search  +  active-filter chips
SECRs count | Most affected harness families      (one row)
Program | Phase | Model Year | Harness           (dimension filters)
SECRs table    the SECRs in the database — select a row
Changes        the changes of the selected SECR
```

The harness chart doubles as the filter: one click narrows the count and the table, one
click on the chip clears it. The four dropdowns below it are the database's own
dimensions, populated from the values actually present so a filter can never select an
empty result. Harness appears in both places on purpose — the chart and the dropdown
write the same `harness_family` key, and the dropdown's index is derived from the filter
dict rather than held in widget state, so picking a bar updates the dropdown and vice
versa. Selecting a SECR is a click on its table row
(`st.dataframe(on_select="rerun", selection_mode="single-row")`), not a separate
dropdown. The richer per-facet charts (change type, object, CNUM, circuit, DTCR) live on
the **Dashboard** tab.

**Chart form.** The chart answers a magnitude question about nominal categories, so it is
a horizontal bar chart in a **single** colour — a value-ramp across nominal categories
would double-encode bar length as hue. Colour is spent on *selection state* instead: the
filtered harness keeps the accent hue and its siblings recede to grey, so no legend is
needed. Steps come from the validated palette (blue slot 1), chosen per theme because the
app renders on both a light and a dark surface. The accent/muted pair passes the
validator's CVD and normal-vision separation checks; the muted step is deliberately below
3:1 (a de-emphasis colour that competed with the accent would defeat the point) and
carries the required relief — every bar is direct-labelled and the same SECRs appear in
the table.

**A chart never filters itself.** Selecting `IP` narrows the count and the table, but the
harness chart keeps all its bars — otherwise it would collapse to one bar with no way to
switch. `change_facets()` computes each facet with every filter *except* the one that
facet drives.

**CNUM and circuit are separate filter keys** (`cnum`, `circuit`) even though both live in
`secr_change.object_id`. Sharing one key made the two Dashboard charts exclude each
other's selection, so picking a CNUM left the circuit chart full of bars beside a count
reading zero.

**One implementation note.** A Vega selection lives in Streamlit's widget state and is
replayed on every rerun, so acting on it unconditionally re-applies the filter on the
rerun the click itself triggered. `_apply_selection` compares against the last value seen
for that chart, which makes a click act exactly once. Vega's point selection *replaces*
on a plain click (deselecting needs shift), so clicking a selected bar does not clear it
— the ✕ chip is the one-click clear, and the caption says so.

## 10. Connections must close (Windows)

`splice/secr/db.py` exposes two connection helpers:

- `get_conn()` — raw connection, caller closes. Used only by
  `reserve_next_secr_number`, which needs its own `BEGIN IMMEDIATE`.
- `connect()` — **the one to use.** Commits on success, rolls back on error, and
  always closes.

The distinction matters. `with sqlite3.connect(...) as conn` manages the
*transaction*, not the connection: it leaves the file handle open. On macOS and
Linux that is invisible, because an open file can still be deleted. On Windows it
locks `secr_database.db` and its `-wal` / `-shm` sidecars, so backing up,
replacing or deleting the database while the app is running fails with
"the process cannot access the file because it is being used by another process".

This was caught by the first real Windows build: the frozen `--self-test` created
a probe database in a temp directory and the cleanup could not remove it. All 24
call sites now use `connect()`.

`test_operations_leave_no_open_file_handles` guards it portably — SQLite deletes
the WAL and shared-memory files when the last connection closes, so their absence
after a write/read cycle proves the handle was released. Reintroducing the leak
makes that test fail on macOS too.
