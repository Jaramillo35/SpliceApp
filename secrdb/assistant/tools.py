"""The tool surface the local assistant is allowed to call.

Every tool is a **read-only** query against the SECR database. There is no SQL
tool and no write tool: the model chooses which question to ask and how to
phrase the answer, but it can neither invent data nor change it.

Each entry carries a JSON schema in the shape Ollama (and the OpenAI
function-calling convention it follows) expects, so ``tool_specs()`` can be
handed straight to ``/api/chat``.

Two rules shape this module:

* **Descriptions are written for the model, not for us.** They say which
  question the tool answers and what the arguments look like in real data
  (``D2784J``, ``A937F``, ``50319``), because that is the only guidance the
  model gets when choosing.
* **Results are capped and JSON-safe.** A question like "every change on the IP
  harness" can match thousands of rows; the tool returns the first ``limit``
  and says so, rather than silently truncating or blowing the context window.

This module deliberately has no Ollama dependency, so it is testable on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from secrdb.core.secr import api, db as secr_db

#: Hard ceiling on rows returned to the model, whatever it asks for. Large
#: enough for real answers, small enough to keep the context usable.
MAX_ROWS = 200

#: Fields never worth sending to a model: large, binary, or noise.
_DROPPED_FIELDS = frozenset({"content", "source_file_blob", "parse_warnings"})


@dataclass(frozen=True)
class Tool:
    """One callable question, plus the schema the model sees."""

    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Callable[..., Any]

    def spec(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolResult:
    """What a tool call produced — the evidence an answer must be built from."""

    name: str
    arguments: Dict[str, Any]
    data: Any = None
    row_count: int = 0
    truncated: bool = False
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    def to_model_payload(self) -> Dict[str, Any]:
        """The JSON the model sees back. Errors are reported, never hidden —
        a tool that failed must not look like a question with no answer."""
        if self.error:
            return {"error": self.error}
        payload: Dict[str, Any] = {"result": self.data}
        if isinstance(self.data, list):
            payload["row_count"] = self.row_count
            if self.truncated:
                payload["truncated"] = True
                payload["note"] = (
                    f"Only the first {self.row_count} rows are shown. Narrow the "
                    "question (by harness family, program, or model year) to see "
                    "the rest."
                )
        return payload


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

def _schema(
    properties: Dict[str, Dict[str, Any]], required: Optional[List[str]] = None
) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


_LIMIT = {
    "type": "integer",
    "description": f"Maximum rows to return (default 50, hard cap {MAX_ROWS}).",
}


def _text(description: str) -> Dict[str, Any]:
    return {"type": "string", "description": description}


# ---------------------------------------------------------------------------
# Result shaping
# ---------------------------------------------------------------------------

def _jsonable(value: Any) -> Any:
    """Make a database row safe to serialise: no bytes, no dates, no blobs."""
    if isinstance(value, dict):
        return {
            key: _jsonable(item)
            for key, item in value.items()
            if key not in _DROPPED_FIELDS
        }
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(bytes(value))} bytes>"
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _clamp(limit: Any) -> int:
    try:
        requested = int(limit)
    except (TypeError, ValueError):
        requested = 50
    return max(1, min(requested, MAX_ROWS))


# ---------------------------------------------------------------------------
# Tool handlers
#
# Each takes only keyword arguments matching its schema, plus db_path.
# ---------------------------------------------------------------------------

def _search_secrs(
    query: str = "",
    program: str = "",
    model_year: str = "",
    harness_family: str = "",
    phase: str = "",
    dtcr: str = "",
    limit: int = 50,
    *,
    db_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    return api.search_secrs(
        query,
        program=program,
        model_year=model_year,
        harness_family=harness_family,
        phase=phase,
        dtcr=dtcr,
        limit=_clamp(limit),
        db_path=db_path,
    )


def _get_secr_summary(
    secr_number: str, version: str = "", *, db_path: Optional[Path] = None
) -> Any:
    return api.get_secr_summary(secr_number, version, db_path=db_path)


def _get_changes_by_secr(
    secr_number: str, version: str = "", *, db_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """Changes of one SECR, each stamped with the SECR it belongs to.

    The stored change rows carry only a numeric ``secr_id``. Every other tool
    returns rows joined to their SECR, so without this the model would receive
    the one result set it cannot attribute — and an answer naming the SECR
    would have no evidence for that name.
    """
    summary = api.get_secr_summary(secr_number, version, db_path=db_path)
    if summary is None:
        return []
    context = {
        key: summary.get(key)
        for key in (
            "secr_number",
            "version",
            "program",
            "model_year",
            "phase",
            "harness_family",
            "bulletin_numbers",
        )
    }
    return [
        {**row, **context}
        for row in api.get_changes_by_secr(secr_number, version, db_path=db_path)
    ]


def _get_changes_by_dtcr(
    dtcr_number: str, limit: int = 50, *, db_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    return api.get_changes_by_dtcr(dtcr_number, limit=_clamp(limit), db_path=db_path)


def _get_changes_by_harness(
    harness_family: str,
    model_year: str = "",
    program: str = "",
    limit: int = 50,
    *,
    db_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    return api.get_changes_by_harness(
        harness_family,
        model_year=model_year,
        program=program,
        limit=_clamp(limit),
        db_path=db_path,
    )


def _get_changes_by_cnum(
    cnum: str, limit: int = 50, *, db_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    return api.get_changes_by_cnum(cnum, limit=_clamp(limit), db_path=db_path)


def _get_changes_by_endpoint(
    connector: str,
    cavity: str = "",
    limit: int = 50,
    *,
    db_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    return api.get_changes_by_endpoint(
        connector, cavity=cavity, limit=_clamp(limit), db_path=db_path
    )


def _get_changes_by_circuit(
    circuit: str, limit: int = 50, *, db_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    return api.get_changes_by_circuit(circuit, limit=_clamp(limit), db_path=db_path)


def _get_connector_changes(
    connector_pn: str, limit: int = 50, *, db_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    return api.get_connector_changes(
        connector_pn, limit=_clamp(limit), db_path=db_path
    )


def _get_program_summary(program: str, *, db_path: Optional[Path] = None) -> Any:
    return api.get_program_summary(program, db_path=db_path)


def _get_model_year_summary(model_year: str, *, db_path: Optional[Path] = None) -> Any:
    return api.get_model_year_summary(model_year, db_path=db_path)


def _get_database_summary(*, db_path: Optional[Path] = None) -> Any:
    return api.get_database_summary(db_path=db_path)


def _get_revision_chain(secr_number: str, *, db_path: Optional[Path] = None) -> Any:
    return api.get_revision_chain(secr_number, db_path=db_path)


def _get_change_counts(
    program: str = "",
    model_year: str = "",
    harness_family: str = "",
    action: str = "",
    top_n: int = 10,
    *,
    db_path: Optional[Path] = None,
) -> Any:
    """Aggregate counts — the "which/most/how many" questions."""
    return secr_db.change_facets(
        top_n=_clamp(top_n),
        program=program,
        model_year=model_year,
        harness_family=harness_family,
        action=action,
        db_path=db_path,
    )


def _list_known_values(*, db_path: Optional[Path] = None) -> Dict[str, Any]:
    """The vocabulary of the database, so the model binds names to real values
    instead of guessing (``"the IP harness"`` -> ``IP``)."""
    values: Dict[str, Any] = {}
    for column in ("program", "model_year", "phase", "harness_family"):
        try:
            values[column] = secr_db.distinct_values(column, db_path=db_path)
        except Exception:  # noqa: BLE001 - an empty database is not an error
            values[column] = []
    try:
        values["change_type"] = secr_db.distinct_change_actions(db_path=db_path)
    except Exception:  # noqa: BLE001
        values["change_type"] = []
    return values


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_TOOL_LIST: List[Tool] = [
    Tool(
        name="list_known_values",
        description=(
            "List the values that actually exist in the database: programs, "
            "model years, phases, harness families and change types. Call this "
            "first when the question names something loosely (\"the IP "
            "harness\", \"MY27\") so you use the exact stored value."
        ),
        parameters=_schema({}),
        handler=_list_known_values,
    ),
    Tool(
        name="search_secrs",
        description=(
            "Find SECRs by free text and/or filters. The text matches a SECR "
            "number, subject, DTCR, bulletin, harness family, or any connector "
            "(CNUM), circuit or part number touched by one of its changes. Use "
            "this when the question is about *which SECRs* rather than about "
            "individual changes."
        ),
        parameters=_schema(
            {
                "query": _text(
                    "Free text: a CNUM like D2784J, a circuit like A937F, a "
                    "DTCR like 50319, or a SECR number like D50319A."
                ),
                "program": _text("Vehicle program, e.g. RU."),
                "model_year": _text("Model year as stored, e.g. 2028."),
                "harness_family": _text("Harness family, e.g. IP or BODY_LEFT."),
                "phase": _text("Engineering phase, e.g. X1."),
                "dtcr": _text("DTCR number, e.g. 50319."),
                "limit": _LIMIT,
            }
        ),
        handler=_search_secrs,
    ),
    Tool(
        name="get_secr_summary",
        description=(
            "Header details of one SECR: program, model year, phase, harness "
            "family, bulletin, DTCR numbers, author, issue date, filename, and "
            "how many changes it contains broken down by type. Use this to "
            "describe a SECR without listing every change."
        ),
        parameters=_schema(
            {
                "secr_number": _text("SECR number, e.g. D50319A or D28X1RU_1000."),
                "version": _text("Version, e.g. 1 or 2. Omit for the latest."),
            },
            required=["secr_number"],
        ),
        handler=_get_secr_summary,
    ),
    Tool(
        name="get_changes_by_secr",
        description=(
            "Every change record in one SECR: what object changed (connector, "
            "circuit, harness part number), the field, the old value and the "
            "new value. Use this for \"what changed in SECR X\"."
        ),
        parameters=_schema(
            {
                "secr_number": _text("SECR number, e.g. D50319A."),
                "version": _text("Version. Omit for the latest."),
            },
            required=["secr_number"],
        ),
        handler=_get_changes_by_secr,
    ),
    Tool(
        name="get_changes_by_circuit",
        description=(
            "Every change to a circuit, across all SECRs, with the SECR number, "
            "program, model year, harness family, DTCR, and the old and new "
            "values. Circuit identifiers combine number and suffix (A937F); "
            "a prefix works too, so A937 also finds A937F. Use this for "
            "\"when/where did circuit A111 change\"."
        ),
        parameters=_schema(
            {
                "circuit": _text("Circuit identifier, e.g. A111 or A937F."),
                "limit": _LIMIT,
            },
            required=["circuit"],
        ),
        handler=_get_changes_by_circuit,
    ),
    Tool(
        name="get_changes_by_cnum",
        description=(
            "Every change involving a connector, by its CNUM, across all "
            "SECRs. Use this for \"has connector D2784J changed before\" or "
            "\"what happened to C205\". Covers both roles: the connector "
            "itself changing, and a circuit being routed to or from it. Each "
            "row says which in `connector_role` ('connector' or 'endpoint'); "
            "endpoint rows also give `endpoint_side` (FROM/TO) and "
            "`endpoint_cavity`."
        ),
        parameters=_schema(
            {
                "cnum": _text("Connector number (CNUM), e.g. D2784J or C205."),
                "limit": _LIMIT,
            },
            required=["cnum"],
        ),
        handler=_get_changes_by_cnum,
    ),
    Tool(
        name="get_changes_by_endpoint",
        description=(
            "Circuits that terminate on a connector, optionally at one "
            "cavity. Use this for \"what is wired to D2784J\", \"which "
            "circuits land on C205 cavity 7\" or \"what moved off X501A\". "
            "The DNUM in a circuit's endpoint is the same identifier as a "
            "connector's CNUM. Each row's `object_id` is the CIRCUIT; the "
            "connector and cavity are in from_dnum/from_cav/to_dnum/to_cav."
        ),
        parameters=_schema(
            {
                "connector": _text(
                    "Connector the circuit lands on (DNUM/CNUM), e.g. D2784J."
                ),
                "cavity": _text(
                    "Optional cavity, e.g. 7 or C. Cavities can be letters."
                ),
                "limit": _LIMIT,
            },
            required=["connector"],
        ),
        handler=_get_changes_by_endpoint,
    ),
    Tool(
        name="get_connector_changes",
        description=(
            "Find changes where a connector *part number* was the old or the "
            "new value. Use this for \"where was part number D4Z080-000-B "
            "introduced\", as opposed to searching by CNUM."
        ),
        parameters=_schema(
            {
                "connector_pn": _text("Connector part number, e.g. D4Z080-000-B."),
                "limit": _LIMIT,
            },
            required=["connector_pn"],
        ),
        handler=_get_connector_changes,
    ),
    Tool(
        name="get_changes_by_dtcr",
        description=(
            "Every change attributed to a DTCR, across all SECRs. Use this for "
            "\"what did DTCR 50319 change\"."
        ),
        parameters=_schema(
            {
                "dtcr_number": _text("DTCR number, e.g. 50319."),
                "limit": _LIMIT,
            },
            required=["dtcr_number"],
        ),
        handler=_get_changes_by_dtcr,
    ),
    Tool(
        name="get_changes_by_harness",
        description=(
            "Every change on a harness family, optionally narrowed to a model "
            "year or program. Use this for \"what changed on the IP harness in "
            "MY28\". This can return many rows — narrow it before asking."
        ),
        parameters=_schema(
            {
                "harness_family": _text("Harness family, e.g. IP, DASH, BODY_LEFT."),
                "model_year": _text("Model year, e.g. 2028."),
                "program": _text("Program, e.g. RU."),
                "limit": _LIMIT,
            },
            required=["harness_family"],
        ),
        handler=_get_changes_by_harness,
    ),
    Tool(
        name="get_change_counts",
        description=(
            "Counts rather than rows: totals plus breakdowns by change type, "
            "object type, harness family, DTCR, most-changed connectors and "
            "most-changed circuits. Use this for \"which harness family has the "
            "most changes\", \"how many changes are there\", or any "
            "most/least/how-many question. Filters narrow what is counted."
        ),
        parameters=_schema(
            {
                "program": _text("Program, e.g. RU."),
                "model_year": _text("Model year, e.g. 2028."),
                "harness_family": _text("Harness family, e.g. IP."),
                "action": _text(
                    "Change type: ADD, DELETE, CHG, COMP CHG or PN CHANGE."
                ),
                "top_n": {
                    "type": "integer",
                    "description": "How many entries per breakdown (default 10).",
                },
            }
        ),
        handler=_get_change_counts,
    ),
    Tool(
        name="get_program_summary",
        description=(
            "SECR and change counts for one vehicle program, with its harness "
            "families, top DTCRs and the SECR numbers involved."
        ),
        parameters=_schema(
            {"program": _text("Program, e.g. RU.")}, required=["program"]
        ),
        handler=_get_program_summary,
    ),
    Tool(
        name="get_model_year_summary",
        description="SECR and change counts for one model year, e.g. 2028.",
        parameters=_schema(
            {"model_year": _text("Model year, e.g. 2028.")},
            required=["model_year"],
        ),
        handler=_get_model_year_summary,
    ),
    Tool(
        name="get_revision_chain",
        description=(
            "The version history of one SECR, oldest first. Use this for "
            "\"how many revisions does D50319A have\"."
        ),
        parameters=_schema(
            {"secr_number": _text("SECR number, e.g. D50319A.")},
            required=["secr_number"],
        ),
        handler=_get_revision_chain,
    ),
    Tool(
        name="get_database_summary",
        description=(
            "What the database holds overall: how many SECRs and changes, and "
            "breakdowns by program, model year and harness family. Use this to "
            "answer \"what is in the database\" or to orient before a narrower "
            "question."
        ),
        parameters=_schema({}),
        handler=_get_database_summary,
    ),
]

TOOLS: Dict[str, Tool] = {tool.name: tool for tool in _TOOL_LIST}


def tool_specs() -> List[Dict[str, Any]]:
    """Every tool in the format Ollama's ``/api/chat`` expects."""
    return [tool.spec() for tool in _TOOL_LIST]


def tool_names() -> List[str]:
    return [tool.name for tool in _TOOL_LIST]


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def call_tool(
    name: str,
    arguments: Optional[Dict[str, Any]] = None,
    *,
    db_path: Optional[Path] = None,
) -> ToolResult:
    """Run one tool call from the model. Never raises.

    A model will occasionally invent a tool name, omit a required argument, or
    pass a stray one. Each of those comes back as a ``ToolResult`` carrying an
    explanation the model can act on, because a raised exception would end the
    conversation where a correction would rescue it.
    """
    arguments = dict(arguments or {})
    tool = TOOLS.get(name)
    if tool is None:
        return ToolResult(
            name=name,
            arguments=arguments,
            error=(
                f"There is no tool called {name!r}. Available tools: "
                + ", ".join(tool_names())
            ),
        )

    allowed = set(tool.parameters.get("properties", {}))
    unexpected = sorted(set(arguments) - allowed)
    if unexpected:
        return ToolResult(
            name=name,
            arguments=arguments,
            error=(
                f"{name} does not take {', '.join(unexpected)}. "
                f"It takes: {', '.join(sorted(allowed)) or 'no arguments'}."
            ),
        )

    missing = [key for key in tool.parameters.get("required", []) if not arguments.get(key)]
    if missing:
        return ToolResult(
            name=name,
            arguments=arguments,
            error=f"{name} requires {', '.join(missing)}.",
        )

    try:
        raw = tool.handler(**arguments, db_path=db_path)
    except Exception as exc:  # noqa: BLE001 - reported to the model, not raised
        return ToolResult(
            name=name,
            arguments=arguments,
            error=f"{name} failed: {exc}",
        )

    data = _jsonable(raw)
    truncated = False
    row_count = 0
    if isinstance(data, list):
        row_count = len(data)
        if row_count > MAX_ROWS:
            data = data[:MAX_ROWS]
            row_count = MAX_ROWS
            truncated = True
    elif isinstance(data, dict):
        # Some tools answer with a mapping rather than rows (list_known_values,
        # the summaries). Reporting 0 for those made a tool that worked look
        # like a tool that returned nothing — in an issue report that is a
        # false lead, and it cost a real investigation. Count what is there.
        row_count = sum(
            len(value) if isinstance(value, (list, dict)) else 1
            for value in data.values()
        )
    elif data not in (None, ""):
        row_count = 1

    return ToolResult(
        name=name,
        arguments=arguments,
        data=data,
        row_count=row_count,
        truncated=truncated,
    )
