from __future__ import annotations

import importlib
import io
import os
import sys
from pathlib import Path


def _resolve_app_root() -> Path:
    """Resolve app root for source and frozen (PyInstaller) modes."""
    if getattr(sys, "frozen", False):
        # PyInstaller unpacks the bundle to _MEIPASS at runtime.
        return Path(getattr(sys, "_MEIPASS", Path.cwd()))
    return Path(__file__).resolve().parents[2]


def _configure_frozen_runtime() -> None:
    """Place mutable files outside PyInstaller's read-only application payload."""
    if not getattr(sys, "frozen", False):
        return

    configured = os.environ.get("SPLICE_DATA_DIR")
    if configured:
        data_dir = Path(configured)
    else:
        local_app_data = os.environ.get("LOCALAPPDATA")
        base_dir = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        data_dir = base_dir / "SpliceApp"

    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["SPLICE_DATA_DIR"] = str(data_dir)


def _self_test_secr_database() -> None:
    """Prove the SECR database can be created, written and read when frozen.

    Runs against a throwaway file, never the user's database: the shipped app
    must start with an empty database that the engineer populates on this
    machine, so the self-test must not create or touch the real one.
    """
    import contextlib
    import sqlite3
    import tempfile

    from splice.config import SECR_DB_PATH
    from secrdb.core.secr import db as secr_db

    # Windows refuses to delete a file that still has an open handle, so the
    # temp directory only cleans up if every connection was closed. That makes
    # this a real check that the database releases its file, not just that it
    # can be written.
    with tempfile.TemporaryDirectory() as temp_dir:
        probe = Path(temp_dir) / "self_test_secr.db"
        secr_db.init_db(probe)
        if not probe.is_file():
            raise RuntimeError("SECR database was not created")

        with secr_db.connect(probe) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        if version != secr_db.SCHEMA_VERSION:
            raise RuntimeError(
                f"SECR schema version is {version}, expected {secr_db.SCHEMA_VERSION}"
            )
        expected = {"secr", "secr_change", "secr_sequence", "secr_source_file"}
        if not expected <= tables:
            raise RuntimeError(f"SECR schema is incomplete: {sorted(tables)}")

        if secr_db.list_secrs(db_path=probe):
            raise RuntimeError("A freshly created SECR database is not empty")
        if secr_db.peek_next_secr_number("2028", "X1", db_path=probe) != 1000:
            raise RuntimeError("SECR numbering does not start at 1000")

    # The real database must be creatable where the app will put it, but is
    # deliberately left alone here.
    try:
        SECR_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(
            f"SECR database location is not writable: {SECR_DB_PATH.parent} ({exc})"
        ) from exc
    print(f"SECR database location: {SECR_DB_PATH}")
    if SECR_DB_PATH.exists():
        # closing(), not `with sqlite3.connect(...)`: the latter manages the
        # transaction and leaves the handle open, which would lock the user's
        # real database for the rest of this process.
        with contextlib.closing(sqlite3.connect(str(SECR_DB_PATH))) as conn:
            stored = conn.execute("SELECT COUNT(*) FROM secr").fetchone()[0]
        print(f"  existing database found with {stored} SECR record(s)")
    else:
        print("  no database yet — it is created empty on first use")


def _self_test_charts() -> None:
    """The SECR Database charts need altair's bundled Vega-Lite schemas."""
    import altair as alt
    import pandas as pd

    frame = pd.DataFrame([{"name": "IP", "n": 3}, {"name": "BODY", "n": 1}])
    chart = (
        alt.Chart(frame)
        .mark_bar()
        .encode(y=alt.Y("name:N"), x=alt.X("n:Q"))
        .add_params(alt.selection_point(fields=["name"], name="pick"))
    )
    spec = chart.to_json()
    if '"pick"' not in spec:
        raise RuntimeError("Altair chart lost its selection parameter")


def _run_self_test(app_root: Path) -> int:
    """Verify frozen imports/assets without starting the Streamlit server."""
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))

    required_files = [
        app_root / "app.py",
        app_root / "feedback_system.py",
        app_root / "assets" / "SECR_TEMPLATE.xlsx",
        app_root / "assets" / "versigent_logo_horizontal.jpg",
        app_root / "vbom_legacy" / "main_app.py",
        app_root / "vbom_legacy" / "Template.xlsx",
    ]
    missing_files = [str(path) for path in required_files if not path.is_file()]
    if missing_files:
        raise FileNotFoundError(f"Packaged runtime files are missing: {missing_files}")

    required_modules = [
        "feedback_system",
        "splice.common.logging",
        "splice.splice_gen",
        "splice.dtx_compare",
        "secrdb.core.secr",
        "secrdb.core.secr.api",
        "secrdb.core.secr.db",
        "secrdb.core.secr.enrich",
        "secrdb.core.secr.generation",
        "secrdb.core.secr.identity",
        "secrdb.core.secr.importer",
        "secrdb.core.secr.parse",
        "splice.vbom",
    ]
    for module_name in required_modules:
        importlib.import_module(module_name)

    _self_test_secr_database()
    _self_test_charts()

    import openpyxl
    import pandas as pd
    import pyarrow as pa
    import sympy
    import xlrd
    import xlsxwriter

    assert sympy.simplify_logic(sympy.And(sympy.Symbol("A"), sympy.Symbol("B")))
    assert pa.table({"value": [1]}).num_rows == 1
    assert xlrd.__version__
    assert xlsxwriter.__version__

    for engine in ("openpyxl", "xlsxwriter"):
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine=engine) as writer:
            pd.DataFrame({"value": [1]}).to_excel(writer, index=False)
        if not output.getvalue():
            raise RuntimeError(f"{engine} failed to generate an in-memory workbook")

    template = openpyxl.load_workbook(
        app_root / "assets" / "SECR_TEMPLATE.xlsx",
        read_only=True,
    )
    try:
        if "Summary" not in template.sheetnames:
            raise RuntimeError("Packaged SECR template is missing the Summary sheet")
    finally:
        template.close()

    from splice.vbom.workflow import _load_vbom_module

    vbom_module = _load_vbom_module()
    for function_name in (
        "build_vin_matrix",
        "read_complexity_sheet",
        "build_outputs",
        "create_formatted_output",
    ):
        if not hasattr(vbom_module, function_name):
            raise AttributeError(f"VBOM runtime is missing {function_name}")

    print("SpliceApp frozen runtime self-test passed.")
    return 0


def main() -> int:
    _configure_frozen_runtime()
    app_root = _resolve_app_root()
    if "--self-test" in sys.argv:
        return _run_self_test(app_root)

    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))
    app_file = app_root / "app.py"
    if not app_file.exists():
        raise FileNotFoundError(f"Unable to find app entrypoint: {app_file}")

    # Keep the app local-only for desktop team distribution.
    host = os.environ.get("SPLICE_HOST", "127.0.0.1")
    port = os.environ.get("SPLICE_PORT", "8501")

    # Streamlit settings for predictable local desktop behavior.
    os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    os.environ.setdefault("STREAMLIT_GLOBAL_DEVELOPMENT_MODE", "false")

    sys.argv = [
        "streamlit",
        "run",
        str(app_file),
        "--server.address",
        host,
        "--server.port",
        str(port),
        "--server.headless",
        "true",
        "--server.fileWatcherType",
        "none",
        "--server.runOnSave",
        "false",
        "--global.developmentMode",
        "false",
    ]

    from streamlit.web import cli as stcli

    return stcli.main()


if __name__ == "__main__":
    raise SystemExit(main())
