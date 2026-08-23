"""System Engineer Toolkit — Streamlit entry point.

This file is intentionally thin: it configures the page, shows the shared logo,
and registers the pages with ``st.navigation``. All workflow UI lives in the
page modules (``pages/`` and ``ui/pages/``); all business logic lives in the
``splice`` package. Nothing in this file imports an engine.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from splice.common.logging import configure as configure_logging

st.set_page_config(page_title="System Engineer Toolkit", layout="wide")
configure_logging()

APP_DIR = Path(__file__).resolve().parent
LOGO_PATH = APP_DIR / "assets" / "versigent_logo_horizontal.jpg"

if LOGO_PATH.exists():
    st.logo(str(LOGO_PATH))

pages = [
    st.Page("ui/pages/home.py", title="Home", icon="🏠", default=True),
    st.Page("pages/1_Splice_Generation.py", title="Splice Generation", icon="🔌"),
    st.Page("pages/2_DTx_Compare_Report.py", title="DTx Compare Report", icon="📑"),
    st.Page("ui/pages/secr_database.py", title="SECR Database", icon="🗄️"),
    st.Page("ui/pages/secr_assistant.py", title="Ask the Database", icon="💬"),
    st.Page("pages/5_VBOM_Risk_Matrix.py", title="VBOM Risk Matrix", icon="🧮"),
    st.Page("pages/6_Inline_Continuity.py", title="Inline Continuity", icon="🔌"),
    st.Page("ui/pages/circuit_health.py", title="Circuit Health Check", icon="🩺"),
    st.Page("ui/pages/hrn_chart.py", title="HRN Chart Builder", icon="📈"),
    st.Page("ui/pages/meeting_transcripts.py", title="Meeting Transcripts", icon="🎙️"),
]

st.navigation(pages).run()
