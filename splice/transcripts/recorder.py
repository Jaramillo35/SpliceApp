"""Background recorder for Teams Live Captions with speaker anonymization.

Windows only at capture time: the caption text is read from the Teams Live
Captions window through UI Automation, which requires the meeting to be on
this machine's screen. Everything else in this module (anonymization, the
transcript document model) is platform-neutral and unit-tested.

Privacy model
-------------
**Anonymized is the default and needs no consent.** Every name the captions
expose is mapped, in memory only, to a stable alias ("Speaker 1", "Speaker 2",
...) for the duration of the recording; the mapping dies with the recording.
Filenames carry only a timestamp — not the meeting title, which for 1:1 calls
contains a participant's name. Names spoken *inside* a sentence cannot be
detected reliably and are kept verbatim; the transcript header states that
caveat.

**Named recording is opt-in and gated.** Writing real participant names to
disk processes personal data, so :class:`Consent` requires the recording
person to attest — before capture starts — that participants were told the
meeting is being transcribed for minutes AND that permission was requested
with no objection, signed with their own name. The engine refuses to start a
named recording without a complete attestation, and the transcript itself
carries that attestation (who, when, what was said) as the compliance record.
:data:`PARTICIPANT_NOTICE` is the message the user sends to participants.

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

from splice.common.errors import SpliceError
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

#: The message the recording person sends to participants before a named
#: recording. Kept verbatim in the transcript as evidence of what was
#: disclosed. Written to be sendable as-is in a Teams chat or invite.
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

#: The two things the recording person must be able to attest to, in order.
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
    """The recording person's privacy attestation for a NAMED recording.

    Anonymized recordings do not need one. A named recording is refused unless
    every attestation is affirmed and signed with the attester's own name —
    and the affirmation is written into the transcript, so the file itself is
    the compliance record.
    """

    announced: bool = False
    permission_granted: bool = False
    attested_by: str = ""
    attested_at: Optional[datetime] = None
    notice_text: str = PARTICIPANT_NOTICE
    notes: str = ""

    @property
    def missing(self) -> List[str]:
        """Human-readable list of what still blocks a named recording."""
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
        """Record who attested and when (call when the user confirms)."""
        self.attested_by = " ".join(str(by).split())
        self.attested_at = when or datetime.now()
        return self


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
    #: True only for an attested named recording; default stays anonymized.
    record_names: bool = False
    consent: Optional[Consent] = None
    _current_speaker: str = ""
    _seen: set = field(default_factory=set)

    def _label(self, name: str) -> str:
        """The speaker label written to disk for a display name.

        The anonymizer is consulted either way — it keeps the speaker count and
        the ``known()`` memory that makes label detection reliable — but in an
        attested named recording the real name is what gets written.
        """
        alias = self.anonymizer.alias(name)
        if self.record_names:
            return " ".join(str(name).split())
        return alias

    def add_caption(self, item: str) -> bool:
        """Feed one raw caption item. Returns True when the document changed."""
        item = str(item).strip()
        if not item or item in self._seen:
            return False
        self._seen.add(item)

        # A standalone speaker label: remember the label, write nothing.
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
        """The privacy record written into every transcript.

        For an anonymized recording it states that no names were kept. For a
        named one it reproduces the attestation — what the recording person
        confirmed they did, who signed it, when, and the exact notice given to
        participants — so the file stands on its own as the compliance record.
        """
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
        self.record_names: bool = False
        self.consent: Optional[Consent] = None

    # -- public API ---------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, *, record_names: bool = False,
              consent: Optional[Consent] = None) -> None:
        """Begin capture. Anonymized by default.

        ``record_names=True`` writes real participant names and therefore
        requires a complete :class:`Consent`; without one the call raises
        rather than silently falling back, so a privacy gate can never be
        bypassed by a bug upstream.
        """
        if record_names:
            gaps = (consent or Consent()).missing
            if gaps:
                raise SpliceError(
                    "Cannot record participant names: " + "; ".join(gaps) + ".")
        if self.running or not CAPTURE_AVAILABLE:
            return
        self._stop.clear()
        self._paused.clear()
        self.state = "waiting"
        self.error = ""
        self.transcript = None
        self.output_path = None
        self.record_names = bool(record_names)
        self.consent = consent if record_names else None
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
                "record_names": self.record_names,
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
        transcript = Transcript(record_names=self.record_names,
                                consent=self.consent)
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
