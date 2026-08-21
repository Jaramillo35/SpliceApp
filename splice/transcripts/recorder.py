"""Background recorder for Teams Live Captions with speaker anonymization.

Windows only at capture time: the caption text is read from the Teams Live
Captions window through UI Automation, which requires the meeting to be on
this machine's screen. Everything else in this module (anonymization, the
transcript document model) is platform-neutral and unit-tested.

Privacy model
-------------
Participant names are never written to disk. Every name the captions expose is
mapped, in memory only, to a stable alias ("Speaker 1", "Speaker 2", ...) for
the duration of the recording; the mapping dies with the recording. Filenames
carry only a timestamp — not the meeting title, which for 1:1 calls contains a
participant's name. Names spoken *inside* a sentence cannot be detected
reliably and are kept verbatim; the transcript header states that caveat.

Teams renders each caption as "<display name>" and "<text>" (sometimes joined
as "name: text"), and re-renders a caption while the sentence is still being
transcribed. The recorder therefore:

* treats a short title-cased line with no sentence punctuation as a speaker
  label (and any exact repeat of a previously seen label as one, always),
* replaces the previous entry when a new caption from the same speaker merely
  extends it, so partially-transcribed sentences do not pile up,
* rewrites the transcript file atomically on change, so the on-disk file is
  always a clean, complete document.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from splice.config import DATA_DIR

TRANSCRIPTS_DIR = Path(os.getenv("SPLICE_TRANSCRIPTS_DIR", str(DATA_DIR / "transcripts")))

try:  # Windows only; the module stays importable everywhere.
    import uiautomation as _auto
    CAPTURE_AVAILABLE = True
except Exception:  # pragma: no cover - exercised only off-Windows
    _auto = None
    CAPTURE_AVAILABLE = False

#: "name: text" captions. The name part is validated by looks_like_name().
_INLINE_SPEAKER_RE = re.compile(r"^(?P<name>[^:]{1,60}?)\s*:\s*(?P<text>.+)$", re.S)


def looks_like_name(text: str) -> bool:
    """Heuristic for a standalone speaker label rendered by Teams captions:
    short, at most four words, title-cased, no digits, no sentence
    punctuation."""
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
    """Stable in-memory mapping from display names to "Speaker N" aliases."""

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
    speaker: str  # alias, or '' when no speaker context exists
    text: str


@dataclass
class Transcript:
    """The anonymized document: entries plus the logic that folds partially
    transcribed captions into their final form."""

    started: datetime = field(default_factory=datetime.now)
    entries: List[Entry] = field(default_factory=list)
    anonymizer: SpeakerAnonymizer = field(default_factory=SpeakerAnonymizer)
    _current_speaker: str = ""
    _seen: set = field(default_factory=set)

    def add_caption(self, item: str) -> bool:
        """Feed one raw caption item. Returns True when the document changed."""
        item = str(item).strip()
        if not item or item in self._seen:
            return False
        self._seen.add(item)

        # A standalone speaker label: remember the alias, write nothing.
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

        # Fold a caption that extends (or finalizes) the previous one.
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

    def tail(self, n: int = 10) -> List[str]:
        out = []
        for e in self.entries[-n:]:
            prefix = f"{e.speaker}: " if e.speaker else ""
            out.append(f"[{e.time}] {prefix}{e.text}")
        return out


def _write_atomic(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


class Recorder:
    """Owns the capture thread. One instance lives for the Streamlit process
    (see the Meeting Transcripts page), so recording survives page reruns and
    navigation."""

    POLL_SECONDS = 1.0
    SCAN_SECONDS = 5.0

    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._lock = threading.Lock()
        self.state = "idle"  # idle | waiting | recording | paused | error
        self.error: str = ""
        self.transcript: Optional[Transcript] = None
        self.output_path: Optional[Path] = None

    # -- public API ---------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running or not CAPTURE_AVAILABLE:
            return
        self._stop.clear()
        self._paused.clear()
        self.state = "waiting"
        self.error = ""
        self.transcript = None
        self.output_path = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def pause(self) -> None:
        """Suspend capture; captions spoken while paused are not recorded."""
        with self._lock:
            if self.state == "recording":
                self._paused.set()
                self.state = "paused"

    def resume(self) -> None:
        with self._lock:
            if self.state == "paused":
                self._paused.clear()
                self.state = "recording"

    def stop(self) -> None:
        """Finish the transcript: the file gets its footer and capture ends."""
        self._paused.clear()
        self._stop.set()

    def status(self) -> dict:
        with self._lock:
            t = self.transcript
            return {
                "state": self.state,
                "error": self.error,
                "entries": len(t.entries) if t else 0,
                "speakers": t.anonymizer.count if t else 0,
                "tail": t.tail() if t else [],
                "output": str(self.output_path) if self.output_path else "",
            }

    # -- capture loop -------------------------------------------------------

    def _find_captions_window(self):
        for w in _auto.GetRootControl().GetChildren():
            try:
                if w.Name and "Captions" in w.Name:
                    return w
            except Exception:
                continue
        return None

    def _extract_text(self, ctrl, out: list) -> None:
        try:
            if ctrl.ControlTypeName == "TextControl":
                text = ctrl.Name.strip()
                if text:
                    out.append(text)
            for child in ctrl.GetChildren():
                self._extract_text(child, out)
        except Exception:
            pass

    def _run(self) -> None:
        try:
            with _auto.UIAutomationInitializerInThread():
                self._capture_loop()
        except Exception as e:  # pragma: no cover - Windows runtime only
            with self._lock:
                self.state = "error"
                self.error = str(e)

    def _capture_loop(self) -> None:
        window = None
        while not self._stop.is_set() and window is None:
            window = self._find_captions_window()
            if window is None:
                self._stop.wait(self.SCAN_SECONDS)
        if window is None:
            with self._lock:
                self.state = "idle"
            return

        TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        transcript = Transcript()
        out_path = TRANSCRIPTS_DIR / f"Meeting_{transcript.started.strftime('%Y-%m-%d_%H-%M')}.md"
        with self._lock:
            self.transcript = transcript
            self.output_path = out_path
            self.state = "recording"

        window_name = window.Name
        try:
            while not self._stop.is_set():
                if self._paused.is_set():
                    self._stop.wait(self.POLL_SECONDS)
                    continue
                if not window.Exists():
                    break
                items: list = []
                self._extract_text(window, items)
                changed = False
                with self._lock:
                    for item in items:
                        if item == window_name:
                            continue
                        changed |= transcript.add_caption(item)
                if changed:
                    _write_atomic(out_path, transcript.render())
                self._stop.wait(self.POLL_SECONDS)
        finally:
            with self._lock:
                _write_atomic(out_path, transcript.render(ended=datetime.now()))
                self.state = "idle"


def list_transcripts() -> List[Path]:
    """Saved transcripts, newest first."""
    if not TRANSCRIPTS_DIR.is_dir():
        return []
    return sorted(TRANSCRIPTS_DIR.glob("*.md"), key=lambda p: p.name, reverse=True)


def open_transcripts_folder() -> None:
    """Open the transcripts folder in the OS file manager.

    Only meaningful when the Streamlit server runs on the user's own machine
    (the Windows install, or source mode on a workstation) — which is also the
    only place capture works.
    """
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    if sys.platform.startswith("win"):
        os.startfile(str(TRANSCRIPTS_DIR))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(TRANSCRIPTS_DIR)])
    else:
        subprocess.Popen(["xdg-open", str(TRANSCRIPTS_DIR)])
