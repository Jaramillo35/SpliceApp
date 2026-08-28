"""Per-harness circuit applicability from the DTx and individual complexity files.

Reads the Detailed DTx Circuits Report, groups circuits by harness family,
unions each circuit's sales-code conditions, and resolves them against that
harness's own build table to say which part numbers carry which circuits.
"""

from splice.dtxcircuits.analyze import analyze, analyze_harness, union_condition
from splice.dtxcircuits.dtx import read_dtx_circuits
from splice.dtxcircuits.models import (
    ALL_BUILDS,
    NEVER,
    NO_COMPLEXITY,
    UNCONDITIONAL,
    VARIANT,
    CircuitApplicability,
    CircuitRow,
    DtxMeta,
    HarnessAnalysis,
)

__all__ = [
    "analyze", "analyze_harness", "union_condition", "read_dtx_circuits",
    "CircuitApplicability", "CircuitRow", "DtxMeta", "HarnessAnalysis",
    "UNCONDITIONAL", "ALL_BUILDS", "VARIANT", "NEVER", "NO_COMPLEXITY",
]
