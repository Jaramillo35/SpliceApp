from __future__ import annotations

import base64
import csv
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import parse, request, error

import streamlit as st


class FeedbackStore:
    def __init__(self, storage_path: str | os.PathLike[str] | None = None) -> None:
        if storage_path is None:
            storage_path = Path(__file__).resolve().parent / "data" / "tickets.json"
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.storage_path.exists():
            self.storage_path.write_text("[]", encoding="utf-8")

    def load_tickets(self) -> list[dict[str, Any]]:
        try:
            raw = self.storage_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []

        try:
            payload = json.loads(raw) or []
        except json.JSONDecodeError:
            return []

        if isinstance(payload, list):
            return payload
        return []

    def save_tickets(self, tickets: list[dict[str, Any]]) -> None:
        self.storage_path.write_text(json.dumps(tickets, indent=2, ensure_ascii=False), encoding="utf-8")

    def submit_ticket(
        self,
        *,
        reported_by: str,
        workflow: str,
        area: str,
        description: str,
        category: str = "feedback",
        severity: str = "medium",
    ) -> str:
        ticket_id = self._build_ticket_id()
        created_at = datetime.now(timezone.utc).isoformat()
        ticket = {
            "ticket_id": ticket_id,
            "created_at": created_at,
            "reported_by": reported_by.strip() or "Anonymous",
            "workflow": workflow.strip() or "Unknown workflow",
            "area": area.strip() or "General",
            "category": category.strip() or "feedback",
            "severity": severity.strip() or "medium",
            "description": description.strip(),
            "summary": description.strip()[:140],
            "status": "new",
        }
        tickets = self.load_tickets()
        tickets.append(ticket)
        self.save_tickets(tickets)
        return ticket_id

    def export_tickets(self, format: str = "json") -> bytes:
        tickets = self.load_tickets()
        fmt = format.lower()
        if fmt == "json":
            return json.dumps(tickets, indent=2, ensure_ascii=False).encode("utf-8")
        if fmt == "csv":
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=[
                "ticket_id",
                "created_at",
                "reported_by",
                "workflow",
                "area",
                "category",
                "severity",
                "status",
                "summary",
                "description",
            ])
            writer.writeheader()
            for ticket in tickets:
                writer.writerow(ticket)
            return buffer.getvalue().encode("utf-8")
        raise ValueError(f"Unsupported export format: {format}")

    def sync_to_github(
        self,
        *,
        repository: str | None = None,
        token: str | None = None,
        branch: str | None = None,
        file_path: str | None = None,
    ) -> dict[str, Any]:
        repository = repository or os.getenv("GITHUB_REPOSITORY")
        token = token or os.getenv("GITHUB_TOKEN")
        branch = branch or os.getenv("GITHUB_BRANCH", "main")
        file_path = file_path or os.getenv("TICKETS_GITHUB_PATH", "data/tickets.json")

        if not repository or not token:
            return {"ok": False, "message": "GitHub sync requires GITHUB_REPOSITORY and GITHUB_TOKEN to be configured."}

        payload = {
            "message": "Update Streamlit feedback tickets",
            "content": base64.b64encode(self.storage_path.read_bytes()).decode("utf-8"),
            "branch": branch,
        }

        encoded_path = parse.quote(file_path)
        url = f"https://api.github.com/repos/{repository}/contents/{encoded_path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        }

        try:
            existing_req = request.Request(url, headers=headers, method="GET")
            with request.urlopen(existing_req) as response:
                existing = json.loads(response.read().decode("utf-8"))
                payload["sha"] = existing.get("sha")
        except error.HTTPError as exc:
            if exc.code != 404:
                return {"ok": False, "message": f"GitHub lookup failed: {exc}"}

        put_req = request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="PUT")
        try:
            with request.urlopen(put_req) as response:
                response_body = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            return {"ok": False, "message": f"GitHub update failed: {exc}"}

        return {
            "ok": True,
            "message": f"Tickets synced to {repository}/{file_path}",
            "html_url": response_body.get("content", {}).get("html_url"),
        }

    def _build_ticket_id(self) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        existing_count = len(self.load_tickets()) + 1
        return f"TKT-{timestamp}-{existing_count:03d}"


def render_feedback_widget(
    *,
    workflow: str,
    area: str | None = None,
    store: FeedbackStore | None = None,
    key_prefix: str = "feedback",
) -> None:
    store = store or FeedbackStore()
    tickets = store.load_tickets()

    with st.sidebar.expander("Issue / Feedback Ticket", expanded=False):
        st.caption("Submit a structured ticket from anywhere in the app.")
        st.caption("Tickets are stored in the repo-backed data file and can be downloaded as JSON or CSV.")
        st.text_input("Workflow", value=workflow, disabled=True, key=f"{key_prefix}_workflow")
        area_value = area or workflow
        area_input = st.text_input("Area / part", value=area_value, key=f"{key_prefix}_area")
        category = st.selectbox("Type", ["feedback", "bug", "enhancement", "question"], key=f"{key_prefix}_category")
        severity = st.selectbox("Priority", ["low", "medium", "high", "critical"], key=f"{key_prefix}_severity")
        reported_by = st.text_input("Your name / email", key=f"{key_prefix}_reported_by")
        description = st.text_area(
            "Describe the issue or feedback",
            placeholder="What happened? Where did it occur? What should be improved?",
            height=140,
            key=f"{key_prefix}_description",
        )

        if st.button("Submit ticket", key=f"{key_prefix}_submit"):
            if not description.strip():
                st.warning("Please describe the issue or feedback before submitting.")
            else:
                ticket_id = store.submit_ticket(
                    reported_by=reported_by,
                    workflow=workflow,
                    area=area_input,
                    description=description,
                    category=category,
                    severity=severity,
                )
                st.success(f"Ticket submitted successfully. Reference: {ticket_id}")
                st.caption("The ticket is saved in the repo-backed store and can be downloaded or synced to GitHub.")

        st.download_button(
            label="Download tickets as JSON",
            data=store.export_tickets("json"),
            file_name="streamlit_feedback_tickets.json",
            mime="application/json",
            key=f"{key_prefix}_download_json",
        )
        st.download_button(
            label="Download tickets as CSV",
            data=store.export_tickets("csv"),
            file_name="streamlit_feedback_tickets.csv",
            mime="text/csv",
            key=f"{key_prefix}_download_csv",
        )

        if st.button("Sync tickets to GitHub", key=f"{key_prefix}_sync"):
            sync_result = store.sync_to_github()
            if sync_result.get("ok"):
                st.success(sync_result["message"])
            else:
                st.info(sync_result["message"])

        st.caption(f"Stored tickets: {len(tickets)}")
        if tickets:
            latest = tickets[-1]
            st.caption(f"Latest: {latest.get('ticket_id')} | {latest.get('workflow')} | {latest.get('area')}")
