"""Lightweight logging setup for the splice package.

Engines call :func:`get_logger` and log warnings/errors instead of failing
silently. The Streamlit entry point (or any script/agent driver) calls
:func:`configure` once to route those records to the console. The log level is
taken from the ``SPLICE_LOG_LEVEL`` environment variable (default ``INFO``).
"""

from __future__ import annotations

import logging
import os

_CONFIGURED = False


def configure(level: str | None = None) -> None:
    """Initialize root logging once. Safe to call repeatedly (no-op after first)."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    resolved = (level or os.getenv("SPLICE_LOG_LEVEL", "INFO")).upper()
    logging.basicConfig(
        level=getattr(logging, resolved, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a module logger (use ``get_logger(__name__)``)."""
    return logging.getLogger(name)
