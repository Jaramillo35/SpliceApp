"""Fail-fast validation for the production source and Windows build kit."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REQUIRED_FILES = [
    ROOT / "app.py",
    ROOT / "feedback_system.py",
    ROOT / "assets" / "SECR_TEMPLATE.xlsx",
    ROOT / "assets" / "versigent_logo_horizontal.jpg",
    ROOT / "vbom_legacy" / "main_app.py",
    ROOT / "vbom_legacy" / "Template.xlsx",
    ROOT / "packaging" / "windows" / "SpliceApp.spec",
    ROOT / "packaging" / "windows" / "streamlit_bootstrap.py",
]

REQUIRED_MODULES = [
    "streamlit",
    "altair",
    "pandas",
    "pyarrow",
    "openpyxl",
    "xlsxwriter",
    "sympy",
    "xlrd",
    "splice.splice_gen",
    "splice.dtx_compare",
    "splice.secr",
    "splice.secr.api",
    "splice.secr.db",
    "splice.secr.generation",
    "splice.secr.identity",
    "splice.secr.importer",
    "splice.secr.parse",
    "splice.vbom",
]


def main() -> int:
    missing_files = [str(path.relative_to(ROOT)) for path in REQUIRED_FILES if not path.is_file()]
    if missing_files:
        print(f"Missing required production files: {', '.join(missing_files)}", file=sys.stderr)
        return 1

    spec_text = (ROOT / "packaging" / "windows" / "SpliceApp.spec").read_text(
        encoding="utf-8"
    )
    required_spec_entries = [
        'collect_all("streamlit")',
        'collect_all("altair")',
        '"splice.secr.parse"',
        '"feedback_system"',
        '"pandas"',
        '"pyarrow"',
        '"sympy"',
        '"xlrd"',
        '"xlsxwriter"',
        'ROOT / "feedback_system.py"',
        'ROOT / "splice"',
        'ROOT / "vbom_legacy"',
    ]
    missing_spec_entries = [entry for entry in required_spec_entries if entry not in spec_text]
    if missing_spec_entries:
        print(
            f"Windows spec is missing required entries: {', '.join(missing_spec_entries)}",
            file=sys.stderr,
        )
        return 1
    if 'ROOT / "data"' in spec_text:
        print("Windows spec must not bundle mutable runtime data.", file=sys.stderr)
        return 1

    # The SECR database is engineering history that belongs to whoever runs the
    # app: it is created empty on first use and must never travel in the build
    # kit or the executable.
    shipped_databases = [
        str(path.relative_to(ROOT))
        for path in ROOT.rglob("*.db")
        if "dist" not in path.parts and ".git" not in path.parts
        and "data" not in path.parts
    ]
    if shipped_databases:
        print(
            "Database files must not be part of the build kit: "
            + ", ".join(shipped_databases),
            file=sys.stderr,
        )
        return 1
    forbidden_collect_all = [
        package
        for package in ("pandas", "numpy", "openpyxl", "xlrd", "xlsxwriter", "sympy")
        if f'collect_all("{package}")' in spec_text
    ]
    if forbidden_collect_all:
        print(
            "Windows spec broadly collects test/development modules for: "
            + ", ".join(forbidden_collect_all),
            file=sys.stderr,
        )
        return 1

    bootstrap_text = (
        ROOT / "packaging" / "windows" / "streamlit_bootstrap.py"
    ).read_text(encoding="utf-8")
    if '"--self-test"' not in bootstrap_text:
        print("Windows bootstrap is missing the frozen runtime self-test.", file=sys.stderr)
        return 1

    import_failures: list[str] = []
    for module_name in REQUIRED_MODULES:
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001 - validation must report every import failure
            import_failures.append(f"{module_name}: {exc}")
    if import_failures:
        print("Production import validation failed:", file=sys.stderr)
        for failure in import_failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    import openpyxl
    from splice.vbom.workflow import _load_vbom_module

    template = openpyxl.load_workbook(
        ROOT / "assets" / "SECR_TEMPLATE.xlsx",
        read_only=True,
        data_only=False,
    )
    try:
        if "Summary" not in template.sheetnames:
            print("SECR template is missing the Summary sheet.", file=sys.stderr)
            return 1
    finally:
        template.close()

    vbom_module = _load_vbom_module()
    required_vbom_api = [
        "build_vin_matrix",
        "read_complexity_sheet",
        "build_outputs",
        "create_formatted_output",
    ]
    missing_vbom_api = [name for name in required_vbom_api if not hasattr(vbom_module, name)]
    if missing_vbom_api:
        print(
            f"VBOM runtime is missing required functions: {', '.join(missing_vbom_api)}",
            file=sys.stderr,
        )
        return 1

    deprecated_hits: list[str] = []
    for path in [*ROOT.glob("pages/*.py"), *ROOT.glob("ui/pages/*.py")]:
        if "use_container_width" in path.read_text(encoding="utf-8"):
            deprecated_hits.append(str(path.relative_to(ROOT)))
    if deprecated_hits:
        print(
            f"Deprecated Streamlit use_container_width remains in: {', '.join(deprecated_hits)}",
            file=sys.stderr,
        )
        return 1

    print("Production source validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
