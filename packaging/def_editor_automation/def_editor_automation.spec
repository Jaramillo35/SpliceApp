# -*- mode: python ; coding: utf-8 -*-
# Build:  pyinstaller def_editor_automation.spec

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    # comtypes builds its UIA wrappers at run time and pywinauto reaches them
    # dynamically, so PyInstaller cannot see them by static analysis and the
    # exe starts but cannot attach without these named explicitly.
    hiddenimports=[
        'comtypes.stream',
        'comtypes.gen',
        'pywinauto.controls.uia_controls',
        'pywinauto.uia_defines',
        'pywinauto.uia_element_info',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['numpy', 'pandas', 'matplotlib', 'PIL'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='DEFEditorAutomation',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
