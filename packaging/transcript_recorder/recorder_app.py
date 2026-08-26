"""Teams Transcript Recorder — standalone Windows app with a small status GUI.

Records Microsoft Teams Live Captions into markdown transcripts, exactly like
Splice's Meeting Transcripts page. By default they are anonymized: participant
names never reach disk (speakers become Speaker 1..N), filenames carry only a
timestamp, and partially transcribed captions fold into their final sentence.
Every transcript starts with instructions for an AI assistant, so pasting the
file into an LLM produces meeting minutes directly.

Recording real names is opt-in behind a privacy gate: the user must confirm
they told the participants the meeting is being transcribed for minutes and
that permission was granted, signed with their name. The app supplies the
message to send participants, and writes the whole attestation into the
transcript as the compliance record.

The window shows what the recorder is doing (no captions window detected /
recording / paused), and when a meeting ends it offers a button straight to
the saved transcript's folder. Recording needs no interaction: it starts when
a captions window appears and finishes when it closes, then waits for the
next meeting.

NOTE: the anonymization/document logic is vendored from
splice/transcripts/recorder.py (the Splice app). If a bug is fixed there,
port it here and rebuild.
"""

from __future__ import annotations

import os
import re
import sys
import threading
import tkinter as tk
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import uiautomation as auto


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


TRANSCRIPTS_DIR = get_base_dir() / "Transcripts"

# --------------------------------------------------------------------------
# Anonymized transcript document (vendored from splice.transcripts.recorder)
# --------------------------------------------------------------------------

_INLINE_SPEAKER_RE = re.compile(r"^(?P<name>[^:]{1,60}?)\s*:\s*(?P<text>.+)$", re.S)

PARTICIPANT_NOTICE = (
    "Hi all — before we start: I'm going to capture this meeting's live "
    "captions so I can produce written minutes (summary, decisions, and "
    "action items) afterwards.\n\n"
    "What this means:\n"
    "• The captions text is saved, together with who said what.\n"
    "• It is used only to write up the minutes for this meeting and is kept "
    "with our normal project records.\n"
    "• No audio or video is recorded by this tool — captions text only.\n"
    "• If you would rather not be identified by name, tell me and I'll switch "
    "to the anonymized mode, where speakers appear only as \"Speaker 1\", "
    "\"Speaker 2\", and so on.\n\n"
    "If anyone objects, say so now (or message me privately) and I will turn "
    "it off. Thanks!"
)

ATTESTATIONS = (
    ("announced",
     "I told everyone in the meeting that it is being transcribed and that the "
     "transcript will be used to generate a minute report."),
    ("permission_granted",
     "I asked the participants for permission to record their names, and no "
     "one objected."),
)


@dataclass
class Consent:
    """The recording person's privacy attestation for a NAMED recording."""

    announced: bool = False
    permission_granted: bool = False
    attested_by: str = ""
    attested_at: Optional[datetime] = None
    notice_text: str = PARTICIPANT_NOTICE
    notes: str = ""

    @property
    def missing(self) -> List[str]:
        gaps: List[str] = []
        if not self.announced:
            gaps.append("participants have not been told the meeting is being "
                        "transcribed for minutes")
        if not self.permission_granted:
            gaps.append("permission to record names has not been requested and "
                        "granted")
        if not str(self.attested_by).strip():
            gaps.append("the attestation is unsigned (enter your name)")
        return gaps

    @property
    def complete(self) -> bool:
        return not self.missing

    def sign(self, by: str, when: Optional[datetime] = None) -> "Consent":
        self.attested_by = " ".join(str(by).split())
        self.attested_at = when or datetime.now()
        return self


def looks_like_name(text: str) -> bool:
    t = str(text).strip()
    if not t or len(t) > 40:
        return False
    if t[-1] in ".?!,;":
        return False
    if any(ch.isdigit() for ch in t):
        return False
    words = t.split()
    if len(words) > 4:
        return False
    return all(w[0].isupper() for w in words if w[0].isalpha())


class SpeakerAnonymizer:
    def __init__(self) -> None:
        self._aliases: dict[str, str] = {}

    @staticmethod
    def _key(name: str) -> str:
        return " ".join(str(name).split()).casefold()

    def alias(self, name: str) -> str:
        key = self._key(name)
        if key not in self._aliases:
            self._aliases[key] = f"Speaker {len(self._aliases) + 1}"
        return self._aliases[key]

    def known(self, name: str) -> bool:
        return self._key(name) in self._aliases

    @property
    def count(self) -> int:
        return len(self._aliases)


@dataclass
class Entry:
    time: str
    speaker: str
    text: str


@dataclass
class Transcript:
    started: datetime = field(default_factory=datetime.now)
    entries: List[Entry] = field(default_factory=list)
    anonymizer: SpeakerAnonymizer = field(default_factory=SpeakerAnonymizer)
    record_names: bool = False
    consent: Optional[Consent] = None
    _current_speaker: str = ""
    _seen: set = field(default_factory=set)

    def _label(self, name: str) -> str:
        alias = self.anonymizer.alias(name)   # keeps the count and known() memory
        if self.record_names:
            return " ".join(str(name).split())
        return alias

    def add_caption(self, item: str) -> bool:
        item = str(item).strip()
        if not item or item in self._seen:
            return False
        self._seen.add(item)

        if self.anonymizer.known(item) or looks_like_name(item):
            self._current_speaker = self._label(item)
            return False

        speaker = self._current_speaker
        text = item
        m = _INLINE_SPEAKER_RE.match(item)
        if m and (self.anonymizer.known(m.group("name")) or looks_like_name(m.group("name"))):
            speaker = self._label(m.group("name"))
            self._current_speaker = speaker
            text = m.group("text").strip()

        if self.entries:
            last = self.entries[-1]
            if last.speaker == speaker and (
                text.startswith(last.text) or last.text.startswith(text)
            ):
                if len(text) >= len(last.text):
                    last.text = text
                    last.time = datetime.now().strftime("%H:%M:%S")
                return True

        self.entries.append(
            Entry(time=datetime.now().strftime("%H:%M:%S"), speaker=speaker, text=text)
        )
        return True

    def render(self, ended: Optional[datetime] = None) -> str:
        lines = [
            "# Meeting Transcript",
            "",
            "> **How to use this file:** paste the ENTIRE file into an AI "
            "assistant (Copilot, ChatGPT, Claude, ...) and send it — the "
            "instructions the assistant needs are right below.",
            "",
            "**Instructions for the assistant:** produce meeting minutes from "
            "the anonymized transcript that follows: 1) a concise summary of "
            "what was discussed and concluded; 2) decisions made; 3) action "
            "points as a table (action, owner as Speaker N, due date if "
            "mentioned); 4) pending or unresolved items; 5) risks, concerns, "
            "and other relevant information. Keep the Speaker N labels exactly "
            "as written and do not invent names. If a section has no content, "
            'write "None recorded."'
            if not self.record_names else
            "**Instructions for the assistant:** produce meeting minutes from "
            "the transcript that follows: 1) a concise summary of what was "
            "discussed and concluded; 2) decisions made; 3) action points as a "
            "table (action, owner, due date if mentioned); 4) pending or "
            "unresolved items; 5) risks, concerns, and other relevant "
            "information. Use the participant names exactly as written and do "
            'not invent names. If a section has no content, write "None '
            'recorded."',
            "",
            f"**Started:** {self.started.strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Speakers:** {self.anonymizer.count} "
            + ("(recorded by name — see the privacy record below)"
               if self.record_names else
               "(anonymized as Speaker 1..N; names spoken mid-sentence are "
               "not removed)"),
            "",
        ]
        lines += self._privacy_lines()
        lines += ["---", ""]
        for e in self.entries:
            prefix = f"**{e.speaker}** " if e.speaker else ""
            lines.append(f"- **[{e.time}]** {prefix}{e.text}")
        if ended is not None:
            lines += ["", "---", "", f"**Ended:** {ended.strftime('%Y-%m-%d %H:%M:%S')}"]
        return "\n".join(lines) + "\n"

    def _privacy_lines(self) -> List[str]:
        """The privacy record written into every transcript."""
        if not self.record_names:
            return [
                "**Privacy:** anonymized recording — participant names were "
                "never written to disk, so no consent was required.",
                "",
            ]
        c = self.consent or Consent()
        signed = (c.attested_at or self.started).strftime("%Y-%m-%d %H:%M:%S")
        out = [
            "## Privacy record — participant names recorded",
            "",
            "This transcript identifies participants by name. Before recording "
            "started, the person below confirmed:",
            "",
            f"- [{'x' if c.announced else ' '}] {ATTESTATIONS[0][1]}",
            f"- [{'x' if c.permission_granted else ' '}] {ATTESTATIONS[1][1]}",
            "",
            f"**Attested by:** {c.attested_by or 'unknown'}  ",
            f"**Attested at:** {signed}",
            "",
        ]
        if c.notes.strip():
            out += [f"**Notes from the recorder:** {c.notes.strip()}", ""]
        out += [
            "**Notice given to participants** (sent before recording):",
            "",
            "> " + "\n> ".join((c.notice_text or PARTICIPANT_NOTICE).splitlines()),
            "",
            "_Handle this file according to your organisation's personal-data "
            "policy: keep it only as long as the minutes require it, and share "
            "it only with people entitled to see it._",
            "",
        ]
        return out


def _write_atomic(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


# --------------------------------------------------------------------------
# Capture worker
# --------------------------------------------------------------------------

POLL_SECONDS = 1.0
SCAN_SECONDS = 3.0


class SharedState:
    """What the worker reports and the GUI displays."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.status = "scanning"       # scanning | recording
        self.entries = 0
        self.speakers = 0
        self.current_file = ""
        self.last_saved = ""
        # Privacy mode for the NEXT/current meeting. Anonymized until the user
        # completes the consent dialog; reset to anonymized on request.
        self.record_names = False
        self.consent: Optional[Consent] = None


state = SharedState()
stop_event = threading.Event()
pause_event = threading.Event()


def _find_captions_window():
    for w in auto.GetRootControl().GetChildren():
        try:
            if w.Name and "Captions" in w.Name:
                return w
        except Exception:
            continue
    return None


def _extract_text(ctrl, out: list) -> None:
    try:
        if ctrl.ControlTypeName == "TextControl":
            text = ctrl.Name.strip()
            if text:
                out.append(text)
        for child in ctrl.GetChildren():
            _extract_text(child, out)
    except Exception:
        pass


def _record_one_meeting(window) -> None:
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    with state.lock:
        # A named recording needs a complete attestation; anything else is
        # anonymized, so a half-filled consent can never leak names.
        consent = state.consent
        named = bool(state.record_names and consent and consent.complete)
    transcript = Transcript(record_names=named, consent=consent if named else None)
    out_path = TRANSCRIPTS_DIR / f"Meeting_{transcript.started.strftime('%Y-%m-%d_%H-%M')}.md"
    window_name = window.Name
    with state.lock:
        state.status = "recording"
        state.current_file = out_path.name
        state.entries = 0
        state.speakers = 0
    try:
        while not stop_event.is_set():
            if pause_event.is_set():
                stop_event.wait(POLL_SECONDS)
                continue
            if not window.Exists():
                break
            items: list = []
            _extract_text(window, items)
            changed = False
            for item in items:
                if item == window_name:
                    continue
                changed |= transcript.add_caption(item)
            if changed:
                _write_atomic(out_path, transcript.render())
            with state.lock:
                state.entries = len(transcript.entries)
                state.speakers = transcript.anonymizer.count
            stop_event.wait(POLL_SECONDS)
    finally:
        _write_atomic(out_path, transcript.render(ended=datetime.now()))
        with state.lock:
            state.status = "scanning"
            state.last_saved = out_path.name
            state.current_file = ""


def recorder_worker() -> None:
    # COM must be initialized in this thread for UI Automation to work.
    with auto.UIAutomationInitializerInThread():
        while not stop_event.is_set():
            window = _find_captions_window()
            if window is None:
                stop_event.wait(SCAN_SECONDS)
                continue
            _record_one_meeting(window)
            stop_event.wait(SCAN_SECONDS)


# --------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------

BG = "#F4F4F6"
GREEN = "#1F7A33"
ORANGE = "#B96A00"
GRAY = "#5A5A60"

RED = "#A32020"

NO_CAPTIONS_HELP = (
    "In your Teams meeting turn on Live Captions:\n"
    "More → Language and speech → Live captions.\n\n"
    "Captions already ON but still not detected?\n"
    "Separate the captions window from the meeting window\n"
    "(pop the captions out so they are their own window)."
)


def open_consent_dialog(parent) -> None:
    """Privacy gate for named recording.

    Gives the user the message to send participants, then asks them to confirm
    they announced the recording and got permission, signed with their name.
    Only a complete attestation switches the mode — and it is written into the
    transcript as the compliance record.
    """
    win = tk.Toplevel(parent)
    win.title("Record participant names")
    win.configure(bg=BG)
    win.grab_set()

    tk.Label(win, text="Record participant names", bg=BG, fg="#1D1D1F",
             font=("Segoe UI", 12, "bold")).pack(pady=(12, 2), padx=14, anchor="w")
    tk.Label(win, text="Names on disk are personal data. Confirm you have told the "
                       "participants\nand have their permission — your confirmation is "
                       "written into the transcript.",
             bg=BG, fg=GRAY, font=("Segoe UI", 9), justify="left") \
        .pack(padx=14, anchor="w")

    tk.Label(win, text="1 · Send this to the participants", bg=BG, fg="#1D1D1F",
             font=("Segoe UI", 10, "bold")).pack(pady=(12, 2), padx=14, anchor="w")
    notice = tk.Text(win, width=74, height=11, wrap="word", font=("Segoe UI", 9))
    notice.insert("1.0", PARTICIPANT_NOTICE)
    notice.pack(padx=14)

    def copy_notice() -> None:
        parent.clipboard_clear()
        parent.clipboard_append(notice.get("1.0", "end-1c"))
        copy_btn.config(text="✔ Copied — paste it in the meeting chat")

    copy_btn = tk.Button(win, text="Copy message", width=34, command=copy_notice)
    copy_btn.pack(pady=(6, 0))
    tk.Label(win, text="Edit it if you said something different — what is here is what "
                       "the transcript records as the notice given.",
             bg=BG, fg=GRAY, font=("Segoe UI", 8), justify="left") \
        .pack(padx=14, anchor="w")

    tk.Label(win, text="2 · Confirm what you did", bg=BG, fg="#1D1D1F",
             font=("Segoe UI", 10, "bold")).pack(pady=(12, 2), padx=14, anchor="w")
    vars_ = []
    for _key, text in ATTESTATIONS:
        v = tk.BooleanVar(value=False)
        vars_.append(v)
        tk.Checkbutton(win, text=text, variable=v, bg=BG, wraplength=520,
                       justify="left", font=("Segoe UI", 9)) \
            .pack(padx=14, anchor="w")

    row = tk.Frame(win, bg=BG)
    row.pack(padx=14, pady=(8, 0), anchor="w", fill="x")
    tk.Label(row, text="Your name:", bg=BG, font=("Segoe UI", 9)).pack(side="left")
    signer = tk.Entry(row, width=32, font=("Segoe UI", 9))
    signer.pack(side="left", padx=6)

    row2 = tk.Frame(win, bg=BG)
    row2.pack(padx=14, pady=(6, 0), anchor="w", fill="x")
    tk.Label(row2, text="Notes (optional):", bg=BG, font=("Segoe UI", 9)).pack(side="left")
    notes = tk.Entry(row2, width=44, font=("Segoe UI", 9))
    notes.pack(side="left", padx=6)

    problem = tk.Label(win, text="", bg=BG, fg=RED, font=("Segoe UI", 9),
                       wraplength=520, justify="left")
    problem.pack(padx=14, pady=(6, 0), anchor="w")

    def confirm() -> None:
        consent = Consent(
            announced=vars_[0].get(), permission_granted=vars_[1].get(),
            notice_text=notice.get("1.0", "end-1c") or PARTICIPANT_NOTICE,
            notes=notes.get().strip())
        consent.sign(signer.get())
        if not consent.complete:
            problem.config(text="Cannot start: " + "; ".join(consent.missing) + ".")
            return
        with state.lock:
            state.record_names = True
            state.consent = consent
        win.destroy()

    btns = tk.Frame(win, bg=BG)
    btns.pack(pady=(10, 14))
    tk.Button(btns, text="Cancel", width=14, command=win.destroy).pack(side="left", padx=6)
    tk.Button(btns, text="Record with names", width=22, command=confirm) \
        .pack(side="left", padx=6)


def main() -> None:
    threading.Thread(target=recorder_worker, daemon=True).start()

    root = tk.Tk()
    root.title("Teams Transcript Recorder")
    root.geometry("430x420")
    root.resizable(False, False)
    root.configure(bg=BG)

    tk.Label(root, text="Teams Transcript Recorder", bg=BG, fg="#1D1D1F",
             font=("Segoe UI", 14, "bold")).pack(pady=(14, 2))
    mode_lbl = tk.Label(root, text="", bg=BG, font=("Segoe UI", 9, "bold"),
                        justify="center")
    mode_lbl.pack()

    mode_row = tk.Frame(root, bg=BG)
    mode_row.pack(pady=(6, 0))

    def use_names() -> None:
        open_consent_dialog(root)

    def use_anonymized() -> None:
        with state.lock:
            state.record_names = False
            state.consent = None

    names_btn = tk.Button(mode_row, text="Record with names…", width=20,
                          command=use_names)
    names_btn.pack(side="left", padx=6)
    anon_btn = tk.Button(mode_row, text="Back to anonymized", width=20,
                         command=use_anonymized)
    anon_btn.pack(side="left", padx=6)

    status_lbl = tk.Label(root, text="", bg=BG, font=("Segoe UI", 12, "bold"))
    status_lbl.pack(pady=(14, 2))
    detail_lbl = tk.Label(root, text="", bg=BG, fg=GRAY, font=("Segoe UI", 9),
                          justify="center")
    detail_lbl.pack(pady=(0, 8))

    btn_row = tk.Frame(root, bg=BG)
    btn_row.pack(pady=(4, 0))

    def toggle_pause() -> None:
        if pause_event.is_set():
            pause_event.clear()
        else:
            pause_event.set()

    def open_folder() -> None:
        TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(TRANSCRIPTS_DIR))  # type: ignore[attr-defined]

    pause_btn = tk.Button(btn_row, text="Pause recording", width=18,
                          command=toggle_pause, state="disabled")
    pause_btn.pack(side="left", padx=6)
    folder_btn = tk.Button(btn_row, text="Open Transcripts Folder", width=22,
                           command=open_folder, state="disabled")
    folder_btn.pack(side="left", padx=6)

    saved_lbl = tk.Label(root, text="", bg=BG, fg=GREEN, font=("Segoe UI", 9))
    saved_lbl.pack(pady=(10, 0))

    def tick() -> None:
        with state.lock:
            status = state.status
            entries, speakers = state.entries, state.speakers
            current, last = state.current_file, state.last_saved
            named = bool(state.record_names and state.consent
                         and state.consent.complete)
            attester = state.consent.attested_by if named and state.consent else ""

        if named:
            mode_lbl.config(
                text=f"Names ARE being recorded — attested by {attester}",
                fg=ORANGE)
        else:
            mode_lbl.config(
                text="Anonymized: speakers become Speaker 1..N, names are never saved.",
                fg=GRAY)
        # Switching mode mid-meeting would split one conversation across two
        # privacy regimes, so the choice is locked while a meeting records.
        recording_now = status == "recording"
        names_btn.config(state="disabled" if (recording_now or named) else "normal")
        anon_btn.config(state="normal" if (named and not recording_now) else "disabled")

        if status == "recording" and pause_event.is_set():
            status_lbl.config(text="⏸  Paused", fg=ORANGE)
            detail_lbl.config(text="Captions spoken now are NOT being recorded.")
            pause_btn.config(text="Resume recording", state="normal")
        elif status == "recording":
            status_lbl.config(text="●  Recording", fg=GREEN)
            detail_lbl.config(
                text=f"{entries} caption entries · {speakers} speakers\n"
                     f"Saving to {current}")
            pause_btn.config(text="Pause recording", state="normal")
        else:
            status_lbl.config(text="○  No captions window detected", fg=ORANGE)
            detail_lbl.config(text=NO_CAPTIONS_HELP)
            pause_btn.config(text="Pause recording", state="disabled")
            if pause_event.is_set():
                pause_event.clear()

        has_transcripts = bool(last) or (
            TRANSCRIPTS_DIR.is_dir() and any(TRANSCRIPTS_DIR.glob("*.md")))
        folder_btn.config(state="normal" if has_transcripts else "disabled")
        if last:
            saved_lbl.config(
                text=f"✔ Transcript saved: {last}\n"
                     "Open the folder and paste the file into an AI assistant "
                     "for the minutes.")

        root.after(500, tick)

    def on_close() -> None:
        stop_event.set()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    tick()
    root.mainloop()


if __name__ == "__main__":
    main()
