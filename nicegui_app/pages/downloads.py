"""Downloads — kits and extensions that ship with the app."""

from __future__ import annotations

from pathlib import Path

from nicegui import ui

from nicegui_app import components as c

DOWNLOADS = Path(__file__).resolve().parents[2] / "assets" / "downloads"

ITEMS = [
    ("teams-transcript-recorder.zip",
     "Standalone transcript recorder (Windows .exe)",
     "Windows recorder with a status window — download, unzip, and run the "
     ".exe (no install, no Python). Anonymized by default. Built on Windows "
     "and published as a release rather than committed: the 42 MB archive "
     "was most of the repository, and the copy in git predated the "
     "privacy attestation this description used to promise."),
    ("ispeed-dtcr-downloader.zip",
     "iSpeed DTCR Downloader (Chrome extension)",
     "Captures iSpeed DTCR search results, attachments, and a summary CSV in "
     "one run. Load unpacked via chrome://extensions."),
    ("Z913_example_input.xlsx",
     "Splice Generation example input",
     "Reference workbook showing the required Complexity + OptionPerCkt "
     "structure."),
]


@ui.page("/downloads")
def page() -> None:
    with c.frame("Downloads", "Kits and extensions that ship with the toolkit."):
        for filename, title, desc in ITEMS:
            path = DOWNLOADS / filename
            with c.card(title, desc):
                if path.exists():
                    c.download(filename, lambda p=path: p.read_bytes())
                else:
                    c.note("review", f"{filename} is not in this build — get it "
                                     "from the project's Releases page, or drop "
                                     "it into assets/downloads")
