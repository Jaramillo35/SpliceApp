from __future__ import annotations

import base64
import json

from metrics.storage import JsonMetricsStorage


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def test_sync_to_github_merges_remote_and_local_metrics(tmp_path, monkeypatch) -> None:
    storage = JsonMetricsStorage(tmp_path / "impact_metrics.json")
    storage.create_workflow_run(
        {
            "id": "local-run",
            "workflow_id": "splice_generation",
            "anonymous_session_id": "local-session",
            "status": "completed",
            "created_at": "2026-07-15T10:00:00+00:00",
        }
    )

    monkeypatch.setenv("GITHUB_REPOSITORY", "Jaramillo35/SpliceApp")
    monkeypatch.setenv("GITHUB_TOKEN", "token")

    remote_payload = {
        "workflow_runs": [
            {
                "id": "remote-run",
                "workflow_id": "vbom_risk_matrix",
                "anonymous_session_id": "remote-session",
                "status": "completed",
                "created_at": "2026-07-15T09:00:00+00:00",
            }
        ],
        "workflow_feedback": [
            {
                "workflow_run_id": "remote-run",
                "workflow_id": "vbom_risk_matrix",
                "created_at": "2026-07-15T09:05:00+00:00",
            }
        ],
    }
    captured: dict[str, dict] = {}

    def fake_urlopen(req):
        if req.get_method() == "GET":
            return _FakeResponse(
                {
                    "sha": "remote-sha",
                    "content": base64.b64encode(json.dumps(remote_payload).encode("utf-8")).decode("utf-8"),
                }
            )

        body = json.loads(req.data.decode("utf-8"))
        captured["put"] = body
        return _FakeResponse({"content": {"html_url": "https://github.com/Jaramillo35/SpliceApp/blob/main/data/impact_metrics.json"}})

    monkeypatch.setattr("metrics.storage.request.urlopen", fake_urlopen)

    result = storage.sync_to_github()

    assert result["ok"] is True
    uploaded = json.loads(base64.b64decode(captured["put"]["content"]).decode("utf-8"))
    assert {row["id"] for row in uploaded["workflow_runs"]} == {"remote-run", "local-run"}
    assert {row["workflow_run_id"] for row in uploaded["workflow_feedback"]} == {"remote-run"}


def test_create_workflow_feedback_triggers_github_sync(tmp_path, monkeypatch) -> None:
    storage = JsonMetricsStorage(tmp_path / "impact_metrics.json")
    called: list[str] = []

    monkeypatch.setattr(storage, "sync_to_github", lambda: called.append("sync") or {"ok": True})

    storage.create_workflow_feedback(
        {
            "id": "feedback-id",
            "workflow_run_id": "run-id",
            "workflow_id": "splice_generation",
            "anonymous_session_id": "session-id",
            "created_at": "2026-07-15T12:00:00+00:00",
        }
    )

    assert called == ["sync"]


def test_failed_run_update_triggers_github_sync(tmp_path, monkeypatch) -> None:
    storage = JsonMetricsStorage(tmp_path / "impact_metrics.json")
    called: list[str] = []
    storage.create_workflow_run({"id": "run-id", "status": "started", "created_at": "2026-07-15T11:00:00+00:00"})

    monkeypatch.setattr(storage, "sync_to_github", lambda: called.append("sync") or {"ok": True})

    storage.update_workflow_run("run-id", {"status": "failed", "completed_at": "2026-07-15T11:01:00+00:00"})

    assert called == ["sync"]