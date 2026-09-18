"""Engine tools: what the assistant may ask of the engineering engines.

The SECR tools answer from a database. The engines work on **files** — DTx
exports, a DTCR report — so these tools work on a *workspace*: a folder the
engineer puts files in (the app's upload, or by hand). The model never sees a
path and never reads a file itself; it names a file from
``list_workspace_files`` and a tool runs the tested engine on it.

All five are read-only: they compute and return rows, and write nothing.
Anything that produces a deliverable (a change workbook, a matching report)
stays a button in the app, where a person presses it.

    from secrdb.assistant.engine_tools import engine_tools, ENGINE_PROMPT
    Assistant(tools=engine_tools(workspace), system_prompt=ENGINE_PROMPT)

Results are capped like the SECR tools', and every row carries the
identifiers the grounding check verifies an answer against.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from secrdb.assistant.tools import Tool, _LIMIT, _clamp, _schema, _text

ENGINE_PROMPT = """\
You help a wiring-harness systems engineer by running engineering tools on the
files in their workspace: DTx exports (every circuit at every connector pin of
every harness family) and DTCR reports (device change requests).

Rules:
1. Answer ONLY from the tools. Never state a circuit, connector (CNUM), harness
   family, DTCR, sales code or count that a tool did not return.
2. Call list_workspace_files first unless the user named exact file names; use
   the file names exactly as listed. OLD is the earlier export, NEW the later.
3. If a tool returns an error or nothing, say so plainly. Do not guess.
4. Be concise, the way an engineer writes: what changed, where (CNUM and pin),
   on which harness family, and how many. Do not list more than about ten rows;
   the full table is shown beneath your answer.
"""

_KINDS = (("dtcr", "DTCR report"), ("dtx", "DTx export"))


def default_workspace() -> Path:
    from secrdb.config import DATA_DIR  # noqa: PLC0415
    return Path(DATA_DIR) / "assistant_workspace"


def _file(workspace: Path, name: str) -> Path:
    """A workspace file by name — never a path: nothing outside the folder."""
    name = str(name or "").strip()
    if not name or Path(name).name != name:
        raise ValueError(f"{name!r} is not a file name. Use a name from list_workspace_files.")
    path = workspace / name
    if not path.is_file():
        have = sorted(p.name for p in workspace.glob("*") if p.is_file())
        raise ValueError(f"No file {name!r} in the workspace. Files: {', '.join(have) or 'none'}")
    return path


def _kind(path: Path) -> str:
    lowered = path.name.lower()
    if path.suffix.lower() not in (".xls", ".xlsx", ".xlsm"):
        return "other"
    return next((label for key, label in _KINDS if key in lowered), "workbook")


def _dtx_rows(path: Path):
    from splice.dtxcircuits.dtx import read_dtx_circuits  # noqa: PLC0415
    return read_dtx_circuits(path.read_bytes(), path.name)


def _frames(workspace: Path, old_file: str, new_file: str):
    from splice.dtx_compare.engine import load_dtx_report  # noqa: PLC0415
    old, new = _file(workspace, old_file), _file(workspace, new_file)
    old_df, _l = load_dtx_report(old.read_bytes(), old.name)
    new_df, _l = load_dtx_report(new.read_bytes(), new.name)
    return old, new, old_df, new_df


def engine_tools(workspace: Optional[Path] = None) -> List[Tool]:
    """The engine tools, bound to one workspace folder."""
    workspace = Path(workspace) if workspace is not None else default_workspace()

    def list_workspace_files(*, db_path=None) -> List[Dict[str, Any]]:
        workspace.mkdir(parents=True, exist_ok=True)
        return [{"file": p.name, "kind": _kind(p), "size_kb": round(p.stat().st_size / 1024, 1)}
                for p in sorted(workspace.glob("*")) if p.is_file() and not p.name.startswith(".")]

    def describe_dtx(file: str, *, db_path=None) -> Dict[str, Any]:
        rows, meta = _dtx_rows(_file(workspace, file))
        families: Dict[str, int] = {}
        for r in rows:
            families[r.harness_family] = families.get(r.harness_family, 0) + 1
        return {"file": file, "program": meta.program, "phase": meta.phase,
                "report_date": meta.report_date, "circuit_rows": len(rows),
                "circuits": len({r.circuit for r in rows}),
                "connectors": len({r.cnum for r in rows if r.cnum}),
                "harness_families": [{"harness_family": f, "circuit_rows": n}
                                     for f, n in sorted(families.items())]}

    def find_circuit(file: str, circuit: str, limit: Any = None, *, db_path=None):
        wanted = str(circuit).strip().upper()
        rows, _meta = _dtx_rows(_file(workspace, file))
        hits = [r for r in rows if r.circuit.upper() == wanted] or \
               [r for r in rows if r.circuit.upper().startswith(wanted)]
        return [{"circuit": r.circuit, "harness_family": r.harness_family, "cnum": r.cnum,
                 "pin": r.pin, "sales_code": r.sales_code, "connector_pn": r.connector_pn,
                 "function": r.function} for r in hits][: _clamp(limit)]

    def find_connector(file: str, cnum: str, limit: Any = None, *, db_path=None):
        wanted = str(cnum).strip().upper()
        rows, _meta = _dtx_rows(_file(workspace, file))
        return [{"cnum": r.cnum, "pin": r.pin, "circuit": r.circuit,
                 "harness_family": r.harness_family, "sales_code": r.sales_code,
                 "connector_pn": r.connector_pn, "function": r.function}
                for r in rows if r.cnum.upper() == wanted][: _clamp(limit)]

    def compare_dtx_exports(old_file: str, new_file: str, harness_family: str = "",
                            limit: Any = None, *, db_path=None) -> Dict[str, Any]:
        from splice.dtx_compare.engine import (  # noqa: PLC0415
            build_all_changes_df, build_family_summary_df, compare_reports)
        old, new, old_df, new_df = _frames(workspace, old_file, new_file)
        results = compare_reports(old_df, new_df)
        changes = build_all_changes_df(results)
        families = build_family_summary_df(changes)
        if harness_family and not changes.empty:
            changes = changes[changes["Harness Family"].str.upper()
                              == harness_family.strip().upper()]
        keep = ["Harness Family", "Change Type", "CNUM", "Pin Number", "Circuit Name",
                "Connector PN", "Wire Gauge", "Sales Code", "Changed Fields", "Change Detail"]
        shown = changes[[c for c in keep if c in changes.columns]].head(_clamp(limit))
        return {"old_file": old.name, "new_file": new.name,
                "counts": {k: int(results[k]) for k in (
                    "added_cnum_count", "removed_cnum_count", "added_circuit_count",
                    "removed_circuit_count", "modified_circuit_count")},
                "by_harness_family": families.drop(columns=["DTCR#s"], errors="ignore")
                                             .to_dict("records"),
                "changes_total": int(len(changes)),
                "changes": shown.fillna("").astype(str).to_dict("records")}

    def match_dtcrs(old_file: str, new_file: str, dtcr_file: str, limit: Any = None,
                    *, db_path=None) -> Dict[str, Any]:
        from splice.dtx_compare.engine import (  # noqa: PLC0415
            generate_dtcr_matching_report, load_dtcr_report)
        old, new = _file(workspace, old_file), _file(workspace, new_file)
        dtcr = _file(workspace, dtcr_file)
        frame = generate_dtcr_matching_report(
            old.read_bytes(), new.read_bytes(), old.name, new.name,
            load_dtcr_report(dtcr.read_bytes(), dtcr.name))["dtcr_matching_df"]
        method = frame["Match Method"].astype(str)
        return {"dtcrs": int(len(frame)), "matched": int((method != "No Match").sum()),
                "unmatched": int((method == "No Match").sum()),
                "rows": frame.fillna("").astype(str).head(_clamp(limit)).to_dict("records")}

    dtx = _text("A DTx export's file name, exactly as list_workspace_files gives it.")
    return [
        Tool("list_workspace_files",
             "List the files the engineer has put in the workspace, with what kind each "
             "looks like (DTx export, DTCR report). Call this first to learn the file names.",
             _schema({}), list_workspace_files),
        Tool("describe_dtx",
             "What one DTx export contains: its vehicle program and build phase (from its own "
             "title block), how many circuit rows, circuits and connectors, and its harness "
             "families. Use it to tell which export is OLD and which is NEW.",
             _schema({"file": dtx}, required=["file"]), describe_dtx),
        Tool("find_circuit",
             "Where a circuit appears in a DTx export: every connector (CNUM) and pin it lands "
             "on, the harness family, and the sales-code condition. A944 also matches A944B.",
             _schema({"file": dtx, "circuit": _text("Circuit name, e.g. K106A."),
                      "limit": _LIMIT}, required=["file", "circuit"]), find_circuit),
        Tool("find_connector",
             "Everything at one connector (CNUM) in a DTx export: each pin, the circuit on it, "
             "the harness family and the sales code.",
             _schema({"file": dtx, "cnum": _text("Connector number, e.g. Q101A."),
                      "limit": _LIMIT}, required=["file", "cnum"]), find_connector),
        Tool("compare_dtx_exports",
             "Compare an OLD and a NEW DTx export: counts of added, removed and modified "
             "circuits and connectors, a breakdown by harness family, and the change rows "
             "(optionally for one harness family).",
             _schema({"old_file": _text("The earlier export's file name."),
                      "new_file": _text("The later export's file name."),
                      "harness_family": _text("Only this harness family, e.g. BODY_LEFT."),
                      "limit": _LIMIT}, required=["old_file", "new_file"]),
             compare_dtx_exports),
        Tool("match_dtcrs",
             "Match a DTCR report's change requests to connectors and harness families using "
             "an OLD and a NEW DTx export. Says how many DTCRs matched and lists each DTCR "
             "with its CNUM, harness family and match method.",
             _schema({"old_file": _text("The earlier export's file name."),
                      "new_file": _text("The later export's file name."),
                      "dtcr_file": _text("The DTCR report's file name."),
                      "limit": _LIMIT}, required=["old_file", "new_file", "dtcr_file"]),
             match_dtcrs),
    ]
