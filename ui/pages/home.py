"""Home / overview page — tool cards and shared downloads.

Rendered as the default page by the ``st.navigation`` shell in ``app.py``.
Every tool gets the same card component (title, description, badges, then its
links/downloads), laid out two per row in declaration order.
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
TRANSCRIPT_RECORDER_ZIP_PATH = (
    APP_DIR / "assets" / "downloads" / "teams-transcript-recorder.zip"
)

from ui import components

components.hero(
    "System Engineer Toolkit",
    "One home for the wiring-engineering workflows: splice generation, DTx "
    "comparison, the SECR database, VBOM risk matrix, circuit health, HRN "
    "charts, and meeting transcripts.",
)

tool_card = components.tool_card


def splice_generation_extras() -> None:
    st.page_link("pages/1_Splice_Generation.py", label="Open Splice Generation", icon="🔌")
    if SPLICE_SAMPLE_INPUT_PATH.exists():
        st.download_button(
            "Download Example Splice Input",
            data=SPLICE_SAMPLE_INPUT_PATH.read_bytes(),
            file_name="Z913_example_input.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_splice_example_home",
        )


def dtx_extras() -> None:
    st.page_link("pages/2_DTx_Compare_Report.py", label="Open DTx Compare Report", icon="📑")


def secr_extras() -> None:
    st.page_link("ui/pages/secr_database.py", label="Open SECR Database", icon="🗄️")
    st.page_link("ui/pages/secr_assistant.py", label="Ask the Database", icon="💬")


def vbom_extras() -> None:
    st.page_link("pages/5_VBOM_Risk_Matrix.py", label="Open VBOM Risk Matrix", icon="🧮")


def inline_extras() -> None:
    st.page_link("pages/6_Inline_Continuity.py", label="Open Inline Continuity", icon="🔌")


def circuit_health_extras() -> None:
    st.page_link("ui/pages/circuit_health.py", label="Open Circuit Health Check", icon="🩺")


def hrn_extras() -> None:
    st.page_link("ui/pages/hrn_chart.py", label="Open HRN Chart Builder", icon="📈")


def transcripts_extras() -> None:
    st.page_link("ui/pages/meeting_transcripts.py", label="Open Meeting Transcripts", icon="🎙️")
    if TRANSCRIPT_RECORDER_ZIP_PATH.exists():
        st.download_button(
            "Download Standalone Recorder (Windows .exe)",
            data=TRANSCRIPT_RECORDER_ZIP_PATH.read_bytes(),
            file_name="teams-transcript-recorder.zip",
            mime="application/zip",
            key="download_transcript_recorder_kit",
        )
    with st.expander("Run and use the standalone recorder", expanded=False):
        st.markdown(
            """
A lightweight Windows app with a small **status window** and the same
anonymized recording as the Meeting Transcripts page — for coworkers who
don't run Splice. **No install and no Python needed.**

### Run

1. Download and unzip the file above.
2. Double-click **TeamsTranscriptRecorder.exe** — a small window shows the
   recorder status. (The first time, Windows may show a *"Windows protected
   your PC"* prompt — click **More info → Run anyway**.)

### Use

1. In the Teams meeting turn on **Live Captions**
   (More → Language and speech → Live captions).
2. If it says **"No captions window detected"** with captions already on,
   separate (pop out) the captions window from the meeting window.
3. Recording starts when captions are detected and finishes when they close.
   When a transcript is saved, the **Open Transcripts Folder** button lights
   up and takes you straight to the file.
4. **Pause** any time — paused speech is not recorded. Closing the window
   stops the recorder.

Speakers are anonymized to Speaker 1..N — names never reach disk — and every
transcript starts with built-in instructions for an AI assistant, so pasting
the file into an LLM produces the meeting minutes directly.
            """
        )


def ispeed_extras() -> None:
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


TOOLS = [
    {
        "title": "Splice Generation",
        "desc": (
            "Build harness configurations, generated connections, print matrix, and "
            "interactive sales code validation from one Complexity + OptionPerCkt workbook."
        ),
        "badges": ["Complexity", "OptionPerCkt", "Output Excel"],
        "extras": splice_generation_extras,
    },
    {
        "title": "DTx Compare Report",
        "desc": (
            "Compare OLD vs NEW DTx reports, review added/removed/modified CNUM and "
            "circuits, optionally tag changes with DTCR#, and generate the compare workbook."
        ),
        "badges": ["OLD vs NEW", "Change Log", "Dashboard"],
        "extras": dtx_extras,
    },
    {
        "title": "SECR Database",
        "desc": (
            "A searchable history of engineering changes: import SECR workbooks, create "
            "and update SECRs from DEF compares, browse every change, and ask the local "
            "assistant about any of it in plain language."
        ),
        "badges": ["Create / Update", "Import", "Local AI Assistant"],
        "extras": secr_extras,
    },
    {
        "title": "VBOM Risk Matrix",
        "desc": (
            "Upload VBOM input files and generate the same workbook bundle used by the "
            "desktop VBOM workflow: master complexity workbook, VIN matrix, and selections."
        ),
        "badges": ["DoAll / BuildSpec", "Harness Complexity", "Workbook Bundle"],
        "extras": vbom_extras,
    },
    {
        "title": "Inline Continuity",
        "desc": (
            "Validate that circuits continue across harness interfaces. Load a Circuit "
            "Summary and the complexity file for each harness in it; every cavity of every "
            "inline is decided, and only the exceptions reach you."
        ),
        "badges": ["Circuit Summary", "Harness Complexity", "Findings Workbook"],
        "extras": inline_extras,
    },
    {
        "title": "Circuit Health Check",
        "desc": (
            "Holistic missing-circuit detection: option windows with real builds "
            "but no wire, and circuits absent from one inline crossing while live "
            "elsewhere. Auto-clears provable variants; the rest queues for SE "
            "disposition with sign-off gates."
        ),
        "badges": ["Window Coverage", "Route Gaps", "SE Sign-off"],
        "extras": circuit_health_extras,
    },
    {
        "title": "HRN Chart Builder",
        "desc": (
            "Batch-convert HRN circuit files with their harness matrix CSV (and optional "
            "CMP connector map) into styled chart workbooks, named "
            "{HarnessFamily}_{ModelYear}{Program}_Chart_{date} from the HRN file name."
        ),
        "badges": ["Batch Upload", "Auto-Pairing", "Supplier Prefixes"],
        "extras": hrn_extras,
    },
    {
        "title": "Meeting Transcripts",
        "desc": (
            "Record Teams Live Captions into an anonymized markdown transcript — speakers "
            "become Speaker 1..N, names are never written to disk — ready to feed an LLM "
            "for minutes and action points. Also available as a standalone tray exe."
        ),
        "badges": ["Teams Captions", "Anonymized", "LLM-ready"],
        "extras": transcripts_extras,
    },
    {
        "title": "iSpeed DTCR Downloader",
        "desc": (
            "Chrome extension that captures iSpeed DTCR search results, attachments, and "
            "a DTCR summary CSV in one run. Download it here and load it in Chrome."
        ),
        "badges": ["Chrome Extension", "Attachments", "Summary CSV"],
        "extras": ispeed_extras,
    },
]

for i in range(0, len(TOOLS), 2):
    row = st.columns(2, gap="large")
    for col, tool in zip(row, TOOLS[i:i + 2]):
        with col:
            tool_card(tool["title"], tool["desc"], tool["badges"])
            tool["extras"]()
