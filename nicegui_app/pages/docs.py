"""Documentation — the Markdown that ships with the build, read in the app.

Twenty-odd .md files say how this toolkit runs, deploys and is meant to be
changed, and every one of them could only be read in an editor or on GitHub.
The engineers running the packaged app have neither. This page lists what
shipped, renders it, and takes a dropped file for the Markdown that did not
ship — a spec mailed over, a change note pasted out of a ticket.

``ui.markdown`` sanitizes through DOMPurify by default. A dropped file is
someone else's text, so that default is deliberately left alone here.
"""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass
from pathlib import Path

from nicegui import ui

from nicegui_app import components as c

ROOT = Path(__file__).resolve().parents[2]

#: Tables and fenced code because the docs lean on both, header-ids so a
#: heading can be linked, mermaid because docs/ARCHITECTURE.md draws the
#: engine graph with one and a fenced block of source is not the diagram.
EXTRAS = ["fenced-code-blocks", "tables", "header-ids", "strike", "task_list",
          "mermaid"]

#: Caches, virtualenvs and vendored trees carry .md files that are not this
#: project's documentation, and ``data`` is the runtime's, not the build's.
#: Hidden directories go with them — .git, .github and .claude hold tooling
#: instructions, which are not what someone opens this page to read.
SKIP = {"node_modules", "__pycache__", "site-packages", "venv", "data"}

#: A dropped file is rendered in one pass and held in the page's memory. Past
#: a megabyte that stops being a document and starts being a log.
MAX_BYTES = 1024 * 1024

ROOT_GROUP = "Project root"


@dataclass(frozen=True)
class Doc:
    """One Markdown file in the checkout."""

    path: Path

    @property
    def rel(self) -> str:
        return self.path.relative_to(ROOT).as_posix()

    @property
    def group(self) -> str:
        """The folder it sits in — the index's only grouping."""
        parts = self.path.relative_to(ROOT).parts
        return parts[0] if len(parts) > 1 else ROOT_GROUP

    @property
    def title(self) -> str:
        return self.path.stem.replace("_", " ")


def repo_docs() -> list[Doc]:
    """Every .md that shipped with this checkout, root files first.

    ``os.walk`` rather than ``rglob`` so the skipped directories are pruned
    before they are walked: ``.git`` alone is tens of thousands of entries
    to stat on the Pi this runs on, for no .md at the end of it.
    """
    found: list[Doc] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP and not d.startswith(".")]
        for name in filenames:
            if name.endswith(".md"):
                found.append(Doc(Path(dirpath) / name))
    return sorted(found, key=lambda d: (d.group != ROOT_GROUP, d.group.lower(),
                                        d.rel.lower()))


def opening_doc(docs: list[Doc]) -> Doc | None:
    """What the page shows before anything is clicked.

    The README, when there is one: alphabetical order would open on the
    CHANGELOG, which is the one document nobody arrives wanting.
    """
    return next((d for d in docs if d.rel == "README.md"),
                docs[0] if docs else None)


@ui.page("/docs")
def page() -> None:
    docs = repo_docs()
    state: dict = {"doc": opening_doc(docs), "dropped": None, "query": ""}

    with c.frame("Documentation",
                 "Every Markdown file that ships with the build — plus any "
                 "you drop in.", wide=True):

        def choose(doc: Doc) -> None:
            state["doc"], state["dropped"] = doc, None
            index.refresh()
            viewer.refresh()

        def took(name: str, data: bytes) -> None:
            if len(data) > MAX_BYTES:
                ui.notify(f"{name} is over {MAX_BYTES // 1024} KB — too long "
                          "to render as a document", type="warning")
                return
            state["dropped"] = (name, data.decode("utf-8", errors="replace"))
            index.refresh()
            viewer.refresh()

        def clear() -> None:
            state["dropped"] = None
            index.refresh()
            viewer.refresh()

        def search(value: str | None) -> None:
            # the clear button hands back None, not ""
            state["query"] = value or ""
            index.refresh()

        @ui.refreshable
        def index() -> None:
            query = state["query"].strip().lower()
            shown = [d for d in docs if query in d.rel.lower()]
            if not shown:
                c.empty(f"No document's path matches “{state['query'].strip()}”.",
                        icon="search_off")
                return
            group = ""
            for doc in shown:
                if doc.group != group:
                    group = doc.group
                    ui.label(group).classes("sx-eyebrow px-2 mt-3 mb-1")
                active = state["dropped"] is None and state["doc"] == doc
                ui.button(doc.title, on_click=lambda _e, d=doc: choose(d)) \
                    .props('flat dense no-caps align=left '
                           f'aria-current="{"page" if active else "false"}"') \
                    .classes("sx-nav w-full"
                             + (" sx-nav--active" if active else "")) \
                    .tooltip(doc.rel)

        @ui.refreshable
        def viewer() -> None:
            if state["dropped"] is not None:
                name, text = state["dropped"]
                with c.card(name, "Dropped into this session — rendered here, "
                                  "not added to the build."):
                    ui.button("Back to the shipped docs", icon="arrow_back",
                              on_click=clear) \
                        .props("flat dense no-caps").classes("w-fit")
                    ui.markdown(text, extras=EXTRAS).classes("sx-md")
                return

            doc = state["doc"]
            if doc is None:
                with c.card("Documentation"):
                    c.empty("No Markdown shipped with this build. Drop a file "
                            "in to read one.", icon="menu_book")
                return

            try:
                text = doc.path.read_text(encoding="utf-8", errors="replace")
                stamp = dt.datetime.fromtimestamp(doc.path.stat().st_mtime)
            except OSError as exc:
                # listed a moment ago, gone now: a rebuild swapped the tree
                with c.card(doc.title):
                    c.note("blocker", f"{doc.rel} could not be read: {exc}")
                return

            caption = (f"{doc.rel} · {len(text.splitlines())} lines · "
                       f"updated {stamp:%Y-%m-%d}")
            with c.card(doc.title, caption):
                ui.markdown(text, extras=EXTRAS).classes("sx-md")

        with ui.row().classes("w-full gap-6 items-start"):
            with ui.column().classes("w-[19rem] grow-0 shrink-0 gap-4"):
                with c.card("Documents",
                            f"{len(docs)} in this build" if docs else ""):
                    ui.input(placeholder="Filter by path…",
                             on_change=lambda e: search(e.value)) \
                        .props("dense outlined clearable").classes("w-full")
                    with ui.column().classes("w-full gap-0"):
                        index()
                with c.card("Open a file",
                            "Any Markdown — .md, .markdown or .txt."):
                    c.upload_row("Markdown file", took,
                                 accept=".md,.markdown,.txt")
            with ui.column().classes("flex-1 min-w-[20rem] gap-4"):
                viewer()
