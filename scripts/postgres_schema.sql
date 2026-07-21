-- SECR Database — PostgreSQL schema (portable translation of the SQLite DDL)
-- Run once: psql -d secr_db -f postgres_schema.sql   (or paste into Supabase/Neon SQL editor)

CREATE TABLE IF NOT EXISTS secr (
    id                   BIGSERIAL PRIMARY KEY,
    secr_number          TEXT NOT NULL,
    version              TEXT NOT NULL DEFAULT 'A',
    filename             TEXT,
    action               TEXT NOT NULL CHECK (action IN ('create','update')),
    parent_secr_id       BIGINT REFERENCES secr(id),
    model_year           TEXT,
    program              TEXT,
    phase                TEXT,
    harness_family       TEXT,
    phase_implemented    TEXT,
    pull_ahead           TEXT,
    change_type          TEXT,
    subject              TEXT,
    secr_author          TEXT,
    design_release_engineer TEXT,
    change_requested_by  TEXT,
    original_issue_date  TEXT,
    reissue_date         TEXT,
    dtcr_numbers         TEXT,
    bulletin_numbers     TEXT,
    ref_secr             TEXT,
    source_def_filename  TEXT,
    enriched             INTEGER NOT NULL DEFAULT 0,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by           TEXT,
    UNIQUE (secr_number, version)
);

CREATE TABLE IF NOT EXISTS secr_affected_item (
    id        BIGSERIAL PRIMARY KEY,
    secr_id   BIGINT NOT NULL REFERENCES secr(id) ON DELETE CASCADE,
    category  TEXT NOT NULL CHECK (category IN ('device','circuit','part_number')),
    action    TEXT NOT NULL CHECK (action IN ('ADD','CHG','DELETE')),
    item      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS secr_dtcr (
    id                    BIGSERIAL PRIMARY KEY,
    secr_id               BIGINT NOT NULL REFERENCES secr(id) ON DELETE CASCADE,
    dtcr_number           TEXT NOT NULL,
    device_transmittal    TEXT,
    device_control_number TEXT,
    reason_for_change     TEXT,
    status                TEXT,
    match_method          TEXT,
    matched_dtx_value     TEXT,
    cnum                  TEXT,
    harness_family        TEXT
);

CREATE TABLE IF NOT EXISTS secr_dtcr_circuit (
    secr_dtcr_id BIGINT NOT NULL REFERENCES secr_dtcr(id) ON DELETE CASCADE,
    circuit      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_secr_lookup ON secr (model_year, program, phase);
CREATE INDEX IF NOT EXISTS ix_item_lookup ON secr_affected_item (item, category);
CREATE INDEX IF NOT EXISTS ix_dtcr_lookup ON secr_dtcr (dtcr_number);
CREATE INDEX IF NOT EXISTS ix_dtcr_ckt   ON secr_dtcr_circuit (circuit);
