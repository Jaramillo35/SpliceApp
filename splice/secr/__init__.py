"""SECR area — generation, enrichment, and database persistence.

Sub-modules:
    * :mod:`splice.secr.generate` — build/update the SECR workbook from a DEF.
    * :mod:`splice.secr.enrich`   — fill Reason-for-Change / DTCR / bulletin cells.
    * :mod:`splice.secr.db`       — SQLite persistence for generated SECRs.

DTCR matching used by enrichment lives in :mod:`splice.dtcr` (shared).
"""

from __future__ import annotations

from splice.secr.generate import create_secr_bytes, update_secr_bytes

__all__ = ["create_secr_bytes", "update_secr_bytes"]
