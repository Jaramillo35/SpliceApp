"""Design tokens and the one shared stylesheet.

Every custom surface is expressed in Streamlit's own CSS variables
(``--primary-color``, ``--background-color``, ``--secondary-background-color``,
``--text-color``) plus ``color-mix`` tints of them — so cards, badges, and the
hero render correctly in the branded dark theme *and* if a user flips to light
from the app menu. No hardcoded light-only hex anywhere (the defect that made
the old home page unreadable in dark mode).

Chart colors are the validated categorical palette from docs/UI_UX_AUDIT.md —
run the dataviz validator again if the order or hues ever change.
"""

from __future__ import annotations

import streamlit as st

#: Brand
PRIMARY = "#d95926"

#: Validated categorical chart palette (orange-first). Light / dark steps.
CHART_LIGHT = ["#eb6834", "#2a78d6", "#1baf7a", "#eda100",
               "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
CHART_DARK = ["#d95926", "#3987e5", "#199e70", "#c98500",
              "#d55181", "#008300", "#9085e9", "#e66767"]

#: Status colors (icon + label always accompany them — never color alone)
STATUS = {
    "blocker": "#e66767",
    "high": "#c98500",
    "review": "#d5c04b",
    "ok": "#199e70",
    "info": "#3987e5",
}

#: Surface tokens per rendered mode. Streamlit (1.58) exposes no theme CSS
#: variables to the page, so we define our own from the theme actually being
#: rendered (st.context.theme reports it, so a user flipping to light from
#: the menu still gets readable surfaces).
_MODE_TOKENS = {
    "dark": {"bg2": "#1a1d24", "text": "#e8e8ec"},
    "light": {"bg2": "#f1f3f7", "text": "#1d1d1f"},
}


def _root_vars() -> str:
    try:
        mode = st.context.theme.type  # "light" | "dark"
    except Exception:
        mode = "dark"
    t = _MODE_TOKENS.get(mode, _MODE_TOKENS["dark"])
    return (f":root {{ --sx-primary: {PRIMARY}; --sx-bg2: {t['bg2']}; "
            f"--sx-text: {t['text']}; }}")


_CSS = """
<style>
%ROOT%
:root { --sx-line: color-mix(in srgb, var(--sx-text) 14%, transparent); }

.sx-hero {
    padding: 1.4rem 1.6rem;
    border-radius: 14px;
    border: 1px solid var(--sx-line);
    background: linear-gradient(
        135deg,
        color-mix(in srgb, var(--sx-primary) 14%, var(--sx-bg2)) 0%,
        var(--sx-bg2) 60%);
    margin-bottom: 1.1rem;
}
.sx-hero h1 { margin: 0 0 .3rem 0; font-size: 1.75rem; letter-spacing: -0.02em;
              color: var(--sx-text); }
.sx-hero p  { margin: 0; color: color-mix(in srgb, var(--sx-text) 72%, transparent); }

.sx-card {
    border: 1px solid var(--sx-line);
    border-radius: 12px;
    padding: 1rem 1.1rem;
    background: var(--sx-bg2);
    min-height: 185px;
}
.sx-card .sx-title { font-size: 1.08rem; font-weight: 700; margin-bottom: .45rem;
                     letter-spacing: -0.01em; color: var(--sx-text); }
.sx-card .sx-desc  { color: color-mix(in srgb, var(--sx-text) 74%, transparent);
                     font-size: .92rem; line-height: 1.45; margin-bottom: .8rem; }

.sx-badge {
    display: inline-block;
    padding: .16rem .55rem;
    border-radius: 999px;
    font-size: .74rem;
    font-weight: 600;
    background: color-mix(in srgb, var(--sx-primary) 16%, transparent);
    color: color-mix(in srgb, var(--sx-primary) 85%, var(--sx-text));
    margin: 0 .3rem .3rem 0;
}

.sx-chip {
    display: inline-flex; align-items: center; gap: .35rem;
    padding: .18rem .6rem; border-radius: 999px;
    font-size: .8rem; font-weight: 600;
    border: 1px solid color-mix(in srgb, var(--sx-chip-c) 45%, transparent);
    background: color-mix(in srgb, var(--sx-chip-c) 14%, transparent);
    color: var(--sx-chip-c);
}
</style>
"""


def inject() -> None:
    """Mount the shared stylesheet. Call once per page, right after set-up."""
    st.markdown(_CSS.replace("%ROOT%", _root_vars()), unsafe_allow_html=True)
