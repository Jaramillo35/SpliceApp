"""DTx Compare — old-vs-new DTx diffing, change reporting, and PreOrder output.

The implementation lives in :mod:`splice.dtx_compare.engine`; the public entry
points used by the UI and by scripted/agent callers are re-exported here. DTCR
matching used by this area is shared from :mod:`splice.dtcr`.
"""

from __future__ import annotations

from splice.dtx_compare.engine import (
    compare_reports,
    generate_dtcr_matching_report,
    generate_dtx_change_report,
    launch_preorder_generation_tool,
    load_dtcr_report,
)

__all__ = [
    "compare_reports",
    "generate_dtcr_matching_report",
    "generate_dtx_change_report",
    "launch_preorder_generation_tool",
    "load_dtcr_report",
]
