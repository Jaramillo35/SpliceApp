"""Local, on-premises AI assistant over the SECR database.

The assistant answers questions by calling read-only tools against the
database (:mod:`secrdb.assistant.tools`) — never by recalling training data and
never by writing SQL. Inference runs locally through Ollama, so no engineering
data leaves the machine.
"""

from secrdb.assistant.tools import (
    MAX_ROWS,
    TOOLS,
    Tool,
    ToolResult,
    call_tool,
    tool_names,
    tool_specs,
)

__all__ = [
    "MAX_ROWS",
    "TOOLS",
    "Tool",
    "ToolResult",
    "call_tool",
    "tool_names",
    "tool_specs",
]
