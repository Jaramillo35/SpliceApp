# PostgreSQL Setup for the SECR Database on Streamlit Cloud

**Date:** 2026-07-21 · Companion to `SECR_DATABASE_DESIGN.md`

---

## 1. The one thing to understand first

The PostgreSQL you installed on your computer **cannot be reached by Streamlit Cloud**. Streamlit Cloud runs your app on their servers; your laptop's Postgres is behind your home/work network and is offline whenever the laptop sleeps. So the split is:

- **Local Postgres (what you installed)** → use it for development and testing on your machine.
- **Hosted Postgres (free tier)** → what the deployed Streamlit Cloud app actually connects to. Use **Supabase** or **Neon** — both have free tiers that are plenty for this.

Same schema, same code — only the connection string differs.

---

## 2. Local Postgres (development)

Open a terminal (or pgAdmin's Query Tool) and create the database:

```bash
createdb secr_db          # if createdb isn't found: /Library/PostgreSQL/<ver>/bin/createdb on macOS installers
psql -d secr_db -f Splice/scripts/postgres_schema.sql
```

Verify: `psql -d secr_db -c "\dt"` should list `secr`, `secr_affected_item`, `secr_dtcr`, `secr_dtcr_circuit`.

Your local connection string is:

```
postgresql://postgres:<your-password>@localhost:5432/secr_db
```

## 3. Hosted Postgres (what Streamlit Cloud uses)

1. Create a free project at **supabase.com** (or **neon.tech**). Pick a region close to you.
2. In the project dashboard find the **connection string** (Supabase: Settings → Database → Connection string → URI; use the **pooler/"Transaction"** string on port 6543 for Streamlit Cloud). It looks like:
   `postgresql://postgres.xxxx:<password>@aws-0-us-east-1.pooler.supabase.com:6543/postgres`
3. Open the provider's **SQL editor**, paste the contents of `Splice/scripts/postgres_schema.sql`, run it once.

## 4. Secrets — never put the URL in code or git

**Local:** create `Splice/.streamlit/secrets.toml` (already gitignored):

```toml
[postgres]
url = "postgresql://postgres:<password>@localhost:5432/secr_db"
```

**Streamlit Cloud:** app → **Settings → Secrets** → paste the same TOML block, but with the **hosted** URL. Save; the app restarts with it.

The app reads it as `st.secrets["postgres"]["url"]`.

## 5. Dependencies

Add one line to `Splice/requirements.txt`:

```
psycopg2-binary
```

## 6. Code change required in `secr_db.py`

`secr_db.py` currently speaks SQLite only. To support both backends it needs a small adapter (~1–2 hours of work; this is the next implementation task):

- On import, check `st.secrets` for `postgres.url` → connect with `psycopg2`; otherwise fall back to the local SQLite file (so nothing breaks for local use without Postgres).
- Placeholders: SQLite uses `?`, Postgres uses `%s` — route queries through a tiny helper that swaps them.
- `INSERT ... RETURNING id` replaces `cursor.lastrowid`.
- Drop the `PRAGMA` calls on the Postgres path (WAL/foreign-keys are defaults there).

The schema itself is already portable — `postgres_schema.sql` is a direct translation (only `INTEGER PRIMARY KEY` → `BIGSERIAL PRIMARY KEY`).

## 7. Deployment checklist

1. Hosted DB created, schema run, connection string tested (`psql "<url>" -c "select 1"`).
2. `psycopg2-binary` in requirements.txt.
3. Secrets set in Streamlit Cloud (and locally in `.streamlit/secrets.toml`).
4. `secr_db.py` Postgres adapter implemented and tested locally against your installed Postgres.
5. Push to GitHub → Streamlit Cloud redeploys → generate a test SECR → confirm the row in the provider's table viewer.
6. Migrate existing SQLite data (if any) with the backfill script, pointed at the new DB.

**Backups:** Supabase/Neon free tiers keep automatic backups, but exporting monthly (`pg_dump "<url>" > secr_backup.sql`) costs nothing and is worth doing for release records.
