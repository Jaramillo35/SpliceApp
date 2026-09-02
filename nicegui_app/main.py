"""Splice on NiceGUI — entry point.

    python -m nicegui_app            # http://localhost:8504

Engines are the same `splice`/`secrdb` packages the Streamlit app uses; this
process can run alongside it (Streamlit :8501/:8502, NiceGUI :8504) during
the migration.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nicegui import app, ui

from splice import version
from splice.common.logging import configure
from splice.config import DATA_DIR

# The engines have logged properly all along; nothing in this process ever
# gave those records a handler, so every warning was discarded. Now they go
# to the console and to a rotating file the Admin page can show.
configure(log_dir=DATA_DIR / "logs")

# importing each module registers its route
from nicegui_app.pages import (  # noqa: F401,E402
    admin, ask, circuit_applicability, circuit_health, downloads, dtx_compare,
    harness_complexity, home, hrn_chart, secr, splice_gen, transcripts, vbom,
)


@app.get("/version")
def version_route() -> dict:
    """Machine-readable identity, for scripts and for the health probe."""
    return version.current().as_dict()


def run() -> None:
    ui.run(
        port=int(os.getenv("SPLICE_NICEGUI_PORT", "8504")),
        title="System Engineer Toolkit",
        favicon="🔌",
        dark=True,
        reload=False,
        show=False,
        # per-user storage (rail identity, preferences); the secret only
        # signs the browser cookie, nothing sensitive is stored
        storage_secret=os.getenv("SPLICE_STORAGE_SECRET", "splice-toolkit"),
    )


if __name__ in {"__main__", "__mp_main__"}:
    run()
