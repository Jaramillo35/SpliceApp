"""Meeting Transcripts: record Teams Live Captions into anonymized markdown.

The page is thin: a process-wide :class:`splice.transcripts.recorder.Recorder`
does the work on a background thread, so recording keeps running while other
Splice pages are used. Capture needs Windows (the captions are read from the
Teams window on this machine's screen); browsing and downloading previously
saved transcripts works everywhere.

Transcripts never contain participant names — speakers are anonymized to
"Speaker N" — so a file can be pasted into an LLM to produce meeting minutes
without disclosing who attended.
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from splice.transcripts import recorder as rec

MINUTES_PROMPT = """You are given an anonymized meeting transcript (speakers are \
labeled Speaker 1..N). Write meeting minutes with these sections:

1. **Summary** — 5-10 sentences covering what the meeting was about and what was concluded.
2. **Decisions** — every decision made, one bullet each.
3. **Action points** — table with columns: action, owner (Speaker N), due date if mentioned.
4. **Pending items** — topics raised but not resolved, with what is blocking each.
5. **Risks / concerns** — anything flagged as a risk, worry, or open question.

Keep speaker labels as-is (Speaker 1, Speaker 2, ...). Do not invent names. \
If a section has no content, write "None recorded."

Transcript follows:
"""


@st.cache_resource
def get_recorder() -> rec.Recorder:
    return rec.Recorder()


def render() -> None:
    st.title("Meeting Transcripts")
    st.caption(
        "Records Microsoft Teams **Live Captions** into a markdown transcript. "
        "Participant names are replaced with Speaker 1..N — the name mapping is "
        "kept only in memory and never written to disk."
    )

    recorder = get_recorder()

    if not rec.CAPTURE_AVAILABLE:
        st.info(
            "Recording is available on the **Windows** install of Splice, where "
            "the Teams meeting is on screen. Saved transcripts can still be "
            "browsed below.",
            icon="🪟",
        )
        col_a, col_b, _ = st.columns([1, 1, 2])
        col_a.button("▶ Start recording", type="primary", disabled=True,
                     use_container_width=True,
                     help="Available on the Windows install of Splice")
        col_b.button("⏹ Finish transcript", disabled=True, use_container_width=True,
                     help="Available on the Windows install of Splice")
    else:
        _render_controls(recorder)

    _render_library()
    _render_minutes_help()


@st.fragment(run_every=2)
def _render_controls(recorder: rec.Recorder) -> None:
    status = recorder.status()
    state = status["state"]

    col_a, col_b, col_state = st.columns([1, 1, 2])

    with col_a:
        if state in ("idle", "error"):
            if st.button("▶ Start recording", type="primary", use_container_width=True):
                recorder.start()
                st.rerun(scope="fragment")
        elif state == "waiting":
            if st.button("✕ Cancel", use_container_width=True):
                recorder.stop()
                st.rerun(scope="fragment")
        elif state == "recording":
            if st.button("⏸ Pause", use_container_width=True):
                recorder.pause()
                st.rerun(scope="fragment")
        elif state == "paused":
            if st.button("▶ Resume", type="primary", use_container_width=True):
                recorder.resume()
                st.rerun(scope="fragment")

    with col_b:
        if state in ("recording", "paused"):
            if st.button("⏹ Finish transcript", use_container_width=True):
                recorder.stop()
                st.rerun(scope="fragment")

    with col_state:
        if state == "waiting":
            st.status("Waiting for a Teams captions window… turn on Live Captions "
                      "in the meeting (More > Language and speech > Live captions).",
                      state="running")
        elif state in ("recording", "paused"):
            m1, m2 = st.columns(2)
            m1.metric("Caption entries", status["entries"])
            m2.metric("Speakers", status["speakers"])
            if state == "paused":
                st.warning("Paused — captions spoken now are NOT being recorded.",
                           icon="⏸")
        elif state == "error":
            st.error(f"Recorder error: {status['error']}")
        else:
            st.caption("Not recording. Start before or during a meeting; the "
                       "recorder waits for the captions window to appear.")

    if state in ("recording", "paused") and status["tail"]:
        with st.expander("Live preview (anonymized)", expanded=True):
            for line in status["tail"]:
                st.text(line)


def _render_library() -> None:
    head_l, head_r = st.columns([3, 1])
    head_l.subheader("Saved transcripts")
    if head_r.button("📂 Open transcripts folder", use_container_width=True):
        try:
            rec.open_transcripts_folder()
        except Exception:
            st.warning("Could not open a file manager on this machine. "
                       f"Transcripts are in: `{rec.TRANSCRIPTS_DIR}`")
    st.caption(f"Folder: `{rec.TRANSCRIPTS_DIR}`")

    files = rec.list_transcripts()
    if not files:
        st.caption("No transcripts yet.")
        return
    for path in files:
        stat = path.stat()
        col_name, col_meta, col_dl = st.columns([3, 2, 1])
        col_name.markdown(f"**{path.stem}**")
        col_meta.caption(
            f"{stat.st_size / 1024:.0f} KB · "
            f"{datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')}"
        )
        col_dl.download_button(
            "Download",
            data=path.read_text(encoding="utf-8"),
            file_name=path.name,
            mime="text/markdown",
            key=f"dl_{path.name}",
        )


def _render_minutes_help() -> None:
    with st.expander("Turn a transcript into meeting minutes (LLM prompt)"):
        st.markdown(
            "Every transcript **already starts with instructions for the "
            "assistant** — just paste the whole file into your LLM of choice "
            "and send it. The transcript is anonymized, so no participant "
            "names leave your machine with it.\n\n"
            "For older transcripts without the embedded instructions, use "
            "this prompt followed by the file's contents:"
        )
        st.code(MINUTES_PROMPT, language=None)


render()
