from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dtx_compare_engine import build_preorder_generation_command


def test_build_preorder_generation_command_includes_input_files(tmp_path: Path) -> None:
    executable = tmp_path / "PreOrderListGen.exe"
    executable.write_bytes(b"fake")
    old_file = tmp_path / "old.xlsx"
    new_file = tmp_path / "new.xlsx"
    old_file.write_bytes(b"old")
    new_file.write_bytes(b"new")

    command = build_preorder_generation_command(executable, old_file, new_file)

    assert command == [str(executable), str(old_file), str(new_file)]


def test_build_preorder_generation_command_requires_existing_executable(tmp_path: Path) -> None:
    missing_executable = tmp_path / "PreOrderListGen.exe"

    with pytest.raises(FileNotFoundError):
        build_preorder_generation_command(missing_executable, tmp_path / "old.xlsx", tmp_path / "new.xlsx")
