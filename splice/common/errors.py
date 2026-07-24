"""Exception hierarchy for the splice package.

``SpliceInputError`` subclasses ``ValueError`` so that existing ``except
ValueError`` handlers (and the Streamlit pages) keep catching bad-input errors,
while callers that want to distinguish splice errors from arbitrary ones can
catch the :class:`SpliceError` base instead.
"""

from __future__ import annotations


class SpliceError(Exception):
    """Base class for every error raised deliberately by the splice package."""


class SpliceInputError(SpliceError, ValueError):
    """The user-provided input is invalid — empty upload, unreadable file, etc."""


class SpliceSchemaError(SpliceInputError):
    """A required column or sheet is missing from an uploaded workbook."""
