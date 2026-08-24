"""Shared UI components — one look, built once, used by every page.

Import and use these instead of hand-rolled markdown so pages stay thin and
the app reads as one product. All styling lives in :mod:`ui.theme`.
"""

from __future__ import annotations

import html as _html

import streamlit as st

from ui import theme


def page_header(title: str, caption: str = "") -> None:
    """Standard page opening: injects the stylesheet, then title + caption.

    The title must equal the page's name in the navigation — one identity.
    """
    theme.inject()
    st.title(title)
    if caption:
        st.caption(caption)


def hero(title: str, subtitle: str) -> None:
    theme.inject()
    st.markdown(
        f"""
        <div class="sx-hero">
            <h1>{_html.escape(title)}</h1>
            <p>{_html.escape(subtitle)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def tool_card(title: str, desc: str, badges: list[str]) -> None:
    badge_html = "".join(
        f'<span class="sx-badge">{_html.escape(b)}</span>' for b in badges)
    st.markdown(
        f"""
        <div class="sx-card">
            <div class="sx-title">{_html.escape(title)}</div>
            <div class="sx-desc">{_html.escape(desc)}</div>
            {badge_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def status_chip(kind: str, label: str) -> str:
    """Inline HTML for a status chip (icon + label — never color alone).

    ``kind`` is one of ui.theme.STATUS keys: blocker/high/review/ok/info.
    Returns markup to embed via st.markdown(..., unsafe_allow_html=True).
    """
    color = theme.STATUS.get(kind, theme.STATUS["info"])
    icon = {"blocker": "⛔", "high": "▲", "review": "◆", "ok": "✔", "info": "ℹ"}.get(kind, "•")
    return (f'<span class="sx-chip" style="--sx-chip-c:{color}">'
            f'{icon} {_html.escape(label)}</span>')


def empty_state(message: str, icon: str = "📄") -> None:
    st.info(message, icon=icon)
