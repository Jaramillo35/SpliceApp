from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def test_frozen_runtime_uses_local_app_data(monkeypatch, tmp_path: Path) -> None:
    bootstrap_path = (
        Path(__file__).resolve().parents[1]
        / "packaging"
        / "windows"
        / "streamlit_bootstrap.py"
    )
    spec = importlib.util.spec_from_file_location("splice_streamlit_bootstrap", bootstrap_path)
    assert spec is not None and spec.loader is not None
    bootstrap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bootstrap)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("SPLICE_DATA_DIR", raising=False)

    bootstrap._configure_frozen_runtime()

    expected = tmp_path / "SpliceApp"
    assert os.environ["SPLICE_DATA_DIR"] == str(expected)
    assert expected.is_dir()


def test_feedback_store_writes_valid_json_under_concurrency(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setitem(sys.modules, "streamlit", types.ModuleType("streamlit"))
    sys.modules.pop("feedback_system", None)
    feedback_system = importlib.import_module("feedback_system")
    store = feedback_system.FeedbackStore(tmp_path / "tickets.json")

    def submit(index: int) -> str:
        return store.submit_ticket(
            reported_by=f"user-{index}",
            workflow="SECR",
            area="Enrichment",
            description=f"ticket-{index}",
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        ticket_ids = list(executor.map(submit, range(20)))

    payload = json.loads((tmp_path / "tickets.json").read_text(encoding="utf-8"))
    assert len(payload) == 20
    assert len(set(ticket_ids)) == 20
    assert {ticket["description"] for ticket in payload} == {
        f"ticket-{index}" for index in range(20)
    }
