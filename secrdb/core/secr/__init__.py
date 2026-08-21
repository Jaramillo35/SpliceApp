"""SECR area — generation, enrichment, and database persistence.

Sub-modules:
    * :mod:`secrdb.core.secr.generate` — build/update the SECR workbook from a DEF.
    * :mod:`secrdb.core.secr.enrich`   — fill Reason-for-Change / DTCR / bulletin cells.
    * :mod:`secrdb.core.secr.db`       — SQLite persistence for generated SECRs.

DTCR matching used by enrichment lives in :mod:`secrdb.core.dtcr` (shared).
"""

from __future__ import annotations

from secrdb.core.secr.generate import create_secr_bytes, update_secr_bytes

__all__ = ["create_secr_bytes", "update_secr_bytes"]
