"""Design tokens and global styling for the NiceGUI app.

Values follow docs/NICEGUI_DESIGN.md and the interface schema study
(2026-09-02). Dark-first by commitment. Everything a page colours or sizes
comes from here — ``tests/test_theme_tokens.py`` refuses a hex or rgba
literal anywhere else under ``nicegui_app``.
"""

from __future__ import annotations

from nicegui import ui

# ------------------------------------------------------------- surfaces
CANVAS = "#0e1117"
SURFACE = "#1a1d24"
SURFACE_2 = "#14161c"      # rail, header, table heads, upload rows
SURFACE_3 = "#21252e"      # hover, selected row
LINE = "rgba(232,232,236,0.13)"
GRID = "rgba(232,232,236,0.08)"   # chart split lines

# ----------------------------------------------------------------- text
TEXT = "#e8e8ec"
TEXT_2 = "#a7adb6"         # secondary: captions, muted rows (solid, not opacity)
TEXT_3 = "#767d87"         # tertiary: eyebrows, footers
AXIS_TEXT = TEXT_2
BRAND = "#d95926"

FONT = ('"Segoe UI", -apple-system, BlinkMacSystemFont, system-ui, Roboto, '
        '"Helvetica Neue", Arial, sans-serif')
MONO = 'ui-monospace, "Cascadia Mono", SFMono-Regular, Menlo, Consolas, monospace'

# --------------------------------------------------------------- status
STATUS = {
    "blocker": "#e66767",
    "high": "#c98500",
    "review": "#d5c04b",
    "ok": "#199e70",
    "info": "#3987e5",
}
STATUS_ICON = {"blocker": "report", "high": "warning", "review": "help_outline",
               "ok": "check_circle", "info": "info"}

#: validated categorical chart palette (dark steps), orange first
CHART = ["#d95926", "#3987e5", "#199e70", "#c98500",
         "#d55181", "#008300", "#9085e9", "#e66767"]


def wash(color: str, alpha: str = "24") -> str:
    """A 14 % tint of ``color`` for chip and tile backgrounds."""
    return f"{color}{alpha}"


def axis_style() -> dict:
    """The axis fragment every echart merges in — typed once, here."""
    return {
        "axisLabel": {"color": AXIS_TEXT, "fontFamily": FONT},
        "axisLine": {"lineStyle": {"color": LINE}},
        "axisTick": {"show": False},
        "splitLine": {"lineStyle": {"color": GRID}},
    }


def echart_theme(options: dict) -> dict:
    """Apply the surface, text and axis tokens to an ECharts option dict.

    Page-level values win: this only fills what the page left unset, so a
    chart that needs a special axis keeps it.
    """
    options.setdefault("backgroundColor", "transparent")
    options.setdefault("textStyle", {"color": TEXT_2, "fontFamily": FONT})
    options.setdefault("color", list(CHART))
    for key in ("xAxis", "yAxis"):
        axes = options.get(key)
        if axes is None:
            continue
        for axis in (axes if isinstance(axes, list) else [axes]):
            for k, v in axis_style().items():
                axis.setdefault(k, v)
    tooltip = options.setdefault("tooltip", {})
    tooltip.setdefault("backgroundColor", SURFACE)
    tooltip.setdefault("borderColor", LINE)
    tooltip.setdefault("textStyle", {"color": TEXT})
    return options


_CSS = f"""
<style>
  body {{ background: {CANVAS}; font-family: {FONT}; color: {TEXT}; }}
  .q-drawer, .q-header, .q-page-container, .q-field, .q-btn, .q-table, .q-item,
  .q-tab, .q-tooltip, .q-menu, .q-notification {{ font-family: {FONT}; }}

  /* ---- type scale: 12 px is the floor; eyebrows earn 11 with weight ---- */
  .sx-title {{ font-size: 20px; font-weight: 600; letter-spacing: -0.01em; line-height: 1.2; }}
  .sx-section {{ font-size: 16px; font-weight: 600; line-height: 1.3; }}
  .sx-body {{ font-size: 14px; line-height: 1.5; }}
  .sx-data {{ font-size: 13px; font-variant-numeric: tabular-nums; }}
  .sx-caption {{ font-size: 12px; line-height: 1.4; color: {TEXT_2}; }}
  .sx-eyebrow {{ font-size: 11px; font-weight: 600; letter-spacing: 0.08em;
                 text-transform: uppercase; color: {TEXT_3}; }}
  .sx-kpi {{ font-size: 24px; font-weight: 600; letter-spacing: -0.02em; line-height: 1;
             font-variant-numeric: tabular-nums; }}
  .sx-muted {{ color: {TEXT_2}; }}
  .sx-faint {{ color: {TEXT_3}; }}
  .sx-mono {{ font-family: {MONO}; }}
  .sx-num {{ font-variant-numeric: tabular-nums; }}

  /* ---- surfaces ---- */
  .sx-card {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 10px; }}
  .sx-tile {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 8px; }}
  .sx-row--selected {{ background: {SURFACE_3}; }}
  .sx-hover:hover {{ background: {SURFACE_3}; }}

  /* ---- motion: feedback only ---- */
  .sx-reveal {{ animation: sxin 180ms cubic-bezier(0.23,1,0.32,1) both; }}
  @keyframes sxin {{ from {{ opacity: 0; transform: translateY(4px); }} }}
  .q-btn {{ transition: transform 140ms cubic-bezier(0.23,1,0.32,1); }}
  .q-btn:active {{ transform: scale(0.97); }}
  .q-btn:focus-visible, a:focus-visible, .q-checkbox:focus-visible {{
    outline: 2px solid {BRAND}; outline-offset: 2px; }}

  /* ---- uploads are quiet rows: the accent belongs to the action ---- */
  .q-uploader {{ background: {SURFACE_2} !important; border: 1px solid {LINE} !important;
                 border-radius: 8px; box-shadow: none !important; }}
  .q-uploader .q-uploader__header {{ background: transparent !important; color: {TEXT} !important; }}
  .q-uploader .q-uploader__header .q-btn {{ color: {TEXT_2}; }}
  .q-uploader__title {{ font-size: 13px; font-weight: 600; }}
  .q-uploader__subtitle {{ font-size: 12px; color: {TEXT_2}; }}
  .q-uploader__list {{ background: transparent; }}
  .q-uploader__file {{ border-color: {LINE} !important; }}
  .q-uploader__file-header {{ font-size: 12px; }}
  .q-uploader__file-header-content .q-uploader__title {{ font-weight: 400; font-family: {MONO}; }}

  /* ---- tables ---- */
  .q-table th {{ font-size: 11px; font-weight: 600; letter-spacing: 0.06em;
                 text-transform: uppercase; color: {TEXT_3}; }}
  .q-table td {{ font-size: 13px; font-variant-numeric: tabular-nums; }}
  .q-table__bottom {{ font-size: 12px; color: {TEXT_2}; }}

  /* ---- toggle chips (real buttons) ---- */
  .sx-toggle {{ border: 1px solid {LINE}; border-radius: 999px; background: {SURFACE_2};
                color: {TEXT_2}; font-size: 12px; font-weight: 600; min-height: 26px; }}
  .sx-toggle[aria-pressed="true"] {{ background: {wash(BRAND)}; color: {BRAND};
                                     border-color: {BRAND}; }}
  .sx-toggle .q-btn__content {{ text-transform: none; }}

  /* ---- step bar ---- */
  .sx-steps {{ position: sticky; top: 0; z-index: 5; background: {CANVAS};
               padding: 8px 0; border-bottom: 1px solid {LINE}; }}
  .sx-step {{ border: 1px solid {LINE}; border-radius: 6px; padding: 4px 10px;
              font-size: 12px; color: {TEXT_2}; display: flex; gap: 6px; align-items: center;
              min-height: 30px; text-decoration: none; }}
  .sx-step--done {{ border-color: {STATUS['ok']}; color: {STATUS['ok']}; }}
  .sx-step--current {{ border-color: {BRAND}; color: {BRAND}; background: {wash(BRAND)};
                       font-weight: 600; }}
  .sx-step--blocked {{ border-color: {STATUS['blocker']}; color: {STATUS['blocker']}; }}
  .sx-step--waiting {{ border-style: dashed; color: {TEXT_3}; }}

  /* ---- navigation rail ---- */
  .sx-nav {{ display: flex; align-items: center; gap: 8px; padding: 6px 8px;
             border-radius: 6px; color: {TEXT}; font-size: 13.5px; }}
  .sx-nav:hover {{ background: {SURFACE_3}; }}
  .sx-nav--active {{ background: {wash(BRAND)}; color: {BRAND}; font-weight: 600; }}

  /* a circuit chart row no build carries is an empty row — it has to read as
     a finding rather than as whitespace */
  .sx-never > td {{ background: {wash(STATUS['blocker'])} !important; }}

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
