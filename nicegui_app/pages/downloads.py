"""Downloads — kits and extensions that ship with the app."""

from __future__ import annotations

from pathlib import Path

from nicegui import ui

from nicegui_app import components as c
from splice.common import kits

DOWNLOADS = Path(__file__).resolve().parents[2] / "assets" / "downloads"

#: Kits built from ``packaging/`` at download time rather than committed. The
#: zip is made from the working tree, so it cannot drift from the source the
#: tests run against — see ``splice.common.kits``.
BUILT = [
    ("def_editor_automation", "def-editor-automation.zip",
     "DEF Editor automation prototype (Windows .exe)",
     "Automates DEF EDITOR through Windows UI Automation: walks program → "
     "model year → phase → composite → harness, reads any module's grid, runs "
     "the quality checks, exports CSV. Ships as source with a PyInstaller "
     "spec — unzip on a Windows PC, pip install -r requirements.txt, "
     "pyinstaller def_editor_automation.spec. Includes a Demo mode and a "
     "--selftest that run the whole workflow with no DEF Editor, so the kit "
     "can be tried anywhere before it is built."),
]

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
        for kit, filename, title, desc in BUILT:
            with c.card(title, desc):
                c.download(filename, lambda k=kit: kits.build(k))
        for filename, title, desc in ITEMS:
            path = DOWNLOADS / filename
            with c.card(title, desc):
                if path.exists():
                    c.download(filename, lambda p=path: p.read_bytes())
                else:
                    c.note("review", f"{filename} is not in this build — get it "
                                     "from the project's Releases page, or drop "
                                     "it into assets/downloads")
