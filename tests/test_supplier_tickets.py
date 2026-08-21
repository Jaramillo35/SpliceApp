"""Supplier-update tickets: diff, dedup by content, self-contained payload."""

from __future__ import annotations

import json

from feedback_system import FeedbackStore
from splice.hrncmp.supplier_tickets import (
    TICKET_CATEGORY,
    diff_supplier_maps,
    file_supplier_ticket,
    has_differences,
    list_supplier_tickets,
    supplier_map_hash,
)

SHIPPED = {'TE CONNECTIVITY': 'DZ', 'YAZAKI': 'YZ', 'MOLEX': 'CM'}


def _store(tmp_path):
    return FeedbackStore(storage_path=tmp_path / "tickets.json")


class TestDiff:
    def test_added_removed_changed(self):
        uploaded = {'TE CONNECTIVITY': 'DZ', 'YAZAKI': 'Y2', 'NEW CORP': 'NC'}
        diff = diff_supplier_maps(SHIPPED, uploaded)
        assert diff['added'] == {'NEW CORP': 'NC'}
        assert diff['removed'] == ['MOLEX']
        assert diff['changed'] == {'YAZAKI': {'old': 'YZ', 'new': 'Y2'}}

    def test_identical_lists_have_no_differences(self):
        assert not has_differences(diff_supplier_maps(SHIPPED, dict(SHIPPED)))

    def test_hash_ignores_order_and_case(self):
        a = {'te connectivity': 'DZ', 'YAZAKI': 'YZ'}
        b = {'YAZAKI': 'YZ', 'TE CONNECTIVITY': 'DZ'}
        assert supplier_map_hash(a) == supplier_map_hash(b)


class TestTicketFiling:
    def test_identical_upload_files_no_ticket(self, tmp_path):
        store = _store(tmp_path)
        tid, _, already = file_supplier_ticket("s.xlsx", dict(SHIPPED), SHIPPED, store=store)
        assert tid is None and not already
        assert list_supplier_tickets(store) == []

    def test_modified_upload_files_one_ticket(self, tmp_path):
        store = _store(tmp_path)
        uploaded = {**SHIPPED, 'NEW CORP': 'NC'}
        tid, diff, already = file_supplier_ticket("s.xlsx", uploaded, SHIPPED, store=store)
        assert tid and not already
        assert diff['added'] == {'NEW CORP': 'NC'}
        tickets = list_supplier_tickets(store)
        assert len(tickets) == 1
        assert tickets[0]['category'] == TICKET_CATEGORY

    def test_same_upload_twice_reuses_the_open_ticket(self, tmp_path):
        store = _store(tmp_path)
        uploaded = {**SHIPPED, 'NEW CORP': 'NC'}
        tid1, _, _ = file_supplier_ticket("s.xlsx", uploaded, SHIPPED, store=store)
        tid2, _, already = file_supplier_ticket("other-name.xlsx", uploaded, SHIPPED, store=store)
        assert tid2 == tid1 and already
        assert len(list_supplier_tickets(store)) == 1

    def test_applied_ticket_does_not_block_a_new_one(self, tmp_path):
        store = _store(tmp_path)
        uploaded = {**SHIPPED, 'NEW CORP': 'NC'}
        tid1, _, _ = file_supplier_ticket("s.xlsx", uploaded, SHIPPED, store=store)
        tickets = store.load_tickets()
        tickets[0]['status'] = 'applied'
        store.save_tickets(tickets)
        tid2, _, already = file_supplier_ticket("s.xlsx", uploaded, SHIPPED, store=store)
        assert tid2 != tid1 and not already

    def test_ticket_payload_is_self_contained(self, tmp_path):
        store = _store(tmp_path)
        uploaded = {**SHIPPED, 'NEW CORP': 'NC'}
        file_supplier_ticket("s.xlsx", uploaded, SHIPPED, store=store)
        desc = list_supplier_tickets(store)[0]['description']
        payload = json.loads(desc.split("```json\n", 1)[1].rsplit("\n```", 1)[0])
        # the full uploaded mapping is embedded — the shipped Excel can be
        # regenerated from the ticket alone
        assert payload['full_list'] == uploaded
        assert payload['added'] == {'NEW CORP': 'NC'}
        assert payload['kind'] == TICKET_CATEGORY
