"""The SECR engineering core.

Vendored from the ``splice`` package so this app has no external dependency on
the Splice checkout. It holds the deterministic pieces:

* :mod:`secrdb.core.secr.generate`  — build/update a SECR workbook from a DEF compare
* :mod:`secrdb.core.secr.parse`     — SECR workbook -> structured change records
* :mod:`secrdb.core.secr.db`        — the only module that opens SQLite
* :mod:`secrdb.core.secr.importer`  — bulk import
* :mod:`secrdb.core.secr.identity`  — numbering, naming, versioning
* :mod:`secrdb.core.secr.generation`— the create/update workflows
* :mod:`secrdb.core.secr.api`       — the read-only query surface

These transforms are engineering logic: their output feeds downstream tools, so
they are changed only deliberately.
"""
