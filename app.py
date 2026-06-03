from __future__ import annotations

import streamlit as st


st.set_page_config(page_title="Engineering Tools Hub", layout="wide")

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
            min-height: 220px;
            box-shadow: 0 8px 16px rgba(26, 43, 60, 0.05);
        }
        .tool-title {
            font-size: 1.2rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
            color: #14324a;
        }
        .tool-desc {
            color: #35526b;
            margin-bottom: 1rem;
        }
        .tool-badge {
            display: inline-block;
            padding: 0.2rem 0.55rem;
            border-radius: 999px;
            font-size: 0.8rem;
            font-weight: 600;
            background: #e8f4ff;
            color: #0b5ea8;
            margin-right: 0.35rem;
            margin-bottom: 0.45rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero">
        <h1 style="margin-bottom: 0.35rem; color: #10273a;">Engineering Data Tools</h1>
        <p style="margin: 0; color: #2f4b62;">
            Select a workflow below to launch either wiring splice generation or DTx report comparison.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

left, right = st.columns(2, gap="large")

with left:
    st.markdown(
        """
        <div class="tool-card">
            <div class="tool-title">Splice Generation</div>
            <div class="tool-desc">
                Build harness configurations, generated connections, print matrix, and interactive sales code validation.
            </div>
            <span class="tool-badge">Complexity</span>
            <span class="tool-badge">OptionPerCkt</span>
            <span class="tool-badge">Output Excel</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.page_link("pages/1_Splice_Generation.py", label="Open Splice Generation", icon="⚡")

with right:
    st.markdown(
        """
        <div class="tool-card">
            <div class="tool-title">DTx Compare Report</div>
            <div class="tool-desc">
                Compare OLD vs NEW DTx reports, review added/removed/modified CNUM and circuits, and download a dashboard workbook.
            </div>
            <span class="tool-badge">OLD vs NEW</span>
            <span class="tool-badge">Change Log</span>
            <span class="tool-badge">Dashboard</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.page_link("pages/2_DTx_Compare_Report.py", label="Open DTx Compare", icon="📊")
