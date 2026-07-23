"""VBOM risk-matrix workflow.

Thin orchestration over the legacy VBOM desktop module (loaded dynamically from
the path in :data:`splice.config.VBOM_ROOT_CANDIDATES`). Implementation lives in
:mod:`splice.vbom.workflow`.
"""

from __future__ import annotations

from splice.vbom.workflow import format_workbook_output, run_vbom_workflow

__all__ = ["format_workbook_output", "run_vbom_workflow"]
