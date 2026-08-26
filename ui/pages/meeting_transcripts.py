"""Meeting Transcripts: record Teams Live Captions into anonymized markdown.

The page is thin: a process-wide :class:`splice.transcripts.recorder.Recorder`
does the work on a background thread, so recording keeps running while other
Splice pages are used. Capture needs Windows (the captions are read from the
Teams window on this machine's screen); browsing and downloading previously
saved transcripts works everywhere.

Transcripts are anonymized by default — speakers become "Speaker N" and no
name reaches disk — so a file can be pasted into an LLM to produce meeting
minutes without disclosing who attended. Recording real names is opt-in and
gated on a privacy attestation (see :data:`splice.transcripts.recorder.Consent`),
which the transcript then carries as its compliance record.
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from splice.common.errors import SpliceError
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
                     width="stretch",
                     help="Available on the Windows install of Splice")
        col_b.button("⏹ Finish transcript", disabled=True, width="stretch",
                     help="Available on the Windows install of Splice")
    else:
        _render_controls(recorder)

    _render_library()
    _render_minutes_help()


def _render_consent_gate(recorder: rec.Recorder) -> None:
    """Opt-in to recording real names, gated on a privacy attestation.

    The engine refuses a named recording without a complete attestation; this
    form collects it and hands the user the notice to send participants.
    """
    with st.expander("🪪 Record participant names instead (needs permission)"):
        st.caption(
            "Names on disk are personal data. Send the participants the notice "
            "below and confirm you did — your confirmation, your name, the "
            "time, and this exact notice are written into the transcript as "
            "the compliance record."
        )
        st.markdown("**1 · Send this to the participants**")
        notice = st.text_area("Notice", value=rec.PARTICIPANT_NOTICE, height=200,
                              key="mt_notice", label_visibility="collapsed")
        st.caption("Edit it if you said something different — what is here is "
                   "what the transcript records as the notice given.")
        st.markdown("**2 · Confirm what you did**")
        checks = [st.checkbox(text, key=f"mt_att_{key}")
                  for key, text in rec.ATTESTATIONS]
        signer = st.text_input("Your name (signs the attestation)", key="mt_signer")
        notes = st.text_input("Notes (optional — e.g. who agreed, or who opted out)",
                              key="mt_notes")
        if st.button("▶ Start recording with names", width="stretch"):
            consent = rec.Consent(
                announced=checks[0], permission_granted=checks[1],
                notice_text=notice or rec.PARTICIPANT_NOTICE, notes=notes or "")
            consent.sign(signer or "")
            try:
                recorder.start(record_names=True, consent=consent)
            except SpliceError as exc:
                st.error(str(exc))
                return
            st.rerun(scope="fragment")


@st.fragment(run_every=2)
def _render_controls(recorder: rec.Recorder) -> None:
    status = recorder.status()
    state = status["state"]

    col_a, col_b, col_state = st.columns([1, 1, 2])

    with col_a:
        if state in ("idle", "error"):
            if st.button("▶ Start recording", type="primary", width="stretch"):
                recorder.start()
                st.rerun(scope="fragment")
            _render_consent_gate(recorder)
        elif state == "waiting":
            if st.button("✕ Cancel", width="stretch"):
                recorder.stop()
                st.rerun(scope="fragment")
        elif state == "recording":
            if st.button("⏸ Pause", width="stretch"):
                recorder.pause()
                st.rerun(scope="fragment")
        elif state == "paused":
            if st.button("▶ Resume", type="primary", width="stretch"):
                recorder.resume()
                st.rerun(scope="fragment")

    with col_b:
        if state in ("recording", "paused"):
            if st.button("⏹ Finish transcript", width="stretch"):
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
    if head_r.button("📂 Open transcripts folder", width="stretch"):
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
