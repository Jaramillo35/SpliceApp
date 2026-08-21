"""Issue recording and export, for a version that is being field-tested.

This release goes to engineers on several programs, on machines nobody can log
into. When something goes wrong there, the only thing that reaches the
developer is what the app managed to write down — so the app writes down a lot,
and gives the user one button to send it.

Three kinds of entry are recorded:

``error``        an exception the app caught, with its traceback
``unanswered``   the assistant could not answer a question, and why
``feedback``     something the user reported by hand

Everything lands in ``issues.jsonl`` in the data directory — one JSON object
per line, so a truncated or partially written file still parses up to the last
good entry. Nothing is ever sent anywhere automatically; export is an explicit
user action.
"""

from __future__ import annotations

import json
import platform
import sys
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from secrdb.config import APP_NAME, DATA_DIR, SECR_DB_PATH

#: Bumped when the app is released. Every issue records it, so a report can be
#: matched to the code it came from.
APP_VERSION = "1.0.6"

KIND_ERROR = "error"
KIND_UNANSWERED = "unanswered"
KIND_FEEDBACK = "feedback"

#: Keeps one runaway loop from filling the disk.
MAX_ISSUES = 2000

#: A traceback is useful; a novel is not.
_MAX_DETAIL_CHARS = 8000


def issues_path() -> Path:
    return DATA_DIR / "issues.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Issue:
    """One recorded problem, question or comment."""

    kind: str
    summary: str
    detail: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    where: str = ""
    at: str = field(default_factory=_now)
    session_id: str = ""
    app_version: str = APP_VERSION
    issue_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, default=str)


def _truncate(text: str) -> str:
    text = str(text or "")
    if len(text) <= _MAX_DETAIL_CHARS:
        return text
    return text[:_MAX_DETAIL_CHARS] + f"\n… truncated ({len(text)} chars total)"


def record(
    kind: str,
    summary: str,
    *,
    detail: str = "",
    context: Optional[Dict[str, Any]] = None,
    where: str = "",
    session_id: str = "",
) -> Issue:
    """Append one issue. Never raises — recording a problem must not create one."""
    issue = Issue(
        kind=kind,
        summary=str(summary)[:500],
        detail=_truncate(detail),
        context=_safe_context(context or {}),
        where=where,
        session_id=session_id,
    )
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with issues_path().open("a", encoding="utf-8") as handle:
            handle.write(issue.to_json() + "\n")
        _trim_if_huge()
    except Exception:  # noqa: BLE001 - diagnostics must never break the app
        pass
    return issue


def record_error(
    exc: BaseException,
    *,
    where: str = "",
    context: Optional[Dict[str, Any]] = None,
    session_id: str = "",
) -> Issue:
    """Record an exception with its traceback."""
    detail = "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    )
    return record(
        KIND_ERROR,
        f"{type(exc).__name__}: {exc}",
        detail=detail,
        context=context,
        where=where,
        session_id=session_id,
    )


def record_unanswered(
    question: str,
    *,
    reason: str = "",
    tools_called: Optional[List[Dict[str, Any]]] = None,
    session_id: str = "",
) -> Issue:
    """Record a question the assistant could not answer.

    These are the most valuable entries in a field test: they say what
    engineers actually want to ask and where the data or the tools fall short.
    """
    return record(
        KIND_UNANSWERED,
        question,
        detail=reason,
        context={"tools_called": tools_called or []},
        where="assistant",
        session_id=session_id,
    )


def record_feedback(
    message: str,
    *,
    where: str = "",
    context: Optional[Dict[str, Any]] = None,
    session_id: str = "",
) -> Issue:
    """Record something the user typed into the report box."""
    return record(
        KIND_FEEDBACK,
        message,
        context=context,
        where=where,
        session_id=session_id,
    )


def _safe_context(context: Dict[str, Any]) -> Dict[str, Any]:
    """Keep the context JSON-safe and free of binary payloads."""
    safe: Dict[str, Any] = {}
    for key, value in context.items():
        if isinstance(value, (bytes, bytearray, memoryview)):
            safe[key] = f"<{len(bytes(value))} bytes>"
        elif isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value
        else:
            try:
                json.dumps(value, default=str)
                safe[key] = value
            except Exception:  # noqa: BLE001
                safe[key] = str(value)
    return safe


def _trim_if_huge() -> None:
    path = issues_path()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:  # noqa: BLE001
        return
    if len(lines) <= MAX_ISSUES:
        return
    path.write_text("\n".join(lines[-MAX_ISSUES:]) + "\n", encoding="utf-8")


def load_issues(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Every recorded issue, newest last. Unparseable lines are skipped, not fatal."""
    path = issues_path()
    if not path.is_file():
        return []
    issues: List[Dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                issues.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except Exception:  # noqa: BLE001
        return issues
    return issues[-limit:] if limit else issues


def clear_issues() -> int:
    """Delete the recorded issues. Returns how many were removed."""
    path = issues_path()
    count = len(load_issues())
    try:
        path.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        return 0
    return count


# ---------------------------------------------------------------------------
# Environment snapshot
# ---------------------------------------------------------------------------

def environment() -> Dict[str, Any]:
    """What was running, so a report can be reproduced.

    Deliberately excludes usernames and file paths outside the app's own data
    directory — enough to debug, not a survey of the engineer's machine.
    """
    info: Dict[str, Any] = {
        "app": APP_NAME,
        "app_version": APP_VERSION,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "captured_at": _now(),
    }
    for name in ("streamlit", "pandas", "altair", "openpyxl"):
        try:
            import importlib.metadata as metadata

            info[name] = metadata.version(name)
        except Exception:  # noqa: BLE001
            info[name] = "unknown"
    info.update(database_state())
    return info


def database_state() -> Dict[str, Any]:
    """Size and shape of the database — usually the first question about a bug."""
    state: Dict[str, Any] = {
        "database_exists": SECR_DB_PATH.is_file(),
        "database_size_bytes": (
            SECR_DB_PATH.stat().st_size if SECR_DB_PATH.is_file() else 0
        ),
    }
    if not state["database_exists"]:
        return state
    try:
        from secrdb.core.secr import db as secr_db

        with secr_db.connect() as conn:
            state["schema_version"] = conn.execute(
                "PRAGMA user_version"
            ).fetchone()[0]
            for table in ("secr", "secr_change", "secr_source_file"):
                state[f"{table}_rows"] = conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
    except Exception as exc:  # noqa: BLE001 - a broken database is the bug
        state["database_error"] = str(exc)
    return state


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def build_report(note: str = "", session_id: str = "") -> Dict[str, Any]:
    """The whole picture: environment, counts, and every recorded issue."""
    issues = load_issues()
    counts: Dict[str, int] = {}
    for issue in issues:
        kind = str(issue.get("kind", "unknown"))
        counts[kind] = counts.get(kind, 0) + 1
    return {
        "report_version": 1,
        "generated_at": _now(),
        "session_id": session_id,
        "user_note": note,
        "environment": environment(),
        "issue_counts": counts,
        "issue_total": len(issues),
        "issues": issues,
    }


def export_bytes(note: str = "", session_id: str = "") -> bytes:
    """The report as pretty JSON — one file the user attaches to an email."""
    report = build_report(note=note, session_id=session_id)
    return json.dumps(report, indent=2, ensure_ascii=False, default=str).encode(
        "utf-8"
    )


def export_filename() -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"SECR_Database_issue_report_{stamp}.json"
