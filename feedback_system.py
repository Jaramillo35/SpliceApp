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


def _get_streamlit_secret(*keys: str) -> str | None:
    try:
        # Support both flat secrets and a nested [github] section.
        github_secrets = st.secrets.get("github", {})
        for key in keys:
            if key in st.secrets and st.secrets[key]:
                return str(st.secrets[key])
            if isinstance(github_secrets, dict) and key in github_secrets and github_secrets[key]:
                return str(github_secrets[key])
            lower_key = key.lower()
            if isinstance(github_secrets, dict) and lower_key in github_secrets and github_secrets[lower_key]:
                return str(github_secrets[lower_key])
    except Exception:
        return None
    return None


def _get_config_value(env_key: str, *, default: str | None = None, secret_keys: tuple[str, ...] = ()) -> str | None:
    value = os.getenv(env_key)
    if value:
        return value
    lookup_keys = (env_key, *secret_keys)
    secret_value = _get_streamlit_secret(*lookup_keys)
    if secret_value:
        return secret_value
    return default


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

    def submit_ticket_and_sync(
        self,
        *,
        reported_by: str,
        workflow: str,
        area: str,
        description: str,
        category: str = "feedback",
        severity: str = "medium",
    ) -> tuple[str, dict[str, Any]]:
        ticket_id = self.submit_ticket(
            reported_by=reported_by,
            workflow=workflow,
            area=area,
            description=description,
            category=category,
            severity=severity,
        )
        sync_result = self.sync_to_github()
        return ticket_id, sync_result

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
        repository = repository or _get_config_value(
            "GITHUB_REPOSITORY",
            secret_keys=("repository",),
        )
        token = token or _get_config_value(
            "GITHUB_TOKEN",
            secret_keys=("token",),
        )
        branch = branch or _get_config_value(
            "GITHUB_BRANCH",
            default="main",
            secret_keys=("branch",),
        )
        file_path = file_path or _get_config_value(
            "TICKETS_GITHUB_PATH",
            default="data/tickets.json",
            secret_keys=("path", "file_path"),
        )

        if not repository or not token:
            return {
                "ok": False,
                "message": "GitHub sync requires GITHUB_REPOSITORY and GITHUB_TOKEN (env vars or Streamlit secrets).",
            }

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


def get_feedback_area_options(*, workflow: str | None = None, area: str | None = None) -> list[str]:
    options = [
        "General",
        "Home",
        "Splice Generation",
        "DTx Compare Report",
        "Create SECR",
        "DTCR Matching Report",
        "VBOM Risk Matrix",
    ]
    for candidate in [workflow, area]:
        if candidate and candidate not in options:
            options.append(candidate)
    return options


def render_feedback_widget(
    *,
    workflow: str,
    area: str | None = None,
    store: FeedbackStore | None = None,
    key_prefix: str = "feedback",
) -> None:
    store = store or FeedbackStore()
    tickets = store.load_tickets()

    st.sidebar.markdown("### Report an issue or feedback")
    with st.sidebar.expander("Open ticket form", expanded=True):
        st.caption("Submit a structured ticket from anywhere in the app.")
        st.caption("Tickets are stored in the repo-backed data file and reviewed by the administrator.")
        st.text_input("Workflow", value=workflow, disabled=True, key=f"{key_prefix}_workflow")
        area_value = area or workflow
        area_options = get_feedback_area_options(workflow=workflow, area=area_value)
        default_index = area_options.index(area_value) if area_value in area_options else 0
        area_input = st.selectbox(
            "Area / part",
            options=area_options,
            index=default_index,
            key=f"{key_prefix}_area",
        )
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
                ticket_id, sync_result = store.submit_ticket_and_sync(
                    reported_by=reported_by,
                    workflow=workflow,
                    area=area_input,
                    description=description,
                    category=category,
                    severity=severity,
                )
                if sync_result.get("ok"):
                    st.success(f"Ticket submitted successfully. Reference: {ticket_id}")
                    st.caption("The ticket is saved locally and synced to GitHub.")
                else:
                    st.success(f"Ticket submitted successfully. Reference: {ticket_id}")
                    st.info(sync_result.get("message", "GitHub sync was not completed."))

        st.caption(f"Stored tickets: {len(tickets)}")
        if tickets:
            latest = tickets[-1]
            st.caption(f"Latest: {latest.get('ticket_id')} | {latest.get('workflow')} | {latest.get('area')}")
