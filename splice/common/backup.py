"""Backups of the data directory — the one thing that cannot be rebuilt.

Everything else in the toolkit is derivable: an export can be regenerated
from its inputs, an image can be rebuilt from the repo. The data directory
cannot. It holds the SECR database, the Circuit Health baseline, the
applicability workbench and the feedback tickets, and until now there was no
export, no rotation, and no restore. ``docker compose down -v`` — a plausible
thing for a frustrated user to try — deleted all of it permanently.

A backup is a dated ``tar.gz`` of the data directory, written into a
``backups/`` folder inside it (excluded from itself) so it lives on the same
persistent volume and survives a container rebuild. The newest N are kept.

Restore is deliberately two-step: the archive is unpacked next to the live
directory first and only swapped in once it is complete, so a corrupt or
interrupted archive cannot leave the live data half-overwritten. The
displaced live data is kept as one more dated folder, so a restore is itself
undoable.
"""

from __future__ import annotations

import logging
import shutil
import tarfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from splice.config import DATA_DIR

logger = logging.getLogger(__name__)

BACKUP_DIR_NAME = "backups"
KEEP = 10
_STAMP = "%Y%m%d-%H%M%S"
_PREFIX = "splice-data-"
_SUFFIX = ".tar.gz"

#: transient or self-referential things that must not go into an archive
_SKIP_NAMES = {BACKUP_DIR_NAME, "logs", "__pycache__"}
_SKIP_SUFFIXES = {".tmp", ".db-wal", ".db-shm"}


@dataclass(frozen=True)
class Backup:
    path: Path
    created: datetime
    size: int

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def size_text(self) -> str:
        return human_size(self.size)


def human_size(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def backup_dir(data_dir: Optional[Path] = None) -> Path:
    return Path(data_dir or DATA_DIR) / BACKUP_DIR_NAME


def _included(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if any(part in _SKIP_NAMES for part in relative.parts):
        return False
    return path.suffix not in _SKIP_SUFFIXES


def data_size(data_dir: Optional[Path] = None) -> int:
    """Bytes of live data, excluding backups and logs."""
    root = Path(data_dir or DATA_DIR)
    if not root.exists():
        return 0
    return sum(p.stat().st_size for p in root.rglob("*")
               if p.is_file() and _included(p, root))


def create(data_dir: Optional[Path] = None, keep: int = KEEP,
           now: Optional[datetime] = None) -> Backup:
    """Archive the data directory and prune to the newest ``keep``.

    ``now`` names the archive; it is a parameter so a test can make several
    backups without sleeping through the one-second stamp resolution.
    """
    root = Path(data_dir or DATA_DIR)
    target_dir = backup_dir(root)
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime(_STAMP)
    target = target_dir / f"{_PREFIX}{stamp}{_SUFFIX}"
    partial = target.with_suffix(".partial")

    count = 0
    with tarfile.open(partial, "w:gz") as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file() and _included(path, root):
                archive.add(path, arcname=str(path.relative_to(root)))
                count += 1
    partial.replace(target)
    logger.info("Backup %s: %d file(s), %s", target.name, count,
                human_size(target.stat().st_size))
    prune(root, keep)
    return _describe(target)


def list_backups(data_dir: Optional[Path] = None) -> List[Backup]:
    """Newest first."""
    folder = backup_dir(data_dir)
    if not folder.exists():
        return []
    found = [_describe(p) for p in folder.glob(f"{_PREFIX}*{_SUFFIX}")]
    return sorted(found, key=lambda b: b.created, reverse=True)


def prune(data_dir: Optional[Path] = None, keep: int = KEEP) -> int:
    """Delete everything but the newest ``keep``; returns how many went."""
    removed = 0
    for old in list_backups(data_dir)[max(keep, 0):]:
        old.path.unlink(missing_ok=True)
        removed += 1
    return removed


def restore(archive: Path, data_dir: Optional[Path] = None) -> Path:
    """Replace the live data with ``archive``. Returns where the displaced
    live data was kept, so the restore can itself be undone."""
    root = Path(data_dir or DATA_DIR)
    archive = Path(archive)
    if not archive.is_file():
        raise FileNotFoundError(archive)

    staging = root.parent / f"{root.name}.restoring"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    with tarfile.open(archive, "r:gz") as tar:
        _safe_extract(tar, staging)

    # the archive is whole; now move things, keeping what we displace
    keep_dir = backup_dir(root)
    keep_dir.mkdir(parents=True, exist_ok=True)
    displaced = keep_dir / f"replaced-{datetime.now().strftime(_STAMP)}"
    displaced.mkdir()
    for child in root.iterdir():
        if child.name == BACKUP_DIR_NAME:
            continue
        shutil.move(str(child), str(displaced / child.name))
    for child in staging.iterdir():
        shutil.move(str(child), str(root / child.name))
    shutil.rmtree(staging, ignore_errors=True)
    logger.info("Restored %s; previous data kept at %s", archive.name, displaced)
    return displaced


def _safe_extract(tar: tarfile.TarFile, destination: Path) -> None:
    """Refuse members that would land outside ``destination``."""
    destination = destination.resolve()
    for member in tar.getmembers():
        target = (destination / member.name).resolve()
        if destination not in target.parents and target != destination:
            raise ValueError(f"Archive entry escapes the data directory: {member.name}")
    tar.extractall(destination, filter="data")


def _describe(path: Path) -> Backup:
    stamp = path.name[len(_PREFIX):-len(_SUFFIX)]
    try:
        created = datetime.strptime(stamp, _STAMP)
    except ValueError:
        created = datetime.fromtimestamp(path.stat().st_mtime)
    return Backup(path=path, created=created, size=path.stat().st_size)
