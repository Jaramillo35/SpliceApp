from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dtx_compare_engine import generate_preorder_generation_workbook


REQUIRED_COLUMNS = [
    "Device Control Number",
    "Device Name",
    "Suffix",
    "CNUM",
    "Number of Cavities",
    "Connector PN",
    "Harness Family",
    "Pin Number",
    "Circuit Name",
    "Circuit Suffix",
    "Circuit Function",
    "Color",
    "Terminal",
    "Connector FCA part number",
    "Wire Gauge",
    "Wire Type",
    "Sales Code",
]


def _write_dtx_excel(path: Path, rows: list[dict[str, object]]) -> None:
    frame = pd.DataFrame(rows, columns=REQUIRED_COLUMNS)
    with pd.ExcelWriter(path) as writer:
        frame.to_excel(writer, index=False)


def test_generate_preorder_generation_workbook_creates_excel_bytes(tmp_path: Path) -> None:
    old_path = tmp_path / "old.xlsx"
    new_path = tmp_path / "new.xlsx"
    _write_dtx_excel(
        old_path,
        [
            {
                "Device Control Number": "DCN1",
                "Device Name": "Device A",
                "Suffix": "A",
                "CNUM": "C1",
                "Number of Cavities": "2",
                "Connector PN": "PN-OLD",
                "Harness Family": "HF-1",
                "Pin Number": "1",
                "Circuit Name": "CIRCUIT1",
                "Circuit Suffix": "S1",
                "Circuit Function": "FUNC",
                "Color": "RED",
                "Terminal": "T1",
                "Connector FCA part number": "FCA1",
                "Wire Gauge": "18",
                "Wire Type": "W1",
                "Sales Code": "S1",
            }
        ],
    )
    _write_dtx_excel(
        new_path,
        [
            {
                "Device Control Number": "DCN1",
                "Device Name": "Device A",
                "Suffix": "A",
                "CNUM": "C1",
                "Number of Cavities": "2",
                "Connector PN": "PN-NEW",
                "Harness Family": "HF-1",
                "Pin Number": "1",
                "Circuit Name": "CIRCUIT1",
                "Circuit Suffix": "S1",
                "Circuit Function": "FUNC",
                "Color": "RED",
                "Terminal": "T1",
                "Connector FCA part number": "FCA1",
                "Wire Gauge": "18",
                "Wire Type": "W1",
                "Sales Code": "S1",
            },
            {
                "Device Control Number": "DCN2",
                "Device Name": "Device B",
                "Suffix": "B",
                "CNUM": "C2",
                "Number of Cavities": "4",
                "Connector PN": "PN-NEW2",
                "Harness Family": "HF-2",
                "Pin Number": "2",
                "Circuit Name": "CIRCUIT2",
                "Circuit Suffix": "S2",
                "Circuit Function": "FUNC2",
                "Color": "BLUE",
                "Terminal": "T2",
                "Connector FCA part number": "FCA2",
                "Wire Gauge": "20",
                "Wire Type": "W2",
                "Sales Code": "S2",
            },
        ],
    )

    result = generate_preorder_generation_workbook(
        old_file_bytes=old_path.read_bytes(),
        new_file_bytes=new_path.read_bytes(),
        old_file_name=old_path.name,
        new_file_name=new_path.name,
    )

    assert result["output_excel_bytes"]
    assert "summary_df" in result
    assert "connector_changes_df" in result
    assert result["summary_df"].shape[0] >= 1
    assert any(result["summary_df"]["Change Type"] == "Connector PN Change")


def test_generate_preorder_generation_workbook_requires_valid_input_files(tmp_path: Path) -> None:
    old_path = tmp_path / "old.xlsx"
    new_path = tmp_path / "new.xlsx"
    old_path.write_bytes(b"not an excel file")
    new_path.write_bytes(b"not an excel file")

    with pytest.raises(ValueError):
        generate_preorder_generation_workbook(
            old_file_bytes=old_path.read_bytes(),
            new_file_bytes=new_path.read_bytes(),
            old_file_name=old_path.name,
            new_file_name=new_path.name,
        )
