"""What is running: version, commit, build time.

Until now nothing in the toolkit could answer that. ``pyproject.toml`` has
said 0.1.0 from the start, every image is tagged 0.1.0, and the UI showed
nothing — so a bug report could not say what it was reporting against, and
"do I have the latest?" had no honest answer.

Three sources, in order of trust:

1. **Build stamps** — ``SPLICE_GIT_SHA`` / ``SPLICE_BUILD_DATE`` baked into
   the image by the Dockerfile. Authoritative for a deployed container, where
   there is no ``.git`` to ask.
2. **The working tree** — ``git`` at import time, for a developer checkout.
3. **The package version** alone, when neither is available.

The result says which source it came from, because "0.1.0" from a build
stamp and "0.1.0" from a fallback mean different things.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

PACKAGE_VERSION = "0.1.0"

FROM_BUILD = "build stamp"
FROM_GIT = "working tree"
FROM_PACKAGE = "package only"

_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class VersionInfo:
    version: str
    sha: str = ""
    branch: str = ""
    built: str = ""
    source: str = FROM_PACKAGE
    dirty: bool = False

    @property
    def short_sha(self) -> str:
        return self.sha[:7]

    @property
    def label(self) -> str:
        """``0.1.0 (2aed00a)`` — what the footer shows."""
        core = self.version
        if self.sha:
            core += f" ({self.short_sha}{'+' if self.dirty else ''})"
        return core

    def as_dict(self) -> dict:
        data = asdict(self)
        data["label"] = self.label
        data["short_sha"] = self.short_sha
        return data


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=_ROOT, capture_output=True, text=True,
            timeout=3, check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def read() -> VersionInfo:
    """Resolve once; callers cache the result."""
    sha = os.getenv("SPLICE_GIT_SHA", "").strip()
    built = os.getenv("SPLICE_BUILD_DATE", "").strip()
    version = os.getenv("SPLICE_VERSION", "").strip() or PACKAGE_VERSION
    branch = os.getenv("SPLICE_GIT_BRANCH", "").strip()
    if sha and sha.lower() != "unknown":
        return VersionInfo(version=version, sha=sha, branch=branch,
                           built=built, source=FROM_BUILD)

    if (_ROOT / ".git").exists():
        sha = _git("rev-parse", "HEAD")
        if sha:
            branch = _git("rev-parse", "--abbrev-ref", "HEAD")
            dirty = bool(_git("status", "--porcelain"))
            stamp = _git("log", "-1", "--format=%cI")
            return VersionInfo(version=version, sha=sha, branch=branch,
                               built=stamp, source=FROM_GIT, dirty=dirty)

    return VersionInfo(version=version, source=FROM_PACKAGE)


_CACHED: VersionInfo | None = None


def current() -> VersionInfo:
    global _CACHED
    if _CACHED is None:
        _CACHED = read()
    return _CACHED


