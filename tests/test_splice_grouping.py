from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wiring_harness_processor import CircuitNameAllocator, Configuration, Endpoint, generate_splices


def test_generate_splices_reuses_base_name_for_shared_anchor_endpoint() -> None:
    circuit_allocator = CircuitNameAllocator()
    splice_allocator: dict[str, object] = {}

    shared_anchor = Endpoint(cnum="X440A", pin="A6", circuit="M11", sales_code="501")
    cfg1 = Configuration(
        configuration_id="CFG001",
        circuit_name="M11",
        endpoints=[
            Endpoint(cnum="D1", pin="1", circuit="M11", sales_code="AAA"),
            Endpoint(cnum="D2", pin="2", circuit="M11", sales_code="BBB"),
            shared_anchor,
        ],
        target_harness_pns=["PN1"],
        generated_sales_code="AAA",
    )
    cfg2 = Configuration(
        configuration_id="CFG002",
        circuit_name="M11",
        endpoints=[
            Endpoint(cnum="D3", pin="3", circuit="M11", sales_code="CCC"),
            Endpoint(cnum="D4", pin="4", circuit="M11", sales_code="DDD"),
            shared_anchor,
        ],
        target_harness_pns=["PN2"],
        generated_sales_code="CCC",
    )

    rows1 = generate_splices(cfg1, splice_allocator, circuit_allocator)
    rows2 = generate_splices(cfg2, splice_allocator, circuit_allocator)

    trunk1 = next(row for row in rows1 if row["Connection Type"] == "Splice Trunk")
    trunk2 = next(row for row in rows2 if row["Connection Type"] == "Splice Trunk")

    assert trunk1["Splice Name"] == "SM11"
    assert trunk2["Splice Name"] == "SM11"
    assert trunk1["To CNUM"] == "X440A"
    assert trunk2["To CNUM"] == "X440A"
    assert trunk1["To Pin"] == "A6"
    assert trunk2["To Pin"] == "A6"