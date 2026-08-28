"""Persisting the applicability workbench between sessions.

The mapping is a decision the SE made by hand and the ticks are a work list;
both are laborious to redo. What matters most here is that a re-exported
complexity file — new name, same def id — does not lose the mapping, and that
a corrupt or foreign store never blocks the workbench.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from splice.dtxcircuits import store
from splice.dtxcircuits.report import CleanupSelection


@pytest.fixture()
def path(tmp_path) -> Path:
    return tmp_path / "workbench.json"


class TestIdentity:
    def test_def_id_is_the_identity(self):
        assert store.harness_identity("70101", "IP") == "70101"

    def test_name_is_the_fallback_when_there_is_no_def_id(self):
        assert store.harness_identity("", "Body_Left") == "BODY_LEFT"

    def test_nothing_to_identify_is_empty(self):
        assert store.harness_identity("", "") == ""


class TestLoadSave:
    def test_missing_file_gives_an_empty_store(self, path):
        assert store.load(path) == store.empty()

    def test_round_trip(self, path):
        store.save({"mapping": {"IP": ["70101"]}, "cleanup": {}}, path)
        assert store.load(path)["mapping"] == {"IP": ["70101"]}

    def test_save_stamps_the_time_and_schema(self, path):
        store.save({"mapping": {}, "cleanup": {}}, path)
        data = json.loads(path.read_text())
        assert data["schema"] == store.SCHEMA and data["saved"]

    def test_a_corrupt_file_never_raises(self, path):
        path.write_text("{ this is not json")
        assert store.load(path) == store.empty()

    def test_a_foreign_schema_is_ignored_rather_than_misread(self, path):
        path.write_text(json.dumps({"schema": 999, "mapping": {"IP": ["x"]}}))
        assert store.load(path)["mapping"] == {}

    def test_save_is_atomic_leaving_no_temp_file(self, path):
        store.save({"mapping": {}, "cleanup": {}}, path)
        assert path.exists()
        assert not list(path.parent.glob("*.tmp"))


class TestMappingRoundTrip:
    IDENTITY = {"a.xlsm": "70101", "b.xlsm": "70103"}

    def test_stored_by_identity_not_filename(self):
        stored = store.remember_mapping({"IP": ["a.xlsm"]}, self.IDENTITY)
        assert stored == {"IP": ["70101"]}

    def test_survives_a_file_being_re_exported_under_a_new_name(self):
        stored = store.remember_mapping({"IP": ["a.xlsm"]}, self.IDENTITY)
        # tomorrow the same harness arrives as a differently-named file
        tomorrow = {"2.- Harness_Complexity_IP_02-02-2030.xlsm": "70101"}
        assert store.restore_mapping(stored, tomorrow) == {
            "IP": ["2.- Harness_Complexity_IP_02-02-2030.xlsm"]}

    def test_several_harnesses_per_family_survive(self):
        stored = store.remember_mapping(
            {"SEAT": ["a.xlsm", "b.xlsm"]}, self.IDENTITY)
        assert stored == {"SEAT": ["70101", "70103"]}
        assert store.restore_mapping(stored, self.IDENTITY)["SEAT"] == \
            ["a.xlsm", "b.xlsm"]

    def test_an_identity_with_no_file_this_session_is_dropped(self):
        # better an unconnected row than a wrong one
        restored = store.restore_mapping({"IP": ["70101", "99999"]},
                                         {"a.xlsm": "70101"})
        assert restored == {"IP": ["a.xlsm"]}

    def test_a_family_whose_files_are_all_absent_disappears(self):
        assert store.restore_mapping({"IP": ["99999"]}, {"a.xlsm": "70101"}) == {}

    def test_files_without_an_identity_are_not_stored(self):
        stored = store.remember_mapping({"IP": ["ghost.xlsm"]}, {"ghost.xlsm": ""})
        assert stored == {}


class TestCleanupRoundTrip:
    def _selection(self) -> CleanupSelection:
        return CleanupSelection(
            key="IP|IP|circuit|QK107", family="IP", harness="IP",
            kind="circuit", ident="QK107", verdict="never built",
            condition="(QA1&QA2)", note="No build of IP satisfies (QA1&QA2).")

    def test_round_trip_keeps_the_note(self):
        s = self._selection()
        restored = store.restore_cleanup(store.remember_cleanup({s.key: s}))
        assert restored[s.key].note == s.note
        assert restored[s.key].ident == "QK107"
        assert restored[s.key].verdict == "never built"

    def test_empty_selection_round_trips(self):
        assert store.restore_cleanup(store.remember_cleanup({})) == {}

    def test_malformed_entries_are_skipped_not_fatal(self):
        assert store.restore_cleanup({"k": "not a dict"}) == {}

    def test_a_partial_record_still_loads(self):
        restored = store.restore_cleanup({"k": {"ident": "QK1"}})
        assert restored["k"].ident == "QK1" and restored["k"].note == ""


class TestFullDocument:
    def test_a_saved_workbench_reloads_whole(self, path):
        s = CleanupSelection(key="k", family="IP", harness="IP", kind="gap",
                             ident="QZ9", note="untracked")
        store.save({"mapping": store.remember_mapping({"IP": ["a.xlsm"]},
                                                      {"a.xlsm": "70101"}),
                    "cleanup": store.remember_cleanup({"k": s})}, path)
        loaded = store.load(path)
        assert loaded["mapping"] == {"IP": ["70101"]}
        assert store.restore_cleanup(loaded["cleanup"])["k"].ident == "QZ9"
