"""Package the extension into the zip the Splice Downloads page serves.

Source of truth is this folder; the archive is a build artifact. Run the
helper tests first — the build refuses to package a failing extension.
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET = HERE.parents[1] / "assets" / "downloads" / "ispeed-dtcr-downloader.zip"
#: everything the browser loads, in a stable order so the zip is reproducible
FILES = ["manifest.json", "background.js", "dashboard.html", "dashboard.css",
         "dashboard.js", "shared.js", "test-shared.js", "README.md",
         "assets/logo.png"]


def main() -> int:
    result = subprocess.run([_node(), "test-shared.js"], cwd=HERE)
    if result.returncode:
        print("Helper tests failed; not packaging.", file=sys.stderr)
        return result.returncode

    missing = [name for name in FILES if not (HERE / name).is_file()]
    if missing:
        print(f"Missing from the source folder: {missing}", file=sys.stderr)
        return 1

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(TARGET, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            archive.write(HERE / name, arcname=name)
    print(f"Packaged {len(FILES)} files into {TARGET}")
    return 0


def _node() -> str:
    return "node"


if __name__ == "__main__":
    raise SystemExit(main())
