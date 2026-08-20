"""splice-api — a FastAPI gateway over the Splice DTx/DTCR engines.

This is the *versioned service boundary* (ADR-0004): UIs, the SECR assistant, and any
external consumer talk HTTP here instead of importing ``splice`` internals directly. The
engines stay pure-Python and untouched; this layer only marshals uploads → engine calls →
downloads/JSON.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
