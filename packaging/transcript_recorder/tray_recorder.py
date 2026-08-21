"""Teams Transcript Recorder — standalone Windows tray app.

Sits in the system tray and records Microsoft Teams Live Captions into
anonymized markdown transcripts, exactly like Splice's Meeting Transcripts
page: participant names never reach disk (speakers become Speaker 1..N),
filenames carry only a timestamp, and partially transcribed captions fold
into their final sentence.

It waits for a Teams captions window, records until the captions close, saves
the transcript to a "Transcripts" folder next to the exe, then waits for the
next meeting — no interaction needed. Tray menu: Pause/Resume, Open
Transcripts, Exit.

NOTE: the anonymization/document logic is vendored from
splice/transcripts/recorder.py (the Splice app). If a bug is fixed there,
port it here and rebuild.
"""

from __future__ import annotations

import os
import re
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PIL import Image, ImageDraw
from pystray import Icon, Menu, MenuItem

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
# Capture loop
# --------------------------------------------------------------------------

POLL_SECONDS = 1.0
SCAN_SECONDS = 5.0

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
            stop_event.wait(POLL_SECONDS)
    finally:
        _write_atomic(out_path, transcript.render(ended=datetime.now()))


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
# Tray UI
# --------------------------------------------------------------------------

def make_icon_image() -> Image.Image:
    img = Image.new("RGB", (64, 64), color=(10, 102, 208))
    draw = ImageDraw.Draw(img)
    draw.ellipse((18, 10, 46, 40), fill=(255, 255, 255))       # mic head
    draw.rectangle((29, 40, 35, 50), fill=(255, 255, 255))     # mic stem
    draw.rectangle((22, 52, 42, 56), fill=(255, 255, 255))     # base
    return img


def toggle_pause(icon, item) -> None:
    if pause_event.is_set():
        pause_event.clear()
    else:
        pause_event.set()


def open_transcripts(icon, item) -> None:
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    os.startfile(str(TRANSCRIPTS_DIR))  # type: ignore[attr-defined]


def quit_app(icon, item) -> None:
    stop_event.set()
    icon.stop()


def main() -> None:
    threading.Thread(target=recorder_worker, daemon=True).start()
    icon = Icon(
        "Teams Transcript Recorder",
        make_icon_image(),
        "Teams Transcript Recorder (anonymized)",
        menu=Menu(
            MenuItem(
                lambda item: "Resume recording" if pause_event.is_set() else "Pause recording",
                toggle_pause,
            ),
            MenuItem("Open Transcripts", open_transcripts),
            MenuItem("Exit", quit_app),
        ),
    )
    icon.run()


if __name__ == "__main__":
    main()
