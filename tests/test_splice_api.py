"""Contract tests for splice-api — the FastAPI boundary over the DTx/DTCR engines.

Binary-producing endpoints are exercised against the real Validatehere samples (skipped when
absent); health + validation behaviour run everywhere.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from splice_api.main import app

client = TestClient(app)

_D = Path("/Users/martinjaramillo/Downloads/Development/data/Validatehere")
FILES = {
    "old": _D / "28RU_X1_DetailedDTxCircuitsReport_4_22_26 (31) 3.xls",
    "new": _D / "DetailedDTxCircuitsReport (28_RU_X2) (2) 1.xls",
    "dtcr": _D / "DTCRReport (1).xls",
}
needs_files = pytest.mark.skipif(
    not all(p.exists() for p in FILES.values()), reason="real DTx/DTCR sample files absent")

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _uploads(keys):
    return {k: (FILES[k].name, FILES[k].read_bytes(), "application/vnd.ms-excel") for k in keys}


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["service"] == "splice-api" and body["version"]


def test_missing_required_file_is_422():
    r = client.post("/dtx/compare", files=_uploads(["old", "new"]))   # omit the required DTCR
    assert r.status_code == 422


@needs_files
def test_dtx_compare_returns_xlsx():
    r = client.post("/dtx/compare", files=_uploads(["old", "new", "dtcr"]))
    assert r.status_code == 200
    assert r.headers["content-type"] == XLSX
    assert r.headers.get("x-output-filename", "").endswith(".xlsx")
    assert r.content[:2] == b"PK"                                     # .xlsx is a zip container


@needs_files
def test_dtx_compare_summary_json():
    r = client.post("/dtx/compare/summary", files=_uploads(["old", "new", "dtcr"]))
    assert r.status_code == 200
    b = r.json()
    assert b["dtcr_total"] > 0 and 0 <= b["dtcr_matched"] <= b["dtcr_total"]
    assert isinstance(b["harness_families"], list) and b["harness_families"]
    assert b["output_file_name"].endswith(".xlsx")


@needs_files
def test_dtcr_match_returns_xlsx():
    r = client.post("/dtcr/match", files=_uploads(["old", "new", "dtcr"]))
    assert r.status_code == 200 and r.content[:2] == b"PK"


@needs_files
def test_preorder_returns_xlsx():
    r = client.post("/preorder", files=_uploads(["old", "new"]))
    assert r.status_code == 200 and r.content[:2] == b"PK"
