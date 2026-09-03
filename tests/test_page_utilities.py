"""The three Utilities pages, driven as a user would drive them — no browser.

Admin, Downloads and Meeting Transcripts have no engine run to prove; what
can go wrong is the wiring — a card that stops rendering, a note that is
lost in a refactor. The simulated user opens each page and reads what it
says.
"""

from __future__ import annotations

from nicegui.testing import User


async def test_admin_shows_every_card(user: User):
    from nicegui_app.pages import admin
    await user.open("/admin")
    for title in ("Version", "What changed", "Services", "Data", "Logs",
                  "Feedback inbox"):
        await user.should_see(title)
    for name, _url, _kind in admin.SERVICES:
        await user.should_see(name)


async def test_downloads_lists_every_kit(user: User):
    from nicegui_app.pages import downloads
    await user.open("/downloads")
    for _filename, title, _desc in downloads.ITEMS:
        await user.should_see(title)


async def test_transcripts_names_the_recorder_and_says_it_is_per_machine(user: User):
    from nicegui_app.pages import transcripts
    await user.open("/transcripts")
    await user.should_see("Recorder")
    await user.should_see(transcripts.PER_MACHINE)
    await user.should_see("Saved transcripts")
