from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wiring_harness_processor import (
    CircuitNameAllocator,
    Configuration,
    Endpoint,
    _candidate_codes_for_configuration,
    generate_sales_code_expression,
    generate_splices,
    _harmonize_shared_splice_trunk_rows,
    parse_sales_code_expression,
    evaluate_expression,
    validate_generated_expression,
)


def test_generate_sales_code_expression_can_drop_standard_501() -> None:
    harness_code_map = {
        "PN1": {"501", "AAA"},
        "PN2": {"501", "BBB"},
        "PN3": {"501", "AAA", "BBB"},
    }

    expr = generate_sales_code_expression(
        target_harnesses=["PN1", "PN3"],
        harness_code_map=harness_code_map,
        candidate_codes={"501", "AAA", "BBB"},
    )

    assert "501" not in expr
    assert validate_generated_expression(expr, ["PN1", "PN3"], harness_code_map)


def test_parse_sales_code_expression_treats_501_as_always_present() -> None:
    parsed = parse_sales_code_expression("501&AAA&-BBB")

    assert parsed.postfix_tokens == ["AAA", "BBB", "NOT", "&"]
    assert parsed.symbols == {"AAA", "BBB"}


def test_501_only_expression_matches_all_harnesses() -> None:
    parsed = parse_sales_code_expression("501")

    assert evaluate_expression(parsed, set()) is True
    assert evaluate_expression(parsed, {"AAA"}) is True


def test_generate_sales_code_expression_reduces_against_observed_harnesses() -> None:
    harness_code_map = {
        "PN1": {"LCA"},
        "PN2": {"LCH"},
        "PN3": {"LCL"},
        "PN4": {"LHE"},
        "PN5": {"LCA", "LCH"},
    }

    expr = generate_sales_code_expression(
        target_harnesses=["PN1"],
        harness_code_map=harness_code_map,
        candidate_codes={"LCA", "LCH", "LCL", "LHE"},
    )

    assert expr == "-LCH&-LCL&-LHE"
    assert validate_generated_expression(expr, ["PN1"], harness_code_map)


def test_candidate_codes_for_configuration_prefers_endpoint_scope() -> None:
    endpoints = [
        Endpoint(cnum="A", pin="1", circuit="Z913", sales_code="CUS/(CUN&RTM)"),
        Endpoint(cnum="B", pin="2", circuit="Z913", sales_code="LCH/LCL/LHE"),
        Endpoint(cnum="C", pin="3", circuit="Z913", sales_code="GNC/XGD"),
        Endpoint(cnum="D", pin="4", circuit="Z913", sales_code="GN6/GNC"),
        Endpoint(cnum="E", pin="5", circuit="Z913", sales_code="501"),
    ]

    scoped = _candidate_codes_for_configuration(
        endpoints,
        {"CUS", "CUN", "RTM", "LCH", "LCL", "LHE", "GNC", "XGD", "GN6", "EXTRA"},
    )

    assert scoped == {"CUS", "CUN", "RTM", "LCH", "LCL", "LHE", "GNC", "XGD", "GN6"}


def test_generate_splices_reuses_shared_always_present_anchor_for_same_circuit() -> None:
    circuit_allocator = CircuitNameAllocator()
    splice_allocator: dict[str, object] = {}
    shared_anchor = Endpoint(cnum="X440A", pin="A6", circuit="M11", sales_code="501")

    cfg1 = Configuration(
        configuration_id="CFG001",
        circuit_name="M11",
        endpoints=[
            Endpoint(cnum="D1", pin="1", circuit="M11", sales_code="LCA&-CUN&-LCH&-LCL&-LHE"),
            Endpoint(cnum="D2", pin="2", circuit="M11", sales_code="ALT"),
            shared_anchor,
        ],
        target_harness_pns=["PN1"],
        generated_sales_code="LCA&-CUN&-LCH&-LCL&-LHE",
    )
    cfg2 = Configuration(
        configuration_id="CFG002",
        circuit_name="M11",
        endpoints=[
            Endpoint(cnum="D3", pin="3", circuit="M11", sales_code="501"),
            Endpoint(cnum="D4", pin="4", circuit="M11", sales_code="ALT2"),
            shared_anchor,
        ],
        target_harness_pns=["PN2"],
        generated_sales_code="501",
    )

    rows1 = generate_splices(cfg1, splice_allocator, circuit_allocator)
    rows2 = generate_splices(cfg2, splice_allocator, circuit_allocator)

    trunk1 = next(row for row in rows1 if row["Connection Type"] == "Splice Trunk")
    trunk2 = next(row for row in rows2 if row["Connection Type"] == "Splice Trunk")

    assert trunk1["Splice Name"] == trunk2["Splice Name"]
    assert trunk1["Generated Circuit"] == trunk2["Generated Circuit"]
    assert trunk1["To CNUM"] == "X440A"
    assert trunk2["To CNUM"] == "X440A"
    assert trunk1["To Pin"] == "A6"
    assert trunk2["To Pin"] == "A6"


def test_harmonize_shared_splice_trunk_rows_applies_one_sales_code_to_shared_trunk() -> None:
    harness_code_map = {
        "PN1": {"501", "LCA"},
        "PN2": {"501"},
    }
    circuit_codes = {"M11": {"501", "LCA"}}
    rows = [
        {
            "Configuration": "CFG001",
            "Circuit Name": "M11",
            "Generated Circuit": "M11A",
            "Connection Type": "Splice Trunk",
            "Splice Name": "SM11A",
            "From CNUM": "SM11A",
            "From Pin": "",
            "To CNUM": "X440A",
            "To Pin": "A6",
            "Sales Code": "LCA",
            "Target Harness PNs": "PN1",
            "CAN Mode": "False",
        },
        {
            "Configuration": "CFG002",
            "Circuit Name": "M11",
            "Generated Circuit": "M11A",
            "Connection Type": "Splice Trunk",
            "Splice Name": "SM11A",
            "From CNUM": "SM11A",
            "From Pin": "",
            "To CNUM": "X440A",
            "To Pin": "A6",
            "Sales Code": "501",
            "Target Harness PNs": "PN2",
            "CAN Mode": "False",
        },
    ]

    harmonized = _harmonize_shared_splice_trunk_rows(rows, harness_code_map, circuit_codes)

    assert harmonized[0]["Sales Code"] == "TRUE"
    assert harmonized[1]["Sales Code"] == "TRUE"