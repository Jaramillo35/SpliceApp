from __future__ import annotations

import builtins
import importlib.util
from pathlib import Path

import pandas as pd

import vbom_streamlit_engine
from vbom_streamlit_engine import run_vbom_workflow


class DummyUpload:
    def __init__(self, name: str, payload: bytes):
        self.name = name
        self._payload = payload

    def getvalue(self) -> bytes:
        return self._payload


def test_load_vbom_module_succeeds_without_tkinter(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "tkinter" or name.startswith("tkinter."):
            raise ImportError("simulated missing tkinter")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    module = vbom_streamlit_engine._load_vbom_module()

    assert module is not None
    assert hasattr(module, "build_vin_matrix")


def test_run_vbom_workflow_creates_expected_outputs(tmp_path):
    doall_df = pd.DataFrame(
        {
            "VIN": ["VIN001", "VIN002"],
            "Sales Code ( 3 Char)": ["ABC, DEF", "ABC"],
        }
    )
    doall_path = tmp_path / "doall.xlsx"
    doall_df.to_excel(doall_path, index=False)

    complexity_df = pd.DataFrame(
        [
            ["PN", "ABC", "DEF"],
            ["68720520AA", "X", ""],
            ["68720520AB", "", "X"],
        ]
    )
    complexity_path = tmp_path / "Harness_Complexity_FAMILY_A.xlsx"
    with pd.ExcelWriter(complexity_path, engine="openpyxl") as writer:
        complexity_df.to_excel(writer, sheet_name="Complexity", index=False, header=False)
        pd.DataFrame([["Harness:", "FamilyA"]]).to_excel(writer, sheet_name="Harness PN", header=False, index=False)

    result = run_vbom_workflow(
        my="27",
        program="RU",
        source_type="DoAll",
        input_upload=DummyUpload(doall_path.name, doall_path.read_bytes()),
        complexity_uploads=[DummyUpload(complexity_path.name, complexity_path.read_bytes())],
        output_dir=tmp_path / "outputs",
    )

    assert result["master_path"].exists()
    assert result["vin_matrix_path"].exists()
    assert result["selections_path"].exists()
    assert result["formatted_template_path"] is None or Path(result["formatted_template_path"]).exists()
