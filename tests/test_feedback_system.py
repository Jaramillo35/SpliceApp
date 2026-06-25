from __future__ import annotations

import feedback_system
from feedback_system import FeedbackStore, get_feedback_area_options


def test_submit_ticket_persists_and_exports(tmp_path):
    storage_path = tmp_path / "tickets.json"
    store = FeedbackStore(storage_path=storage_path)

    ticket_id = store.submit_ticket(
        reported_by="Jane Doe",
        workflow="DTx Compare Report",
        area="PreOrder Generation List",
        description="The workbook download failed after generating the report.",
        category="bug",
        severity="high",
    )

    assert ticket_id.startswith("TKT-")
    tickets = store.load_tickets()
    assert len(tickets) == 1
    assert tickets[0]["reported_by"] == "Jane Doe"
    assert tickets[0]["workflow"] == "DTx Compare Report"
    assert tickets[0]["area"] == "PreOrder Generation List"
    assert tickets[0]["status"] == "new"

    csv_bytes = store.export_tickets(format="csv")
    assert b"ticket_id" in csv_bytes
    assert b"Jane Doe" in csv_bytes


def test_feedback_area_options_include_site_workflows():
    options = get_feedback_area_options(workflow="DTx Compare Report", area="PreOrder Generation List")
    assert "DTx Compare Report" in options
    assert "VBOM Risk Matrix" in options
    assert "PreOrder Generation List" in options


def test_submit_ticket_and_sync_invokes_github_sync(tmp_path, monkeypatch):
    storage_path = tmp_path / "tickets.json"
    store = FeedbackStore(storage_path=storage_path)
    called = {}

    def fake_sync(**_kwargs):
        called["sync"] = True
        return {"ok": True, "message": "synced"}

    monkeypatch.setattr(store, "sync_to_github", fake_sync)

    ticket_id, sync_result = store.submit_ticket_and_sync(
        reported_by="Jane Doe",
        workflow="Splice Generation",
        area="Upload flow",
        description="The upload button was not obvious.",
        category="feedback",
        severity="medium",
    )

    assert ticket_id.startswith("TKT-")
    assert called["sync"] is True
    assert sync_result["ok"] is True
    assert len(store.load_tickets()) == 1


def test_get_config_value_falls_back_to_streamlit_secret(monkeypatch):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.setattr(feedback_system, "_get_streamlit_secret", lambda *_keys: "Jaramillo35/SpliceApp")
    assert feedback_system._get_config_value("GITHUB_REPOSITORY") == "Jaramillo35/SpliceApp"
