"""Supplier-list update tickets for the HRN Chart Builder.

When a user uploads a modified supplier list, their HRN generation uses it
immediately — but the shipped ``assets/DEF Supplier Codes.xlsx`` is unchanged,
so the next session would silently fall back to the old list. To close that
loop, every upload that differs from the shipped list files a ticket in the
app's existing FeedbackStore (category ``supplier-update``).

The ticket is self-contained: it embeds the diff *and* the complete uploaded
mapping as JSON, so the administrator can regenerate the shipped Excel from
the ticket alone — no need to chase the original file. Retrieval channels are
the ones the feedback system already has: the tickets.json store, its JSON/CSV
export, the optional GitHub sync, plus a per-ticket JSON download on the HRN
page itself.

Admin workflow: take the ticket JSON, hand it to Claude ("apply supplier
ticket ..."), which updates assets/DEF Supplier Codes.xlsx from the embedded
``full_list`` and marks the ticket applied.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional, Tuple

TICKET_CATEGORY = "supplier-update"


def supplier_map_hash(supplier_map: Dict[str, str]) -> str:
    """Stable hash of a mapping, independent of file format or row order."""
    canonical = json.dumps(
        {str(k).strip().upper(): str(v).strip() for k, v in supplier_map.items()},
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def diff_supplier_maps(shipped: Dict[str, str], uploaded: Dict[str, str]) -> Dict[str, Any]:
    """What the uploaded list changes relative to the shipped one."""
    shipped_norm = {str(k).strip().upper(): str(v).strip() for k, v in shipped.items()}
    uploaded_norm = {str(k).strip().upper(): str(v).strip() for k, v in uploaded.items()}
    added = {k: v for k, v in uploaded_norm.items() if k not in shipped_norm}
    removed = sorted(k for k in shipped_norm if k not in uploaded_norm)
    changed = {
        k: {"old": shipped_norm[k], "new": v}
        for k, v in uploaded_norm.items()
        if k in shipped_norm and shipped_norm[k] != v
    }
    return {"added": added, "removed": removed, "changed": changed}


def has_differences(diff: Dict[str, Any]) -> bool:
    return bool(diff["added"] or diff["removed"] or diff["changed"])


def build_ticket_payload(filename: str, uploaded: Dict[str, str],
                         diff: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "kind": TICKET_CATEGORY,
        "hash": supplier_map_hash(uploaded),
        "source_filename": filename,
        "added": diff["added"],
        "removed": diff["removed"],
        "changed": diff["changed"],
        "full_list": uploaded,
    }


def _ticket_description(payload: Dict[str, Any]) -> str:
    lines = [
        "Supplier list update requested from the HRN Chart Builder.",
        f"Uploaded file: {payload['source_filename']}",
        f"Content hash: {payload['hash']}",
        f"Added: {len(payload['added'])} | Removed: {len(payload['removed'])} "
        f"| Changed: {len(payload['changed'])}",
        "",
        "Admin: hand the JSON below to Claude to update the shipped "
        "DEF Supplier Codes.xlsx (it regenerates the file from full_list).",
        "",
        "```json",
        json.dumps(payload, indent=2, sort_keys=True),
        "```",
    ]
    return "\n".join(lines)


def find_existing_ticket(store, content_hash: str) -> Optional[Dict[str, Any]]:
    """A supplier-update ticket already filed for this exact list, if any."""
    for ticket in store.load_tickets():
        if (ticket.get("category") == TICKET_CATEGORY
                and f'"hash": "{content_hash}"' in ticket.get("description", "")
                and ticket.get("status") != "applied"):
            return ticket
    return None


def file_supplier_ticket(filename: str, uploaded: Dict[str, str],
                         shipped: Dict[str, str],
                         store=None, reported_by: str = "HRN Chart Builder",
                         ) -> Tuple[Optional[str], Dict[str, Any], bool]:
    """File a ticket for a modified supplier list (deduplicated by content).

    Returns (ticket_id, diff, already_filed). ticket_id is None when the
    uploaded list matches the shipped one (no ticket needed); already_filed is
    True when an open ticket for this exact list exists, whose id is returned.
    """
    diff = diff_supplier_maps(shipped, uploaded)
    if not has_differences(diff):
        return None, diff, False

    if store is None:
        from feedback_system import FeedbackStore
        store = FeedbackStore()

    payload = build_ticket_payload(filename, uploaded, diff)
    existing = find_existing_ticket(store, payload["hash"])
    if existing is not None:
        return existing.get("ticket_id"), diff, True

    ticket_id = store.submit_ticket(
        reported_by=reported_by,
        workflow="HRN Chart Builder",
        area="Supplier list",
        description=_ticket_description(payload),
        category=TICKET_CATEGORY,
        severity="medium",
    )
    return ticket_id, diff, False


def list_supplier_tickets(store=None) -> list:
    if store is None:
        from feedback_system import FeedbackStore
        store = FeedbackStore()
    return [t for t in store.load_tickets() if t.get("category") == TICKET_CATEGORY]
