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


def test_build_short_sheet_name_strips_program_and_phase_tokens():
    assert vbom_streamlit_engine._build_short_sheet_name("Harness_Complexity_27XX_X2_HarnessA.xlsx") == "HarnessA"
    assert vbom_streamlit_engine._build_short_sheet_name("27XX_X2_ABC_123.xlsx") == "ABC_123"


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


def test_giveaway_matches_required_code_without_extra_penalty():
    module = vbom_streamlit_engine._load_vbom_module()
    vin_matrix = pd.DataFrame(
        {
            "VIN": ["VIN_REQUIRED", "VIN_NEUTRAL"],
            "ABC": ["|", "|"],
            "DEF": ["|", ""],
        }
    )
    families = [
        {
            "family": "FAMILY_A",
            "header_codes": {"ABC", "DEF"},
            "pns": [
                ("12345678AA", {"ABC"}, {"DEF"}),
                ("12345678AB", {"ABC"}, set()),
            ],
        }
    ]

    selections, _candidates, _bom = module.build_outputs(vin_matrix, families)
    required = selections.loc[selections["VIN"] == "VIN_REQUIRED"].iloc[0]
    neutral = selections.loc[selections["VIN"] == "VIN_NEUTRAL"].iloc[0]

    assert required["MatchStatus"] == "EXACT"
    assert required["MatchedCount"] == 2
    assert required["MissingCount"] == 0
    assert required["ExtraCount"] == 0
    assert required["Score"] == 1
    assert neutral["MatchStatus"] == "EXACT"
    assert neutral["MatchedCount"] == 1
    assert neutral["ExtraCount"] == 0
    assert neutral["Score"] == 0


def test_zero_required_signals_returns_not_applicable_without_pn():
    module = vbom_streamlit_engine._load_vbom_module()
    vin_matrix = pd.DataFrame({"VIN": ["VIN_NO_TOW"], "AHT": [""]})
    families = [
        {
            "family": "TRAILER_TOW",
            "header_codes": {"AHT"},
            "pns": [("68284450AF", {"AHT"}, set())],
        }
    ]

    selections, candidates, bom = module.build_outputs(vin_matrix, families)
    result = selections.iloc[0]

    assert result["HarnessFamily"] == "TRAILER_TOW"
    assert result["MatchStatus"] == "NOT APPLICABLE"
    assert pd.isna(result["SelectedHarnessPN"])
    assert result["RequiredCount"] == 0
    assert result["Score"] is None or pd.isna(result["Score"])
    assert candidates.empty
    assert "TRAILER_TOW" in bom.columns
    assert pd.isna(bom.iloc[0]["TRAILER_TOW"])


def test_standard_codes_are_excluded_from_ranking_per_family():
    module = vbom_streamlit_engine._load_vbom_module()
    vin_matrix = pd.DataFrame(
        {"VIN": ["VIN001"], "STD": ["|"], "ABC": ["|"], "DEF": [""]}
    )
    families = [
        {
            "family": "FAMILY_A",
            "header_codes": {"STD", "ABC", "DEF"},
            "pns": [
                ("12345678AA", {"STD", "ABC"}, set()),
                ("12345678AB", {"STD", "DEF"}, set()),
            ],
        }
    ]

    selections, candidates, _bom = module.build_outputs(vin_matrix, families)
    result = selections.iloc[0]

    assert result["SelectedHarnessPN"] == "12345678AA"
    assert result["RequiredCount"] == 2
    assert result["MatchedCount"] == 2
    assert result["ExtraCount"] == 0
    assert result["MatchStatus"] == "EXACT"
    assert result["Score"] == 1
    assert not candidates["ExtraSalesCodes"].fillna("").str.contains("STD").any()


def test_a_code_standard_in_one_family_remains_rankable_in_another():
    module = vbom_streamlit_engine._load_vbom_module()
    vin_matrix = pd.DataFrame({"VIN": ["VIN001"], "ABC": ["|"], "DEF": ["|"]})
    families = [
        {
            "family": "FAMILY_OPTIONAL",
            "header_codes": {"ABC", "DEF"},
            "pns": [
                ("22345678AA", {"ABC"}, set()),
                ("22345678AB", {"DEF"}, set()),
            ],
        }
    ]

    selections, _candidates, _bom = module.build_outputs(vin_matrix, families)
    result = selections.iloc[0]

    assert result["RequiredCount"] == 2
    assert result["MatchedCount"] == 1
    assert result["MissingCount"] == 1


def test_nmr_absence_selects_regular_fan_and_presence_selects_heavy_fan():
    module = vbom_streamlit_engine._load_vbom_module()
    vin_matrix = pd.DataFrame(
        {
            "VIN": ["VIN_REGULAR_400W", "VIN_HEAVY_600W"],
            "LMW": ["|", "|"],
            "NMR": ["", "|"],
        }
    )
    families = [
        {
            "family": "FEM",
            "header_codes": {"LMW", "NMR"},
            "pns": [
                ("68784542AA", {"LMW"}, set()),
                ("68784543AA", {"LMW", "NMR"}, set()),
            ],
        }
    ]

    selections, _candidates, _bom = module.build_outputs(vin_matrix, families)
    regular = selections.loc[selections["VIN"] == "VIN_REGULAR_400W"].iloc[0]
    heavy = selections.loc[selections["VIN"] == "VIN_HEAVY_600W"].iloc[0]

    assert regular["SelectedHarnessPN"] == "68784542AA"
    assert regular["MatchStatus"] == "EXACT"
    assert heavy["SelectedHarnessPN"] == "68784543AA"
    assert heavy["MatchStatus"] == "EXACT"


def test_trailer_tow_applies_for_aht_or_hey_and_not_without_either():
    module = vbom_streamlit_engine._load_vbom_module()
    vin_matrix = pd.DataFrame(
        {
            "VIN": ["VIN_AHT", "VIN_HEY", "VIN_NO_TOW"],
            "AHT": ["|", "", ""],
            "HEY": ["", "|", ""],
        }
    )
    families = [
        {
            "family": "TRAILER_TOW",
            "header_codes": {"AHT"},
            "pns": [("68284450AF", {"AHT"}, set())],
        }
    ]

    selections, candidates, _bom = module.build_outputs(vin_matrix, families)
    aht = selections.loc[selections["VIN"] == "VIN_AHT"].iloc[0]
    hey = selections.loc[selections["VIN"] == "VIN_HEY"].iloc[0]
    no_tow = selections.loc[selections["VIN"] == "VIN_NO_TOW"].iloc[0]

    assert aht["SelectedHarnessPN"] == "68284450AF"
    assert aht["MatchStatus"] == "EXACT"
    assert hey["SelectedHarnessPN"] == "68284450AF"
    assert hey["MatchStatus"] == "EXACT"
    assert no_tow["MatchStatus"] == "NOT APPLICABLE"
    assert pd.isna(no_tow["SelectedHarnessPN"])
    assert candidates.loc[candidates["VIN"] == "VIN_NO_TOW"].empty
