"""Lightweight logging setup for the splice package.

Engines call :func:`get_logger` and log warnings/errors instead of failing
silently. The Streamlit entry point (or any script/agent driver) calls
:func:`configure` once to route those records to the console. The log level is
taken from the ``SPLICE_LOG_LEVEL`` environment variable (default ``INFO``).
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

LOG_FILE_NAME = "splice.log"
#: five files of 2 MB — enough history to reconstruct a bad afternoon,
#: small enough that a backup never has to carry it (backups skip logs/)
_MAX_BYTES = 2 * 1024 * 1024
_KEEP = 5


def configure(level: str | None = None, log_dir: str | os.PathLike | None = None) -> None:
    """Initialize root logging once. Safe to call repeatedly (no-op after first).

    With ``log_dir``, records also go to a rotating file there. The engines
    have logged properly all along; until the UI process asked for a file,
    every one of those records was discarded — so a bug report had nothing
    to attach.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    resolved = (level or os.getenv("SPLICE_LOG_LEVEL", "INFO")).upper()
    numeric = getattr(logging, resolved, logging.INFO)
    logging.basicConfig(level=numeric, format=_FORMAT)
    if log_dir:
        try:
            folder = Path(log_dir)
            folder.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(folder / LOG_FILE_NAME,
                                          maxBytes=_MAX_BYTES, backupCount=_KEEP,
                                          encoding="utf-8")
            handler.setFormatter(logging.Formatter(_FORMAT))
            handler.setLevel(numeric)
            logging.getLogger().addHandler(handler)
        except OSError as exc:  # a read-only volume must not stop the app
            logging.getLogger(__name__).warning("No log file (%s): %s", log_dir, exc)
    _CONFIGURED = True


def log_file(log_dir: str | os.PathLike) -> Path:
    return Path(log_dir) / LOG_FILE_NAME


def tail(log_dir: str | os.PathLike, lines: int = 300) -> str:
    """The last ``lines`` of the current log file, or an explanation."""
    path = log_file(log_dir)
    if not path.exists():
        return "No log file yet."
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            chunk = min(size, 256 * 1024)
            fh.seek(size - chunk)
            text = fh.read().decode("utf-8", errors="replace")
    except OSError as exc:
        return f"Could not read the log: {exc}"
    return "\n".join(text.splitlines()[-lines:])


def get_logger(name: str) -> logging.Logger:
    """Return a module logger (use ``get_logger(__name__)``)."""
    return logging.getLogger(name)
