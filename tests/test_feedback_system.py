from __future__ import annotations

from feedback_system import FeedbackStore


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
