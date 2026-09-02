"""What ran, when, by whom — the feed behind the Overview's "Continue" list.

One JSON line per completed engine run, appended by the UI's engine runner
so no page has to remember to log. Read newest-first, bounded, tolerant of
a truncated last line.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from splice.config import DATA_DIR

logger = logging.getLogger(__name__)

ACTIVITY_PATH = DATA_DIR / "activity.jsonl"
KEEP = 500


def record(tool: str, route: str, summary: str, *, by: str = "",
           context: str = "", path: Optional[Path] = None) -> None:
    """Append one run. Never raises — a log must not break a workflow."""
    target = Path(path or ACTIVITY_PATH)
    entry = {"at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "tool": tool,
             "route": route, "summary": summary, "by": by, "context": context}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
        _trim(target)
    except Exception as exc:  # noqa: BLE001 — logging must never block a run
        logger.warning("Could not record activity: %s", exc)


def recent(limit: int = 20, path: Optional[Path] = None) -> list[dict]:
    """Newest first."""
    target = Path(path or ACTIVITY_PATH)
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read activity: %s", exc)
        return []
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
        if len(out) >= limit:
            break
    return out


def latest_by_tool(path: Optional[Path] = None) -> dict[str, dict]:
    """The most recent run of each tool — what "Continue" shows."""
    seen: dict[str, dict] = {}
    for entry in recent(KEEP, path):
        seen.setdefault(entry.get("route", ""), entry)
    return seen


def _trim(target: Path) -> None:
    lines = target.read_text(encoding="utf-8").splitlines()
    if len(lines) > KEEP * 2:
        target.write_text("\n".join(lines[-KEEP:]) + "\n", encoding="utf-8")
