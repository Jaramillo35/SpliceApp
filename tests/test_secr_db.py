"""End-to-end tests for secr_db using real project files.

Run directly (no pytest required):  python tests/test_secr_db.py
Uses a throwaway DB file; never touches data/secr_database.db.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import secr_db  # noqa: E402

APP_DIR = Path(__file__).resolve().parents[1]
DEV_DIR = APP_DIR.parent

REAL_SECR = DEV_DIR / "SECR" / "7_2028_RU_X1_A_vs_2028_RU_X0_A_IP_DEF_DEF_Compare_20260507.xlsx"
DTCR_MATCHING = DEV_DIR / "SECR" / "28RU_X1_DTCR_Matching_Report.xlsx"


def _find_real_secr_workbook() -> Path:
    """Prefer a real generated SECR workbook if one exists."""
    candidates = (
        sorted((APP_DIR / "samples").glob("SECR_*.xlsx"))
        + sorted(DEV_DIR.glob("SECR*/SECR_*.xlsx"))
        + sorted(DEV_DIR.glob("SECR_*.xlsx"))
    )
    candidates = [c for c in candidates if "TEMPLATE" not in c.name.upper()]
    return candidates[0] if candidates else None


def test_roundtrip(secr_path: Path, db_path: Path) -> None:
    secr_bytes = secr_path.read_bytes()

    dtcr_df = None
    if DTCR_MATCHING.exists():
        dtcr_df = pd.read_excel(DTCR_MATCHING, sheet_name="DTCR_Harness_Family_Mapping")

    record = secr_db.record_from_workbook(
        secr_bytes,
        action="create",
        source_def_filename="test_def_compare.xlsx",
        filename=secr_path.name,
        change_type="Design Change",
        enriched=dtcr_df is not None,
        dtcr_mapping_df=dtcr_df,
    )
    assert record["secr_number"], "SECR # missing"
    assert record["affected_items"], "no affected items parsed"
    print(f"  parsed: SECR#={record['secr_number']} v{record['version']} "
          f"MY={record['model_year']} {record['program']} {record['phase']} "
          f"family={record['harness_family']}")
    print(f"  affected items: {len(record['affected_items'])}, "
          f"DTCR rows (family-matched): {len(record['dtcrs'])}")

    secr_id = secr_db.save_secr(record, db_path=db_path)
    assert secr_id > 0

    # Upsert: saving again must not duplicate
    secr_id2 = secr_db.save_secr(record, db_path=db_path)
    rows = secr_db.list_secrs(db_path=db_path)
    assert len(rows) == 1, f"expected 1 row after upsert, got {len(rows)}"

    # Full read-back
    full = secr_db.get_secr(secr_id2, db_path=db_path)
    assert len(full["affected_items"]) == len(record["affected_items"])
    assert len(full["dtcrs"]) == len(record["dtcrs"])

    # Search by affected item
    if full["affected_items"]:
        probe = full["affected_items"][0]["item"]
        hits = secr_db.find_by_item(probe, db_path=db_path)
        assert hits, f"find_by_item({probe!r}) returned nothing"
        print(f"  find_by_item({probe!r}) -> {len(hits)} SECR(s)")

    # Search by DTCR
    if full["dtcrs"]:
        probe = full["dtcrs"][0]["dtcr_number"]
        hits = secr_db.find_by_dtcr(probe, db_path=db_path)
        assert hits, f"find_by_dtcr({probe!r}) returned nothing"
        print(f"  find_by_dtcr({probe!r}) -> {len(hits)} SECR(s)")

    # Revision chain: simulate an update pointing at this record
    upd = dict(record)
    upd["version"] = "2"
    upd["action"] = "update"
    upd["parent_secr_number"] = record["secr_number"]
    upd_id = secr_db.save_secr(upd, db_path=db_path)
    chain = secr_db.get_revision_chain(upd_id, db_path=db_path)
    assert len(chain) == 2, f"expected chain of 2, got {len(chain)}"
    print(f"  revision chain OK ({chain[1]['secr_number']} v{chain[1]['version']}"
          f" -> v{chain[0]['version']})")

    # next_sequence
    nxt = secr_db.next_sequence(
        record["model_year"], record["program"], record["phase"],
        "Design Change", db_path=db_path,
    )
    print(f"  next_sequence -> {nxt}")


def main() -> None:
    secr_path = _find_real_secr_workbook()
    if secr_path is None:
        print("SKIP: no real SECR workbook found (SECR_*.xlsx)")
        return
    print(f"Testing with: {secr_path.name}")
    with tempfile.TemporaryDirectory() as tmp:
        test_roundtrip(secr_path, Path(tmp) / "test_secr.db")
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
