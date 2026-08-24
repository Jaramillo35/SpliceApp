# -*- mode: python ; coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

# PyInstaller executes spec files via exec(), so __file__ is not guaranteed.
if "SPECPATH" in globals():
    _spec_dir = Path(SPECPATH).resolve()
    ROOT = _spec_dir.parents[1]
else:
    ROOT = Path.cwd().resolve()

streamlit_datas, streamlit_bins, streamlit_hidden = collect_all("streamlit")

# Altair ships the Vega-Lite JSON schemas it validates every chart against as
# package data, so the SECR Database charts fail at runtime in a frozen build
# unless the whole package comes along. Narwhals is altair 6's dataframe layer.
altair_datas, altair_bins, altair_hidden = collect_all("altair")
narwhals_datas, narwhals_bins, narwhals_hidden = collect_all("narwhals")

extra_datas = [
    (str(ROOT / "app.py"), "."),
    (str(ROOT / "feedback_system.py"), "."),
    (str(ROOT / "pages"), "pages"),
    (str(ROOT / "ui"), "ui"),
    (str(ROOT / "splice"), "splice"),
    (str(ROOT / "secrdb"), "secrdb"),
    (str(ROOT / "assets"), "assets"),
    (str(ROOT / ".streamlit"), ".streamlit"),
    (str(ROOT / "vbom_legacy"), "vbom_legacy"),
]

datas = streamlit_datas + altair_datas + narwhals_datas + extra_datas
binaries = streamlit_bins + altair_bins + narwhals_bins

hiddenimports = list(
    set(
        streamlit_hidden
        + altair_hidden
        + narwhals_hidden
        + [
            "feedback_system",
            "numpy",
            "numpy._core._exceptions",
            "openpyxl",
            "pandas",
            "pyarrow",
            "sympy",
            "xlrd",
            "xlsxwriter",
            # The SECR Database is reached only through Streamlit page modules,
            # so nothing statically imports these — name them explicitly.
            "splice.secr.api",
            "splice.secr.db",
            "splice.secr.generation",
            "splice.secr.identity",
            "splice.secr.importer",
            "splice.secr.parse",
            # Merged SECR Database vertical (vendored core + local assistant).
            "secrdb",
            "secrdb.config",
            "secrdb.diagnostics",
            "secrdb.assistant.agent",
            "secrdb.assistant.grounding",
            "secrdb.assistant.ollama",
            "secrdb.assistant.tools",
            "secrdb.core.dtcr.library",
            "secrdb.core.dtcr.matching",
            "secrdb.core.secr.api",
            "secrdb.core.secr.batch",
            "secrdb.core.secr.db",
            "secrdb.core.secr.enrich",
            "secrdb.core.secr.generation",
            "secrdb.core.secr.identity",
            "secrdb.core.secr.importer",
            "requests",
            # HRN Chart Builder engine (reached only through a page module).
            "splice.hrncmp.engine",
            "splice.inline.health",
            # Meeting Transcripts: uiautomation loads comtypes.stream
            # dynamically, so PyInstaller cannot see it statically.
            "uiautomation",
            "comtypes",
            "comtypes.stream",
            "splice.transcripts.recorder",
        ]
    )
)

block_cipher = None

a = Analysis(
    [str(ROOT / "packaging" / "windows" / "streamlit_bootstrap.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "numpy.tests",
        "pandas.tests",
        "sympy.testing",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SpliceApp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SpliceApp",
)
