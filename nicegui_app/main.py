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

from nicegui import ui

# importing each module registers its route
from nicegui_app.pages import (  # noqa: F401,E402
    ask, circuit_health, downloads, dtx_compare, home, hrn_chart,
    secr, splice_gen, transcripts, vbom,
)


def run() -> None:
    ui.run(
        port=int(os.getenv("SPLICE_NICEGUI_PORT", "8504")),
        title="System Engineer Toolkit",
        favicon="🔌",
        dark=True,
        reload=False,
        show=False,
    )


if __name__ in {"__main__", "__mp_main__"}:
    run()
