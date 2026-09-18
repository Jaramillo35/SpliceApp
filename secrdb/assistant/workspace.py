"""The assistant's workspace: the files its engine tools may run on.

A flat folder. The page saves uploads here and lists them; the tools read from
here by **name**. Nothing else on the machine is reachable: a name is never a
path, only workbooks are accepted, and sizes are capped — cell text from these
files reaches a model, so what gets in is kept deliberate.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ALLOWED_SUFFIXES = (".xls", ".xlsx", ".xlsm")
MAX_FILE_BYTES = 60 * 1024 * 1024
MAX_FILES = 40

_KINDS = (("dtcr", "DTCR report"), ("dtx", "DTx export"))


class WorkspaceError(ValueError):
    """Said to the user as written."""


def default_workspace() -> Path:
    from secrdb.config import DATA_DIR  # noqa: PLC0415
    return Path(DATA_DIR) / "assistant_workspace"


def _root(workspace: Optional[Path]) -> Path:
    root = Path(workspace) if workspace is not None else default_workspace()
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_name(name: str) -> str:
    """The file's own name, made safe to store: no folders, no odd characters."""
    base = Path(str(name or "").replace("\\", "/")).name.strip()
    base = re.sub(r"[^A-Za-z0-9._ ()\-]+", "_", base).strip(" .")
    if not base:
        raise WorkspaceError("The file has no usable name.")
    if Path(base).suffix.lower() not in ALLOWED_SUFFIXES:
        raise WorkspaceError(f"{base}: only Excel workbooks ({', '.join(ALLOWED_SUFFIXES)}) "
                             "can go in the assistant's workspace.")
    return base


def kind_of(name: str) -> str:
    lowered = name.lower()
    if Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
        return "other"
    return next((label for key, label in _KINDS if key in lowered), "workbook")


def resolve(name: str, workspace: Optional[Path] = None) -> Path:
    """A workspace file by name — never a path."""
    root = _root(workspace)
    name = str(name or "").strip()
    if not name or Path(name).name != name:
        raise WorkspaceError(f"{name!r} is not a file name. Use a name from list_workspace_files.")
    path = root / name
    if not path.is_file():
        have = [f["file"] for f in list_files(workspace)]
        raise WorkspaceError(f"No file {name!r} in the workspace. Files: {', '.join(have) or 'none'}")
    return path


def list_files(workspace: Optional[Path] = None) -> List[Dict[str, Any]]:
    root = _root(workspace)
    return [{"file": p.name, "kind": kind_of(p.name),
             "size_kb": round(p.stat().st_size / 1024, 1),
             "added": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")}
            for p in sorted(root.glob("*")) if p.is_file() and not p.name.startswith(".")]


def save_file(name: str, data: bytes, workspace: Optional[Path] = None) -> Dict[str, Any]:
    """Store an upload; a file of the same name is replaced. Returns its listing row."""
    root = _root(workspace)
    stored = safe_name(name)
    if not data:
        raise WorkspaceError(f"{stored} is empty.")
    if len(data) > MAX_FILE_BYTES:
        raise WorkspaceError(f"{stored} is {len(data) // (1024 * 1024)} MB; the limit is "
                             f"{MAX_FILE_BYTES // (1024 * 1024)} MB.")
    existing = {f["file"] for f in list_files(workspace)}
    if stored not in existing and len(existing) >= MAX_FILES:
        raise WorkspaceError(f"The workspace holds {MAX_FILES} files. Remove some first.")
    (root / stored).write_bytes(data)
    return next(f for f in list_files(workspace) if f["file"] == stored)


def delete_file(name: str, workspace: Optional[Path] = None) -> bool:
    try:
        resolve(name, workspace).unlink()
        return True
    except WorkspaceError:
        return False


def clear(workspace: Optional[Path] = None) -> int:
    files = list_files(workspace)
    for f in files:
        delete_file(f["file"], workspace)
    return len(files)
