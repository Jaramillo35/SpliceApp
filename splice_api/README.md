# splice-api

FastAPI gateway over the Splice DTx/DTCR engines — the **versioned service boundary**
(ADR-0004). UIs and the SECR assistant call HTTP here instead of importing `splice`
internals. Engines are reused unchanged, so the byte-identical export contract (ADR-0005)
is preserved.

## Run

```bash
cd apps/Splice
pip install -r splice_api/requirements-api.txt      # first time
uvicorn splice_api.main:app --reload                # http://localhost:8000
```

Interactive OpenAPI docs: **http://localhost:8000/docs**

## Endpoints

| Method | Path | Body (multipart) | Returns |
|---|---|---|---|
| GET  | `/health` | — | liveness + version (JSON) |
| POST | `/dtx/compare` | `old`, `new`, `dtcr` | enhanced DTx compare workbook (`.xlsx`) |
| POST | `/dtx/compare/summary` | `old`, `new`, `dtcr` | `CompareSummary` (JSON) |
| POST | `/dtcr/match` | `old`, `new`, `dtcr` | DTCR matching workbook (`.xlsx`) |
| POST | `/preorder` | `old`, `new` | PreOrder generation workbook (`.xlsx`) |

Example:

```bash
curl -s -X POST http://localhost:8000/dtx/compare/summary \
  -F old=@OLD.xls -F new=@NEW.xls -F dtcr=@DTCR.xls | jq
```

## Tests

```bash
cd apps/Splice
python -m pytest tests/test_splice_api.py -q
```

Binary-endpoint tests use the real `data/Validatehere/` samples and skip when absent;
`/health` and validation tests run anywhere.
