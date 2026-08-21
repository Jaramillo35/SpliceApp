"""Home / overview page — tool cards and shared downloads.

Rendered as the default page by the ``st.navigation`` shell in ``app.py``.
Navigation uses ``st.page_link`` so it participates in the native multipage nav.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).resolve().parent.parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

SPLICE_SAMPLE_INPUT_PATH = APP_DIR / "assets" / "downloads" / "Z913_example_input.xlsx"
DTCR_EXTENSION_ZIP_PATH = APP_DIR / "assets" / "downloads" / "ispeed-dtcr-downloader.zip"

st.markdown(
    """
    <style>
        .hero {
            padding: 1.25rem 1.5rem;
            border-radius: 16px;
            border: 1px solid #d9e4ee;
            background: linear-gradient(135deg, #f3f8fc 0%, #eef6f2 100%);
            margin-bottom: 1.2rem;
        }
        .tool-card {
            border: 1px solid #d6e1ea;
            border-radius: 14px;
            padding: 1rem;
            background: #ffffff;
            min-height: 200px;
            box-shadow: 0 8px 16px rgba(26, 43, 60, 0.05);
        }
        .tool-title { font-size: 1.2rem; font-weight: 700; margin-bottom: 0.5rem; color: #14324a; }
        .tool-desc { color: #35526b; margin-bottom: 1rem; }
        .tool-badge {
            display: inline-block; padding: 0.2rem 0.55rem; border-radius: 999px;
            font-size: 0.8rem; font-weight: 600; background: #e8f4ff; color: #0b5ea8;
            margin-right: 0.35rem; margin-bottom: 0.45rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero">
        <h1 style="margin-bottom: 0.35rem; color: #10273a;">System Engineer Toolkit</h1>
        <p style="margin: 0; color: #2f4b62;">
            Select a workflow to launch wiring splice generation, DTx report comparison,
            the SECR database, or the VBOM risk matrix.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

row1 = st.columns(2, gap="large")

with row1[0]:
    st.markdown(
        """
        <div class="tool-card">
            <div class="tool-title">Splice Generation</div>
            <div class="tool-desc">
                Build harness configurations, generated connections, print matrix, and
                interactive sales code validation from one Complexity + OptionPerCkt workbook.
            </div>
            <span class="tool-badge">Complexity</span>
            <span class="tool-badge">OptionPerCkt</span>
            <span class="tool-badge">Output Excel</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.page_link("pages/1_Splice_Generation.py", label="Open Splice Generation", icon="🔌")
    if SPLICE_SAMPLE_INPUT_PATH.exists():
        st.download_button(
            "Download Example Splice Input",
            data=SPLICE_SAMPLE_INPUT_PATH.read_bytes(),
            file_name="Z913_example_input.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_splice_example_home",
        )

with row1[1]:
    st.markdown(
        """
        <div class="tool-card">
            <div class="tool-title">DTx Compare Report</div>
            <div class="tool-desc">
                Compare OLD vs NEW DTx reports, review added/removed/modified CNUM and
                circuits, optionally tag changes with DTCR#, and generate the compare workbook.
            </div>
            <span class="tool-badge">OLD vs NEW</span>
            <span class="tool-badge">Change Log</span>
            <span class="tool-badge">Dashboard</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.page_link("pages/2_DTx_Compare_Report.py", label="Open DTx Compare Report", icon="📑")

row2 = st.columns(2, gap="large")

with row2[0]:
    st.markdown(
        """
        <div class="tool-card">
            <div class="tool-title">SECR Database</div>
            <div class="tool-desc">
                A searchable history of engineering changes: import SECR workbooks, create
                and update SECRs from DEF compares, browse every change, and ask the local
                assistant about any of it in plain language.
            </div>
            <span class="tool-badge">Create / Update</span>
            <span class="tool-badge">Import</span>
            <span class="tool-badge">Local AI Assistant</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.page_link("ui/pages/secr_database.py", label="Open SECR Database", icon="🗄️")
    st.page_link("ui/pages/secr_assistant.py", label="Ask the Database", icon="💬")

with row2[1]:
    st.markdown(
        """
        <div class="tool-card">
            <div class="tool-title">VBOM Risk Matrix</div>
            <div class="tool-desc">
                Upload VBOM input files and generate the same workbook bundle used by the
                desktop VBOM workflow: master complexity workbook, VIN matrix, and selections.
            </div>
            <span class="tool-badge">DoAll / BuildSpec</span>
            <span class="tool-badge">Harness Complexity</span>
            <span class="tool-badge">Workbook Bundle</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.page_link("pages/5_VBOM_Risk_Matrix.py", label="Open VBOM Risk Matrix", icon="🧮")

with st.container(border=True):
    st.markdown(
        """
        <div class="tool-title">Inline Continuity</div>
        <div class="tool-desc">
            Validate that circuits continue across harness interfaces. Load a Circuit
            Summary and the complexity file for each harness in it; every cavity of every
            inline is decided, and only the exceptions reach you.
        </div>
        <div class="tool-badges">
            <span class="tool-badge">Circuit Summary</span>
            <span class="tool-badge">Harness Complexity</span>
            <span class="tool-badge">Findings Workbook</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.page_link("pages/6_Inline_Continuity.py", label="Open Inline Continuity", icon="🔌")

with st.container(border=True):
    st.markdown(
        """
        <div class="tool-title">HRN Chart Builder</div>
        <div class="tool-desc">
            Batch-convert HRN circuit files with their harness matrix CSV (and optional
            CMP connector map) into styled chart workbooks, named
            {HarnessFamily}_{ModelYear}{Program}_Chart_{date} from the HRN file name.
        </div>
        <span class="tool-badge">Batch Upload</span>
        <span class="tool-badge">Auto-Pairing</span>
        <span class="tool-badge">Supplier Prefixes</span>
        """,
        unsafe_allow_html=True,
    )
    st.page_link("ui/pages/hrn_chart.py", label="Open HRN Chart Builder", icon="📈")

with st.container(border=True):
    st.markdown(
        """
        <div class="tool-title">Meeting Transcripts</div>
        <div class="tool-desc">
            Record Teams Live Captions into an anonymized markdown transcript — speakers
            become Speaker 1..N, names are never written to disk — ready to feed an LLM
            for minutes, action points, and pending items. Capture runs on Windows.
        </div>
        <span class="tool-badge">Teams Captions</span>
        <span class="tool-badge">Anonymized</span>
        <span class="tool-badge">LLM-ready</span>
        """,
        unsafe_allow_html=True,
    )
    st.page_link("ui/pages/meeting_transcripts.py", label="Open Meeting Transcripts", icon="🎙️")

with st.container(border=True):
    st.markdown(
        """
        <div class="tool-title">iSpeed DTCR Downloader</div>
        <div class="tool-desc">
            Download the Chrome extension package used to capture iSpeed DTCR search results,
            attachments, and a DTCR summary CSV in one run.
        </div>
        """,
        unsafe_allow_html=True,
    )
    if DTCR_EXTENSION_ZIP_PATH.exists():
        st.download_button(
            "Download iSpeed DTCR Downloader",
            data=DTCR_EXTENSION_ZIP_PATH.read_bytes(),
            file_name="ispeed-dtcr-downloader.zip",
            mime="application/zip",
            key="download_ispeed_dtcr_extension",
        )
    else:
        st.warning(
            "Chrome extension package not found. "
            "Expected: assets/downloads/ispeed-dtcr-downloader.zip"
        )

    with st.expander("Install and use the extension", expanded=False):
        st.markdown(
            """
### Install

1. Download and unzip the extension.
2. Open `chrome://extensions` in Chrome.
3. Turn on **Developer mode**.
4. Click **Load unpacked**.
5. Select the unzipped `ispeed-dtcr-downloader` folder.
6. Pin the extension from Chrome's Extensions menu.

### What it does
The extension processes the current iSpeed DTCR search results. It skips deleted or
canceled DTCRs, records each Reason for Change, downloads attachments with cleaned
filenames, and creates `DTCR_Summary.csv`.

### How to use it

1. Sign in to iSpeed.
2. Select a Vehicle Program and Build Phase, then click **Search**.
3. With the results visible, click the extension icon.
4. Confirm the DTCR count.
5. Click **Choose folder** and select an empty destination folder.
6. Click **Start download**.
7. Keep both tabs open until the run finishes.

iSpeed can be slow. The extension waits for each detail page and the restored search
results before continuing.
            """
        )
