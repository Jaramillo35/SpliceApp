"""Zip a packaged kit on demand, instead of committing the archive.

The Windows kits are source an engineer builds into an exe on their own PC.
Committing the zip means a binary in git that goes stale the moment anyone
edits the source it was made from — the transcript recorder's 42 MB archive
was most of the repository, and the copy in git had drifted from what it
claimed to be.

Building it at download time costs milliseconds and cannot drift: the zip is
made from the working tree, so what an engineer unzips on Windows is what the
tests in this repository just ran against.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

PACKAGING = Path(__file__).resolve().parents[2] / "packaging"

#: Never ship these, whatever a kit directory happens to contain.
EXCLUDE_DIRS = {"__pycache__", ".git", "build", "dist", ".pytest_cache",
                "exports", ".venv", "venv", ".idea", ".vscode"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".db", ".db-wal", ".db-shm", ".log"}
EXCLUDE_NAMES = {".DS_Store"}


def _wanted(path: Path) -> bool:
    if any(part in EXCLUDE_DIRS for part in path.parts):
        return False
    return path.suffix not in EXCLUDE_SUFFIXES and path.name not in EXCLUDE_NAMES


def files(kit: str, root: Path | None = None) -> list[Path]:
    """Everything a kit ships, relative to the kit directory."""
    base = (root or PACKAGING) / kit
    if not base.is_dir():
        raise FileNotFoundError(f"No kit named {kit!r} under {base.parent}")
    return sorted(p.relative_to(base) for p in base.rglob("*")
                  if p.is_file() and _wanted(p.relative_to(base)))


def build(kit: str, root: Path | None = None) -> bytes:
    """The kit as a zip, with the kit name as the top-level folder.

    A single top-level folder on purpose: unzipping into a downloads directory
    should make one folder, not scatter twenty files across it.
    """
    base = (root or PACKAGING) / kit
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for relative in files(kit, root):
            archive.write(base / relative, f"{kit}/{relative.as_posix()}")
    return buffer.getvalue()
