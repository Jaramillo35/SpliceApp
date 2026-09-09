"""DEF Editor automation — UI Automation over DEF Editor, with a testable seam.

    from defauto import application

    session = application.demo()          # anywhere, no DEF Editor
    session = application.connect()       # Windows, attached to the real one

The two return the same ``Session``, so a workflow written against one runs
against the other unchanged. See ``BUILD_WINDOWS.txt`` for building the exe.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["application", "ids"]
