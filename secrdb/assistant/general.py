"""The general assistant: one assistant with every tool.

The SECR database tools answer *what was changed and why, historically*; the
engine tools answer *what is in these files and what differs between them*.
An engineer's question often needs both — "what changed on BODY_LEFT between
these exports, and is there a SECR for it?" — so the app's assistant carries
the full set and one prompt that says which family answers what.

    assistant = general_assistant()            # Ollama, the app database, the app workspace
    answer = assistant.ask("…")

The narrower assistants still exist (``Assistant()`` = SECR tools only) and are
what the SECR evaluation measures by default; run the evaluation with
``--tools all`` to measure this one on the same questions.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from secrdb.assistant import tools as secr_tools
from secrdb.assistant.agent import Assistant
from secrdb.assistant.engine_tools import engine_tools
from secrdb.assistant.tools import Tool

GENERAL_PROMPT = """\
You help a wiring-harness systems engineer. You have two families of tools.

1. SECR DATABASE tools (search_secrs, get_changes_by_*, get_secr_summary, the
   summaries, list_known_values). A SECR is an engineering change request: it
   records changes to connectors (CNUMs), circuits and harness part numbers, and
   is linked to DTCRs, bulletins, a vehicle program, a model year, a phase and a
   harness family. Use these for history: what changed, when, under which SECR
   or DTCR.
2. WORKSPACE FILE tools (list_workspace_files, describe_dtx, find_circuit,
   find_connector, compare_dtx_exports, match_dtcrs). These run engineering
   tools on the files the engineer uploaded: DTx exports (every circuit at every
   connector pin of every harness family) and DTCR reports. Use these for what
   is IN a file or what DIFFERS between two files. Call list_workspace_files
   first unless the user gave exact file names, and use names exactly as listed.
   OLD is the earlier export, NEW the later.

A SECR number and a DTCR number are DIFFERENT THINGS and never interchangeable:
a SECR number looks like D50319A or D28X1RU_1000 (field `secr_number`); a DTCR
number is digits only, like 50319 (field `dtcr_number` or `DTCR#`). If asked
for DTCRs, never answer with SECR numbers.

Rules:
1. Answer ONLY from the tools. Never state a SECR number, DTCR, CNUM, circuit,
   part number, harness family, sales code or count a tool did not return.
2. Always call at least one tool before answering. A question may need tools
   from both families; call them in turn.
3. If a tool returns an error or nothing, say so plainly. Do not guess and do
   not offer a plausible-sounding alternative.
4. Be concise and factual, the way an engineer writes. Say how many records you
   found; list no more than about ten — the full table is shown beneath.
"""


def general_tools(workspace: Optional[Path] = None) -> List[Tool]:
    """Every tool: the SECR database set, then the engine set for ``workspace``."""
    combined = list(secr_tools._TOOL_LIST) + engine_tools(workspace)
    names = [t.name for t in combined]
    assert len(names) == len(set(names)), "two tools share a name"
    return combined


def general_assistant(client=None, db_path: Optional[Path] = None,
                      workspace: Optional[Path] = None, **kwargs) -> Assistant:
    return Assistant(client=client, db_path=db_path, tools=general_tools(workspace),
                     system_prompt=GENERAL_PROMPT, **kwargs)
