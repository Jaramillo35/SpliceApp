"""Invented programme for exercising per-harness circuit applicability.

Deliberately NOT real data. Programme "9000ZZ", phase "X9_A", three harness
families built so that every classification and every failure mode appears:

BODY_LEFT  (4 builds, tracks AAA/BBB/CCC)
  CKT_100  no sales code               -> unconditional, all 4 builds
  CKT_200  "AAA"                       -> variant (2 of 4)
  CKT_300  "AAA/BBB"                   -> variant (3 of 4)
  CKT_400  "AAA&BBB"                   -> variant (1 of 4)
  CKT_500  "CCC"                       -> never built (no build carries CCC)
  CKT_600  "ZZZ"                       -> ZZZ untracked -> treated as present
  CKT_700  two pins, "AAA" and ""      -> one pin unconditional => whole circuit is
  CKT_800  two pins, "AAA" and "BBB"   -> union AAA/BBB -> variant (3 of 4)

IP         (2 builds, tracks AAA only)
  CKT_900  "AAA"                       -> variant (1 of 2)
  CKT_950  "-AAA"                      -> variant (1 of 2)

DASH       -> present in the DTx, no complexity file loaded -> no complexity
"""

from __future__ import annotations

from splice.dtxcircuits.models import CircuitRow
from splice.inline.model import Build, Harness

PROGRAM = "9000ZZ"
PHASE = "X9_A"


def body_left() -> Harness:
    """Four builds. AAA on two, BBB on two, one build carries both, one bare."""
    return Harness(
        name="BODY_LEFT", def_id="90001",
        builds=[
            Build("90000001AA", codes=frozenset({"AAA"})),
            Build("90000002AA", codes=frozenset({"BBB"})),
            Build("90000003AA", codes=frozenset({"AAA", "BBB"})),
            Build("90000004AA", codes=frozenset()),
        ],
        complexity_codes={"AAA", "BBB", "CCC"},
    )


def ip() -> Harness:
    return Harness(
        name="IP", def_id="90002",
        builds=[
            Build("90000010AA", codes=frozenset({"AAA"})),
            Build("90000011AA", codes=frozenset()),
        ],
        complexity_codes={"AAA"},
    )


def circuit_rows() -> list[CircuitRow]:
    def row(family, circuit, code="", cnum="C1", pin="1"):
        return CircuitRow(harness_family=family, circuit=circuit,
                          sales_code=code, cnum=cnum, pin=pin,
                          connector_pn="99999999", function="TEST")

    return [
        row("BODY_LEFT", "CKT_100"),
        row("BODY_LEFT", "CKT_200", "AAA"),
        row("BODY_LEFT", "CKT_300", "AAA/BBB"),
        row("BODY_LEFT", "CKT_400", "AAA&BBB"),
        row("BODY_LEFT", "CKT_500", "CCC"),
        row("BODY_LEFT", "CKT_600", "ZZZ"),
        # one occurrence unconditional -> the circuit is unconditional
        row("BODY_LEFT", "CKT_700", "AAA", cnum="C2", pin="3"),
        row("BODY_LEFT", "CKT_700", "", cnum="C3", pin="4"),
        # two conditioned occurrences -> union
        row("BODY_LEFT", "CKT_800", "AAA", cnum="C4", pin="5"),
        row("BODY_LEFT", "CKT_800", "BBB", cnum="C5", pin="6"),
        row("IP", "CKT_900", "AAA"),
        row("IP", "CKT_950", "-AAA"),
        row("DASH", "CKT_999", "AAA"),
    ]


def harnesses() -> dict:
    """DTx family name -> Harness. DASH deliberately absent."""
    return {"BODY_LEFT": body_left(), "IP": ip()}
