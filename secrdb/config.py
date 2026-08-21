"""Environment and paths for the SECR Database pages inside Splice.

The SECR engineering core is vendored under ``secrdb.core`` (schema v6, ahead
of the legacy ``splice.secr`` v3 core that the retired SECR Management page
used). Since the merge into Splice, all paths delegate to :mod:`splice.config`
so the whole app shares one data directory and one database file — opening the
pre-merge Splice database migrates it in place (v3 -> v6, history preserved).

The historical ``SECRDB_*`` environment overrides still win when set, so an
install that pointed the standalone app at a custom location keeps working.
"""

from __future__ import annotations

import os
from pathlib import Path

from splice.config import (
    DATA_DIR as _SPLICE_DATA_DIR,
    SECR_DB_PATH as _SPLICE_SECR_DB_PATH,
    SECR_TEMPLATE_PATH as _SPLICE_SECR_TEMPLATE_PATH,
)

# secrdb/config.py -> secrdb/ -> project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent

APP_NAME = "SECR Database"


def _path_from_env(env_key: str, default: Path) -> Path:
    value = os.getenv(env_key)
    return Path(value).expanduser() if value else default


DATA_DIR = _path_from_env("SECRDB_DATA_DIR", _SPLICE_DATA_DIR)

#: The SECR database file — Splice's own database unless explicitly overridden.
SECR_DB_PATH = _path_from_env("SECRDB_DB_PATH", _SPLICE_SECR_DB_PATH)

#: The SECR workbook template ships with the app.
SECR_TEMPLATE_PATH = _path_from_env(
    "SECRDB_SECR_TEMPLATE", _SPLICE_SECR_TEMPLATE_PATH
)

# --- Local AI assistant ----------------------------------------------------
#: Ollama runs entirely on-premises. Point this at a shared internal host to
#: avoid installing a model on every engineer's PC; leave it at the default to
#: run against a local Ollama.
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("SECRDB_OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_K_M")
#: Generous on purpose. The first question of a session pays for loading ~4.7GB
#: of weights off disk, and on a CPU-only corporate laptop that alone can exceed
#: two minutes — field reports showed every first question timing out at 120s
#: while Ollama was running perfectly well. Once the model is resident, answers
#: come back in seconds and this ceiling is never approached.
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("SECRDB_OLLAMA_TIMEOUT", "600"))

#: How long Ollama keeps the model in memory after a request. The default is
#: 5 minutes, so a session's second question often pays the cold start again.
OLLAMA_KEEP_ALIVE = os.getenv("SECRDB_OLLAMA_KEEP_ALIVE", "30m")

#: The assistant is optional. When Ollama is unreachable the rest of the app
#: must work exactly as before.
ASSISTANT_ENABLED = os.getenv("SECRDB_ASSISTANT", "1").strip().lower() not in (
    "0",
    "false",
    "off",
)

def configure_environment() -> None:
    """Prepare the runtime: make sure the data directory exists."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
