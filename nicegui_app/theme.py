"""Design tokens and global styling for the NiceGUI app.

Values mirror docs/NICEGUI_DESIGN.md. Dark-first by commitment; the chart
palette is the validated orange-first categorical set from the UI/UX audit.
"""

from __future__ import annotations

from nicegui import ui

CANVAS = "#0e1117"
SURFACE = "#1a1d24"
SURFACE_2 = "#14161c"
TEXT = "#e8e8ec"
BRAND = "#d95926"
LINE = "rgba(232,232,236,0.13)"

STATUS = {
    "blocker": "#e66767",
    "high": "#c98500",
    "review": "#d5c04b",
    "ok": "#199e70",
    "info": "#3987e5",
}

#: validated categorical chart palette (dark steps), orange first
CHART = ["#d95926", "#3987e5", "#199e70", "#c98500",
         "#d55181", "#008300", "#9085e9", "#e66767"]

_CSS = f"""
<style>
  body {{ background: {CANVAS}; }}
  .sx-reveal {{ animation: sxin 180ms cubic-bezier(0.23,1,0.32,1) both; }}
  @keyframes sxin {{ from {{ opacity: 0; transform: translateY(4px); }} }}
  .q-btn {{ transition: transform 140ms cubic-bezier(0.23,1,0.32,1); }}
  .q-btn:active {{ transform: scale(0.97); }}
  .sx-mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
  .sx-card {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 12px; }}
  .sx-muted {{ color: rgba(232,232,236,0.62); }}
  @media (prefers-reduced-motion: reduce) {{
    .sx-reveal {{ animation: none; }}
    .q-btn {{ transition: none; }}
  }}
</style>
"""


def apply() -> None:
    """Call once per page build (idempotent per client)."""
    ui.dark_mode().enable()
    ui.colors(primary=BRAND, positive=STATUS["ok"], negative=STATUS["blocker"],
              warning=STATUS["high"], info=STATUS["info"])
    ui.add_head_html(_CSS)
