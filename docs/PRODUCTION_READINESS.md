# Production Readiness and Windows Distribution

## Runtime dependency audit

Every direct dependency in `requirements.txt` has a confirmed production use:

| Dependency | Production use |
|---|---|
| `streamlit` | Application server and UI |
| `pandas` | Workbook ingestion, transformation, and reporting |
| `openpyxl` | Excel template editing and `.xlsx`/`.xlsm` output |
| `xlsxwriter` | Splice and DTx report exporters |
| `sympy` | Sales-code Boolean simplification |
| `xlrd` | Supported legacy `.xls` input |

No direct runtime package can be removed without dropping a currently supported
workflow or file format. PyInstaller is a build-only dependency and is installed
by the Windows build script.

## Removed production redundancy

- Removed the metrics package and dashboard page because they were unreachable
  from `st.navigation` and unused by every active workflow.
- Removed the virtual-environment Windows installer/launcher path. Production
  distribution now has one supported path: the PyInstaller executable bundle.
- Removed unused imports. The local `splice` modules are included explicitly in
  the PyInstaller payload because Streamlit executes its page files dynamically;
  the Windows build also runs a frozen executable self-test before creating the
  distributable ZIP.
- Removed mutable `data/` files from the distributed application.

## Runtime hardening

- The frozen Windows app binds only to `127.0.0.1`.
- Runtime file watching and run-on-save are disabled in the executable.
- Feedback and the SQLite database resolve under
  `%LOCALAPPDATA%\SpliceApp`.
- Feedback JSON writes are locked and atomically replaced.
- GitHub feedback synchronization has bounded network timeouts.
- Temporary workbook directories are unique and cleaned after use.
- Uploaded filenames are reduced to their basename before writing locally.

## Build and release gates

1. Build on 64-bit Windows with Python 3.11 or 3.12.
2. Extract `SpliceApp-Windows.zip`.
3. Run `packaging\windows\build_windows_exe.bat`.
4. Confirm `scripts\validate_production.py` passes during the build.
5. Confirm the frozen executable self-test passes during the build.
6. Smoke-test all four workflows using approved known-good fixtures.
7. Verify `SpliceApp-Executable.zip` against its `.sha256` file.
8. Distribute the complete ZIP; never distribute `SpliceApp.exe` alone.

The Windows build includes the previously omitted VBOM runtime and explicitly
collects the required runtime packages. Broad collection is limited to
Streamlit's static frontend; pandas, NumPy, SymPy, and the Excel engines use
their standard PyInstaller hooks so test suites and development modules are not
shipped. It does not include local feedback, metrics history, or the developer's
SECR database.

## Release risks requiring organizational decisions

- The executable is not code-signed. A trusted code-signing certificate is
  recommended before broad enterprise distribution.
- Automated regression tests cover SECR enrichment, affected-item counts,
  per-user runtime storage, and concurrent feedback persistence. Full
  golden-workbook tests are still needed for every engineering workflow.
- The executable must receive a final smoke test on Windows; PyInstaller output
  cannot be produced or validated as a Windows binary from macOS.
