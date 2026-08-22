"""Teams Transcript Recorder — standalone Windows app with a small status GUI.

Records Microsoft Teams Live Captions into anonymized markdown transcripts,
exactly like Splice's Meeting Transcripts page: participant names never reach
disk (speakers become Speaker 1..N), filenames carry only a timestamp, and
partially transcribed captions fold into their final sentence. Every
transcript starts with instructions for an AI assistant, so pasting the file
into an LLM produces meeting minutes directly.

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
    _current_speaker: str = ""
    _seen: set = field(default_factory=set)

    def add_caption(self, item: str) -> bool:
        item = str(item).strip()
        if not item or item in self._seen:
            return False
        self._seen.add(item)

        if self.anonymizer.known(item) or looks_like_name(item):
            self._current_speaker = self.anonymizer.alias(item)
            return False

        speaker = self._current_speaker
        text = item
        m = _INLINE_SPEAKER_RE.match(item)
        if m and (self.anonymizer.known(m.group("name")) or looks_like_name(m.group("name"))):
            speaker = self.anonymizer.alias(m.group("name"))
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
            'write "None recorded."',
            "",
            f"**Started:** {self.started.strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Speakers:** {self.anonymizer.count} (anonymized as Speaker 1..N; "
            "names spoken mid-sentence are not removed)",
            "",
            "---",
            "",
        ]
        for e in self.entries:
            prefix = f"**{e.speaker}** " if e.speaker else ""
            lines.append(f"- **[{e.time}]** {prefix}{e.text}")
        if ended is not None:
            lines += ["", "---", "", f"**Ended:** {ended.strftime('%Y-%m-%d %H:%M:%S')}"]
        return "\n".join(lines) + "\n"


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
    transcript = Transcript()
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

NO_CAPTIONS_HELP = (
    "In your Teams meeting turn on Live Captions:\n"
    "More → Language and speech → Live captions.\n\n"
    "Captions already ON but still not detected?\n"
    "Separate the captions window from the meeting window\n"
    "(pop the captions out so they are their own window)."
)


def main() -> None:
    threading.Thread(target=recorder_worker, daemon=True).start()

    root = tk.Tk()
    root.title("Teams Transcript Recorder")
    root.geometry("430x330")
    root.resizable(False, False)
    root.configure(bg=BG)

    tk.Label(root, text="Teams Transcript Recorder", bg=BG, fg="#1D1D1F",
             font=("Segoe UI", 14, "bold")).pack(pady=(14, 2))
    tk.Label(root, text="Transcripts are anonymized: speakers become Speaker 1..N,\n"
                        "names are never saved.", bg=BG, fg=GRAY,
             font=("Segoe UI", 9)).pack()

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
