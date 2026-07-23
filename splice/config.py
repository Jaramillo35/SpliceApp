"""Environment-specific configuration: filesystem paths, tokens, feature flags.

Everything here resolves from an environment variable first (so the internal
server can be configured without code edits) and otherwise falls back to a
default relative to the project root. Keeping this in one module means moving a
engine into the ``splice`` package no longer changes where it looks for the
SECR template or the database.

Streamlit secrets are read lazily via :func:`get_secret` so importing this
module never requires Streamlit to be installed or running.
"""

from __future__ import annotations

import os
from pathlib import Path

# splice/config.py -> splice/ -> project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _path_from_env(env_key: str, default: Path) -> Path:
    """Return ``$env_key`` as an expanded path, or ``default`` if unset/empty."""
    value = os.getenv(env_key)
    return Path(value).expanduser() if value else default


# --- Directories -----------------------------------------------------------
DATA_DIR = _path_from_env("SPLICE_DATA_DIR", PROJECT_ROOT / "data")
ASSETS_DIR = _path_from_env("SPLICE_ASSETS_DIR", PROJECT_ROOT / "assets")

# --- Files -----------------------------------------------------------------
SECR_DB_PATH = _path_from_env("SPLICE_SECR_DB_PATH", DATA_DIR / "secr_database.db")
SECR_TEMPLATE_PATH = _path_from_env("SPLICE_SECR_TEMPLATE", ASSETS_DIR / "SECR_TEMPLATE.xlsx")
TICKETS_PATH = _path_from_env("SPLICE_TICKETS_PATH", DATA_DIR / "tickets.json")
PREORDER_EXE_PATH = _path_from_env(
    "PREORDER_GENERATION_EXE_PATH", ASSETS_DIR / "downloads" / "PreOrderListGen.exe"
)

# Legacy VBOM desktop module, loaded dynamically by splice.vbom. Kept at the
# project root; the alternate candidates preserve the previous lookup order.
VBOM_LEGACY_DIR = _path_from_env("SPLICE_VBOM_LEGACY_DIR", PROJECT_ROOT / "vbom_legacy")
VBOM_ROOT_CANDIDATES = [
    VBOM_LEGACY_DIR,
    PROJECT_ROOT.parent / "VBOMxRISKMATRIX 2",
    PROJECT_ROOT.parent / "VBOMxRISKMATRIX 2" / "VBOMxRISKMATRIX 2",
    Path("/mount/src/VBOMxRISKMATRIX 2"),
]


def get_secret(*keys: str, default: str | None = None) -> str | None:
    """Look up a value from the environment, then Streamlit secrets.

    Accepts several candidate keys and returns the first that resolves. Safe to
    call from non-Streamlit contexts: if Streamlit is unavailable or has no
    secrets configured, only the environment is consulted.
    """
    for key in keys:
        value = os.getenv(key)
        if value:
            return value
    try:
        import streamlit as st  # imported lazily; optional dependency for the core

        for key in keys:
            if key in st.secrets:
                return str(st.secrets[key])
    except Exception:
        pass
    return default
