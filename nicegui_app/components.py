"""Shared shell and components — every page is built from these.

The interaction canon (docs/NICEGUI_DESIGN.md, second edition in the
interface schema study): one gated primary per page; the accent is spent on
the action, not the inputs; the result panel always exists and teaches when
empty; one toast per action; downloads are always a click; twelve pixels is
the floor; status is icon plus word; every click target is a button.

Page registry
-------------
``PAGES`` is the single source of truth for the rail, the Overview grid and
the feedback dialog's area list. A page belongs to one family — the
family says how the page behaves, not what the code is:

* **Workbenches** hold judgement across sessions and end in a sign-off.
* **Converters** take files and return workbooks in one sitting.
* **Records** are searched.
* **Utilities** are everything else.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

from nicegui import context, run, ui

from nicegui_app import theme

ASSETS = Path(__file__).resolve().parents[1] / "assets"


# ================================================================ registry
@dataclass(frozen=True)
class Page:
    label: str
    icon: str
    route: str
    family: str
    purpose: str


FAMILIES = ("Workbenches", "Converters", "Records", "Utilities")
FAMILY_HINT = {
    "Workbenches": "judgement, saved, signed off",
    "Converters": "files in, workbook out",
    "Records": "search the history",
    "Utilities": "",
}

PAGES: tuple[Page, ...] = (
    Page("Circuit Applicability", "rule", "/circuit-applicability", "Workbenches",
         "DTx circuits against each harness's complexity — which part numbers "
         "carry which circuit, and which conditions no build satisfies."),
    Page("Circuit Health", "monitor_heart", "/circuit-health", "Workbenches",
         "Missing circuits across inlines: cavity checks, option-window "
         "coverage, route gaps — with SE dispositions and sign-off."),
    Page("Harness Complexity", "table_view", "/harness-complexity", "Workbenches",
         "Individual harness-complexity .xlsm files from the master workbook — "
         "reviewed matrix, combined-expression decisions, macros preserved."),
    Page("VBOM Risk Matrix", "grid_on", "/vbom", "Workbenches",
         "DoAll / BuildSpec + complexity files into the VBOM workbook bundle, "
         "with a review gate before the DEFE."),
    Page("DTx Compare", "difference", "/dtx-compare", "Converters",
         "OLD vs NEW DTx with DTCR tagging — the WEAVE change workbook and "
         "the PreOrder list."),
    Page("Splice Generation", "cable", "/splice-generation", "Converters",
         "Configurations, generated connections, print matrix, and the output "
         "workbook from one Complexity + OptionPerCkt file."),
    Page("HRN Chart Builder", "stacked_bar_chart", "/hrn-chart", "Converters",
         "Batch HRN + CSV (+ CMP) conversion into chart workbooks with "
         "supplier prefixes."),
    Page("SECR Database", "storage", "/secr", "Records",
         "A searchable history of engineering changes; import workbooks and "
         "browse every change."),
    Page("Ask the Database", "forum", "/ask", "Records",
         "Plain-language questions over the SECR history, answered with "
         "evidence by the local model."),
    Page("Meeting Transcripts", "graphic_eq", "/transcripts", "Utilities",
         "Anonymized Teams caption recording — Speaker 1..N, LLM-ready minutes."),
    Page("Downloads", "download", "/downloads", "Utilities",
         "Kits and extensions that ship with the toolkit."),
)
OVERVIEW = Page("Overview", "space_dashboard", "/", "",
                "Continue where you left off; what needs attention.")
ADMIN = Page("Admin", "admin_panel_settings", "/admin", "",
             "What is running, what changed, and the state of the data.")

#: legacy grouped view, kept for anything that still reads it
NAV = [(family, [(p.label, p.icon, p.route) for p in PAGES if p.family == family])
       for family in FAMILIES]


def pages_in(family: str) -> list[Page]:
    return [p for p in PAGES if p.family == family]


def current_route() -> str:
    try:
        return context.client.page.path
    except Exception:  # noqa: BLE001 — outside a page build there is no route
        return ""


# ============================================================ per-client bag
def _bag() -> dict:
    """Per-client registries: gated actions, step bar, header slot."""
    client = context.client
    bag = getattr(client, "sx", None)
    if bag is None:
        bag = {"actions": [], "steps": [], "header": None, "step_bar": None,
               "title": "", "context": ""}
        client.sx = bag
    return bag


def recheck() -> None:
    """Re-evaluate every gated action on this page. Upload rows call this
    after each file; pages call it after any other input changes."""
    bag = _bag()
    bag["actions"] = [a for a in bag["actions"] if not a.button.is_deleted]
    for act in bag["actions"]:
        act.check()


# ================================================================== shell
def _feedback_dialog() -> ui.dialog:
    with ui.dialog() as dialog, ui.card().classes("w-[28rem] sx-card"):
        ui.label("Report a problem or idea").classes("sx-section")
        area = ui.select(["General"] + [p.label for p in PAGES],
                         value="General", label="Area").classes("w-full")
        text = ui.textarea("What happened, or what would help?").classes("w-full")
        name = ui.input("Your name (optional)").classes("w-full")

        def submit() -> None:
            body = (text.value or "").strip()
            if not body:
                ui.notify("Describe the problem first", type="warning")
                return
            from feedback_system import FeedbackStore
            ticket_id = FeedbackStore().submit_ticket(
                reported_by=name.value or "Anonymous", workflow=area.value,
                area=area.value, description=body, category="feedback")
            dialog.close()
            text.value = ""
            ui.notify(f"Ticket {ticket_id} filed — thank you", type="positive")

        with ui.row().classes("justify-end w-full gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
            ui.button("Send", on_click=submit).props("unelevated no-caps")
    return dialog


def _nav_link(page: Page, active: bool) -> None:
    with ui.link(target=page.route).classes("no-underline w-full"):
        with ui.row().classes("sx-nav w-full no-wrap" + (" sx-nav--active" if active else "")):
            ui.icon(page.icon).classes("text-base")
            ui.label(page.label)


@contextmanager
def frame(title: str, caption: str = "", *, context_chip: str = "", wide: bool = False):
    """App shell: rail + header + content column. Yields the content column.

    ``context_chip`` names the programme and phase once the page knows them
    (header_chip() adds one later). ``wide`` lets a workbench's tables use
    the full width.
    """
    theme.apply()
    bag = _bag()
    bag["title"] = title
    dialog = _feedback_dialog()
    route = current_route()

    # value=None: open above the breakpoint, closed below it — the rail never
    # overlays the content column on its own; the header button opens it
    drawer = ui.left_drawer(value=None, fixed=True) \
        .props("width=232 breakpoint=1023 show-if-above") \
        .classes("p-3") \
        .style(f"background:{theme.SURFACE_2};border-right:1px solid {theme.LINE}")
    with drawer:
        with ui.column().classes("w-full h-full gap-0 no-wrap"):
            with ui.row().classes("items-center gap-2 px-2 pt-1 pb-3 no-wrap"):
                with ui.element("div").classes(
                        "w-8 h-8 rounded-lg flex items-center justify-center shrink-0") \
                        .style(f"background:{theme.BRAND}"):
                    ui.icon("electrical_services").classes("text-xl") \
                        .style(f"color:{theme.TEXT}")
                with ui.column().classes("gap-0"):
                    ui.label("Versigent").classes("text-base font-bold leading-none tracking-tight")
                    ui.label("System Engineer Toolkit").classes("sx-caption leading-none")
            _nav_link(OVERVIEW, route == "/")
            for family in FAMILIES:
                ui.label(family).classes("sx-eyebrow px-2 mt-3 mb-1")
                for page in pages_in(family):
                    _nav_link(page, route == page.route)
            ui.element("div").classes("grow")
            with ui.column().classes("w-full gap-0 pt-3").style(f"border-top:1px solid {theme.LINE}"):
                _nav_link(ADMIN, route == ADMIN.route)
                _identity_row()
                from splice import version
                info = version.current()
                ui.label(f"v{info.label}").classes("sx-caption sx-mono px-2 pt-1")

    with ui.header().classes("items-center justify-between px-5 py-2 no-wrap") \
            .style(f"background:{theme.SURFACE_2};border-bottom:1px solid {theme.LINE}"):
        with ui.row().classes("items-center gap-3 no-wrap min-w-0"):
            ui.button(icon="menu", on_click=drawer.toggle).props("flat dense round") \
                .classes("lt-md").tooltip("Show navigation")
            with ui.column().classes("gap-0 min-w-0"):
                ui.label(title).classes("sx-title")
                if caption:
                    ui.label(caption).classes("sx-caption")
        with ui.row().classes("items-center gap-2 no-wrap") as slot:
            bag["header"] = slot
            if context_chip:
                header_chip(context_chip)
            ui.button("Feedback", icon="rate_review", on_click=dialog.open) \
                .props("outline dense no-caps")

    width = "w-full" if wide else "w-full max-w-[80rem] mx-auto"
    with ui.column().classes(f"{width} p-6 gap-6") as content:
        yield content


def who() -> str:
    """The engineer's name for the state envelope, from per-user storage.
    Empty until they set it (rail footer)."""
    try:
        from nicegui import app
        return str(app.storage.user.get("name", "") or "")
    except Exception:  # noqa: BLE001 — no user storage outside a request
        return ""


def set_who(name: str) -> None:
    try:
        from nicegui import app
        app.storage.user["name"] = name.strip()
    except Exception as exc:  # noqa: BLE001 — no user storage outside a request
        ui.notify(f"Could not remember your name: {exc}", type="warning")


def _identity_row() -> None:
    """Rail footer: who you are, editable in place."""
    with ui.row().classes("items-center gap-1 px-2 no-wrap w-full"):
        ui.icon("person").classes("text-sm").style(f"color:{theme.TEXT_3}")
        label = ui.label(who() or "Set your name").classes("sx-caption truncate")

        with ui.dialog() as dialog, ui.card().classes("w-80 sx-card"):
            ui.label("Your name").classes("sx-section")
            ui.label("Shown on everything you save so the team can see who "
                     "decided what.").classes("sx-caption")
            field = ui.input("Name or initials", value=who()).classes("w-full")

            def save() -> None:
                set_who(field.value or "")
                label.set_text(who() or "Set your name")
                dialog.close()

            field.on("keydown.enter", save)
            with ui.row().classes("justify-end w-full gap-2"):
                ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                ui.button("Save", on_click=save).props("unelevated no-caps")

        ui.button(icon="edit", on_click=dialog.open).props("flat dense round size=xs") \
            .tooltip("Change your name")


def header_chip(text: str, kind: str = "info") -> None:
    """A context chip in the header (programme · phase, or a saved-by line)."""
    bag = _bag()
    bag["context"] = text
    slot = bag["header"]
    if slot is None:
        return
    old = bag.get("context_chip")
    if old is not None and not old.is_deleted:
        old.delete()
    with slot:
        with ui.element("div") as holder:
            chip(kind, text)
    bag["context_chip"] = holder


def envelope(text: str) -> ui.label:
    """The state envelope for a workbench: 'Saved by M.J. · 2 min ago'."""
    slot = _bag()["header"]
    with slot:
        return ui.label(text).classes("sx-caption sx-mono")


# ================================================================ sections
@contextmanager
def card(title: str = "", caption: str = ""):
    with ui.card().classes("w-full sx-card sx-reveal") as c:
        if title:
            ui.label(title).classes("sx-section")
        if caption:
            ui.label(caption).classes("sx-caption -mt-1")
        yield c


class Step:
    def __init__(self, name: str, anchor: str) -> None:
        self.name, self.anchor = name, anchor
        self.state, self.note = "waiting", ""


class StepBar:
    """Sticky in-page navigation for a workbench: one link per section with
    its state (done, current, blocked, waiting) and a short note."""

    def __init__(self) -> None:
        self.container = ui.row().classes("sx-steps w-full gap-2 flex-wrap")
        self.render()

    def render(self) -> None:
        self.container.clear()
        with self.container:
            for step in _bag()["steps"]:
                with ui.link(target=f"#{step.anchor}") \
                        .classes(f"sx-step sx-step--{step.state}"):
                    icon = {"done": "check", "current": "radio_button_checked",
                            "blocked": "report", "waiting": "radio_button_unchecked"}[step.state]
                    ui.icon(icon).classes("text-sm")
                    ui.label(step.name)
                    if step.note:
                        ui.label(step.note).classes("sx-caption")


def _anchor(step: str) -> str:
    return "step-" + "".join(ch if ch.isalnum() else "-" for ch in step.lower())


def step_bar(*names: str) -> StepBar:
    """The workbench's sticky step bar. Pass the step names in page order so
    every step shows from the first paint, waiting until its card renders."""
    steps = _bag()["steps"]
    for name in names:
        if not any(x.name == name for x in steps):
            steps.append(Step(name, _anchor(name)))
    bar = StepBar()
    _bag()["step_bar"] = bar
    return bar


def set_step(name: str, state: str, note: str = "") -> None:
    """Update one step's state and note; the bar redraws in place."""
    bag = _bag()
    for step in bag["steps"]:
        if step.name == name:
            step.state, step.note = state, note
    if bag["step_bar"] is not None:
        bag["step_bar"].render()


@contextmanager
def section(title: str, caption: str = "", *, step: str | None = None,
            state: str = "waiting"):
    """A card that is also a step: registers itself with the page's step bar
    and carries an anchor the bar links to. Only workbenches pass ``step``."""
    anchor = ""
    if step is not None:
        anchor = _anchor(step)
        steps = _bag()["steps"]
        if not any(x.name == step for x in steps):
            s = Step(step, anchor)
            s.state = state
            steps.append(s)
    with ui.card().classes("w-full sx-card sx-reveal") as c:
        if anchor:
            c.props(f'id="{anchor}"')
        if title:
            ui.label(title).classes("sx-section")
        if caption:
            ui.label(caption).classes("sx-caption -mt-1")
        yield c


# ================================================================== status
def chip(kind: str, label: str) -> None:
    """Status: icon plus word, never colour alone."""
    color = theme.STATUS.get(kind, theme.STATUS["info"])
    icon = theme.STATUS_ICON.get(kind, "info")
    with ui.row().classes("items-center gap-1 px-2 py-0.5 rounded-full border inline-flex no-wrap") \
            .style(f"border-color:{color}55;background:{theme.wash(color)};color:{color}"):
        ui.icon(icon).classes("text-sm")
        ui.label(label).classes("text-xs font-semibold")


status = chip


def toggle_chip(label: str, active: bool, on_click: Callable, count: int | None = None) -> ui.button:
    """A filter chip that is a real button: focusable, keyboard-operable,
    and the path a chart click mirrors."""
    text = label if count is None else f"{label} · {count}"
    btn = ui.button(text, on_click=lambda _e: on_click()) \
        .props(f'flat dense no-caps aria-pressed="{"true" if active else "false"}"') \
        .classes("sx-toggle px-3")
    return btn


def note(kind: str, text: str) -> None:
    """The one inline error / warning / info line, placed under the thing
    it is about."""
    color = theme.STATUS.get(kind, theme.STATUS["info"])
    with ui.row().classes("items-start gap-1 no-wrap"):
        ui.icon(theme.STATUS_ICON.get(kind, "info")).classes("text-sm mt-0.5") \
            .style(f"color:{color}")
        ui.label(text).classes("text-sm").style(f"color:{color}")


# ================================================================== inputs
def upload_row(label: str, on_file: Callable[[str, bytes], None],
               accept: str = "", multiple: bool = False) -> None:
    """A quiet upload row: label, drop target, filename and size once
    received. Reads bytes immediately and rechecks the page's gated actions."""
    with ui.column().classes("flex-1 gap-1 min-w-[16rem]"):
        received: list[str] = []

        async def handle(e) -> None:
            # NiceGUI 3.x: the event carries a FileUpload at e.file
            data = await e.file.read()
            on_file(e.file.name, data)
            received.append(e.file.name)
            recheck()
            # one summary chip, not one per file — 17 complexity files must
            # not become a page of chips (field report, 2026-08-24)
            text = received[0] if len(received) == 1 \
                else f"{len(received)} files received"
            confirm.set_text(f"✓ {text}")
            confirm.set_visibility(True)

        ui.upload(label=label, on_upload=handle, multiple=multiple, auto_upload=True) \
            .props(f'accept="{accept}" flat bordered') \
            .classes("w-full").style("max-height: 14rem")
        confirm = ui.label("").classes("text-xs px-2 py-0.5 rounded-full w-fit") \
            .style(f"background:{theme.wash(theme.STATUS['ok'])};color:{theme.STATUS['ok']}")
        confirm.set_visibility(False)


upload_zone = upload_row


class Action:
    """The one primary per page. Disabled until every named input exists,
    with a caption naming what is missing."""

    def __init__(self, label: str, on_click: Callable, *,
                 needs: Callable[[], Sequence[str]] | None = None,
                 icon: str = "play_arrow", secondary: bool = False) -> None:
        self.needs = needs
        with ui.column().classes("gap-1"):
            self.button = ui.button(label, icon=icon, on_click=on_click) \
                .props("outline dense no-caps" if secondary else "unelevated no-caps")
            self.caption = ui.label("").classes("sx-caption")
            self.caption.set_visibility(False)
        _bag()["actions"].append(self)
        self.check()

    def check(self) -> None:
        missing = list(self.needs()) if self.needs else []
        self.button.set_enabled(not missing)
        if missing:
            self.caption.set_text("Needs: " + ", ".join(missing))
        self.caption.set_visibility(bool(missing))


def action(label: str, on_click: Callable, *,
           needs: Callable[[], Sequence[str]] | None = None,
           icon: str = "play_arrow", secondary: bool = False) -> Action:
    return Action(label, on_click, needs=needs, icon=icon, secondary=secondary)


# ================================================================= outputs
def kpi(value, label: str, kind: str | None = None, hint: str = "") -> None:
    """One figure, one label. ``kind`` colours the figure only."""
    color = theme.STATUS[kind] if kind else theme.TEXT
    with ui.column().classes("sx-tile px-4 py-3 gap-1 min-w-[8.5rem] flex-1"):
        ui.label(f"{value:,}" if isinstance(value, int) else str(value)) \
            .classes("sx-kpi").style(f"color:{color}")
        ui.label(label).classes("sx-caption")
        if hint:
            ui.label(hint).classes("sx-caption sx-faint")


@contextmanager
def kpi_strip():
    with ui.row().classes("w-full gap-3 flex-wrap") as strip:
        yield strip


def _humanize(field: str) -> str:
    return field.replace("_", " ").strip().capitalize()


def frame_table(data, *, columns: Iterable[str] | None = None,
                labels: dict | None = None, cap: int | None = None,
                pagination: int = 25, mono: Iterable[str] = (),
                status_field: str | None = None, dense: bool = True) -> ui.table:
    """The one dataframe-to-table. Accepts a pandas DataFrame or a list of
    dicts. When ``cap`` truncates, the footer says so and points to the
    export instead of hiding rows silently."""
    if hasattr(data, "to_dict"):
        rows = data.to_dict(orient="records")
        fields = list(columns or data.columns)
    else:
        rows = list(data)
        fields = list(columns or (rows[0].keys() if rows else []))
    labels = labels or {}
    total = len(rows)
    if cap is not None and total > cap:
        rows = rows[:cap]
    mono = set(mono)
    cols = []
    for f in fields:
        col = {"name": f, "label": labels.get(f, _humanize(str(f))), "field": f,
               "align": "left", "sortable": True}
        if f in mono:
            col["classes"] = "sx-mono"
        cols.append(col)
    clean = [{str(k): ("" if v is None else v) for k, v in r.items()} for r in rows]
    table = ui.table(columns=cols, rows=clean, pagination=pagination) \
        .classes("w-full sx-data").props("flat bordered" + (" dense" if dense else ""))
    if status_field:
        table.add_slot(f"body-cell-{status_field}", r'''
            <q-td :props="props"><span class="text-xs font-semibold">{{ props.value }}</span></q-td>
        ''')
    if cap is not None and total > cap:
        ui.label(f"Showing {cap:,} of {total:,} rows · export for all").classes("sx-caption")
    return table


class ResultPanel:
    """The result container that always exists. Before a run it teaches;
    after a run the page draws into it."""

    def __init__(self, title: str, teach: str, icon: str) -> None:
        self.teach, self.icon = teach, icon
        with ui.card().classes("w-full sx-card sx-reveal"):
            with ui.row().classes("w-full items-center justify-between no-wrap"):
                ui.label(title).classes("sx-section")
                self.actions = ui.row().classes("items-center gap-2 no-wrap")
            self.body = ui.column().classes("w-full gap-3")
        self.clear()

    def clear(self) -> None:
        self.actions.clear()
        self.body.clear()
        with self.body:
            empty(self.teach, icon=self.icon)

    @contextmanager
    def show(self):
        self.actions.clear()
        self.body.clear()
        with self.body:
            yield self.body


def converter(teach: str, *, inputs_title: str = "Inputs", inputs_caption: str = "",
              result_title: str = "Result", icon: str = "upload_file"):
    """Archetype A. Inputs panel and result panel side by side above 1024 px,
    stacked below. The inputs panel is narrow and sticky and ends in the one
    gated primary; the result panel exists from the first paint and teaches
    until there is a result. Returns ``(inputs, result)``."""
    with ui.element("div").classes(
            "w-full grid gap-6 items-start grid-cols-1 lg:grid-cols-[22rem_minmax(0,1fr)]"):
        inputs = ui.card().classes("sx-card sx-reveal w-full gap-3 lg:sticky lg:top-20")
        with inputs:
            ui.label(inputs_title).classes("sx-section")
            if inputs_caption:
                ui.label(inputs_caption).classes("sx-caption -mt-1")
        panel = ResultPanel(result_title, teach, icon)
    return inputs, panel


def result_panel(teach: str, *, title: str = "Result", icon: str = "upload_file") -> ResultPanel:
    return ResultPanel(title, teach, icon)


def empty(message: str, icon: str = "upload_file") -> None:
    with ui.column().classes("items-center w-full py-8 gap-1"):
        ui.icon(icon).classes("text-4xl").style(f"color:{theme.TEXT_3}")
        ui.label(message).classes("text-sm text-center max-w-[40rem]") \
            .style(f"color:{theme.TEXT_2}")


def download(filename: str, data_getter: Callable[[], bytes]) -> ui.button:
    """Filename as label, always a click."""
    return ui.button(filename, icon="download",
                     on_click=lambda: ui.download(data_getter(), filename)) \
        .props("outline dense no-caps")


download_button = download


def downloads(items: Sequence[tuple[str, Callable[[], bytes]]], label: str = "") -> None:
    """Several files become one menu; one file is just its button."""
    if len(items) == 1:
        download(*items[0])
        return
    with ui.button(label or f"{len(items)} files", icon="download") \
            .props("outline dense no-caps"):
        with ui.menu():
            for name, getter in items:
                ui.menu_item(name, on_click=lambda _e, n=name, g=getter: ui.download(g(), n)) \
                    .classes("sx-mono text-xs")


def echart(options: dict, **kwargs) -> ui.echart:
    """A themed chart: the token axis, text and tooltip styles applied once."""
    return ui.echart(theme.echart_theme(options), **kwargs)


# ================================================================= engines
def _log_run(done: str) -> None:
    """Every completed run lands in the activity feed, under the page's
    name, so the Overview can say what to continue."""
    try:
        from splice.common import activity
        bag = _bag()
        activity.record(bag.get("title", ""), current_route(), done,
                        by=who(), context=bag.get("context", ""))
    except Exception as exc:  # noqa: BLE001 — the feed must never break a run
        import logging
        logging.getLogger(__name__).warning("activity not recorded: %s", exc)


async def run_engine(fn: Callable, *args, running: str, done: str = "Done",
                     **kwargs):
    """Run an engine call off the UI thread with progress + completion toasts.

    Keyword arguments other than ``running``/``done`` are forwarded to ``fn``.
    Returns the result, or None after notifying the error.
    """
    note_ = ui.notification(running, spinner=True, timeout=None)
    try:
        result = await run.io_bound(fn, *args, **kwargs)
        ui.notify(done, type="positive")
        _log_run(done)
        return result
    except Exception as exc:  # noqa: BLE001 - engine errors surface to the user
        ui.notify(f"{exc}", type="negative", multi_line=True, close_button=True)
        return None
    finally:
        note_.dismiss()


async def run_engine_progress(fn: Callable, container, *, running: str,
                              done: str = "Done"):
    """Run an engine call that reports progress, showing a real progress bar.

    ``fn`` receives one argument: a ``progress(fraction, message)`` callback it
    may call from its worker thread. That callback only writes into a shared
    cell — the bar and its label are updated from a UI timer, because NiceGUI
    elements must never be touched from a thread other than the event loop's.
    """
    cell = {"fraction": 0.0, "message": running}

    def report(fraction: float, message: str) -> None:
        cell["fraction"], cell["message"] = fraction, message

    container.clear()
    with container:
        with ui.row().classes("items-center justify-between w-full"):
            label = ui.label(running).classes("sx-caption")
            percent = ui.label("0%").classes("sx-caption sx-mono")
        bar = ui.linear_progress(value=0.0, show_value=False) \
            .props("rounded size=8px")

    def tick() -> None:
        bar.set_value(cell["fraction"])
        label.set_text(cell["message"])
        percent.set_text(f"{cell['fraction'] * 100:.0f}%")

    timer = ui.timer(0.1, tick)
    try:
        result = await run.io_bound(fn, report)
        ui.notify(done, type="positive")
        _log_run(done)
        return result
    except Exception as exc:  # noqa: BLE001 - engine errors surface to the user
        ui.notify(f"{exc}", type="negative", multi_line=True, close_button=True)
        return None
    finally:
        timer.deactivate()
        container.clear()
