"""Persisting the VBOM review-gate resolutions between sessions.

A resolution is a judgement the SE made by hand; the store keys it by the
programme tag and the engine's own case identity (VIN | HarnessFamily), so a
regenerated bundle finds its decisions again, and a second engineer's save
is refused rather than overwritten.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from splice.vbom import review_store as store


@pytest.fixture()
def path(tmp_path) -> Path:
    return tmp_path / "review.json"


class TestIdentity:
    def test_the_key_is_programme_tag_plus_review_id(self):
        assert store.case_key("2030", "QX", "QX30000001|IP") == "30_QX|QX30000001|IP"

    def test_a_two_digit_model_year_is_the_same_tag(self):
        assert store.case_key("30", "QX", "V|IP") == store.case_key("2030", "QX", "V|IP")

    def test_programmes_do_not_collide(self):
        assert store.case_key("30", "QX", "V|IP") != store.case_key("30", "RU", "V|IP")


class TestLoadSave:
    def test_missing_file_gives_an_empty_store(self, path):
        assert store.load(path) == store.empty()

    def test_round_trip(self, path):
        res = store.remember({}, "30", "QX", "V1|IP", "99000001AA", "note", by="M.J.")
        store.save({"resolutions": res}, path, by="M.J.")
        loaded = store.load(path)
        assert loaded["resolutions"]["30_QX|V1|IP"]["pn"] == "99000001AA"
        assert loaded["resolutions"]["30_QX|V1|IP"]["note"] == "note"
        assert loaded["resolutions"]["30_QX|V1|IP"]["by"] == "M.J."
        assert loaded["saved_by"] == "M.J."

    def test_save_stamps_the_time_and_schema(self, path):
        store.save({"resolutions": {}}, path)
        data = json.loads(path.read_text())
        assert data["schema"] == store.SCHEMA and data["saved"]

    def test_every_save_bumps_the_revision(self, path):
        store.save({"resolutions": {}}, path)
        assert store.load(path)["revision"] == 1
        store.save({"resolutions": {}}, path)
        assert store.load(path)["revision"] == 2
        assert store.envelope(store.load(path))["revision"] == 2

    def test_a_stale_save_is_refused_and_says_who_moved_it(self, path):
        store.save({"resolutions": {}}, path, by="A")
        mine = store.load(path)["revision"]
        store.save({"resolutions": {}}, path, by="B")      # someone else saved
        with pytest.raises(store.StaleWrite) as info:
            store.save({"resolutions": {}}, path, by="A", expected_revision=mine)
        assert info.value.by == "B"
        assert info.value.revision == mine + 1
        assert store.load(path)["saved_by"] == "B"

    def test_the_expected_revision_lets_a_current_save_through(self, path):
        store.save({"resolutions": {}}, path)
        rev = store.load(path)["revision"]
        store.save({"resolutions": {}}, path, expected_revision=rev)
        assert store.load(path)["revision"] == rev + 1

    def test_a_corrupt_file_never_raises(self, path):
        path.write_text("{ this is not json")
        assert store.load(path) == store.empty()

    def test_a_foreign_schema_is_ignored_rather_than_misread(self, path):
        path.write_text(json.dumps({"schema": 999, "resolutions": {"k": {"pn": "x"}}}))
        assert store.load(path)["resolutions"] == {}

    def test_save_is_atomic_leaving_no_temp_file(self, path):
        store.save({"resolutions": {}}, path)
        assert path.exists()
        assert not list(path.parent.glob("*.tmp"))


class TestRestore:
    def _stored(self) -> dict:
        res = store.remember({}, "30", "QX", "V1|IP", "99000001AA", "first")
        res = store.remember(res, "30", "QX", "V2|IP", "N/A", "second")
        res = store.remember(res, "30", "RU", "V1|IP", "77000001AA", "other programme")
        return res

    def test_only_this_runs_cases_come_back(self):
        got = store.restore(self._stored(), "30", "QX", ["V1|IP", "V9|BODY"])
        assert set(got) == {"V1|IP"}
        assert got["V1|IP"]["pn"] == "99000001AA" and got["V1|IP"]["note"] == "first"

    def test_another_programme_is_not_surfaced(self):
        got = store.restore(self._stored(), "30", "RU", ["V1|IP"])
        assert got["V1|IP"]["pn"] == "77000001AA"

    def test_a_pn_the_case_no_longer_offers_is_dropped(self):
        got = store.restore(self._stored(), "30", "QX", ["V1|IP", "V2|IP"],
                            allowed={"V1|IP": ["99000009AA", "N/A"],
                                     "V2|IP": ["99000001AA", "N/A"]})
        assert set(got) == {"V2|IP"}

    def test_forget_reopens_only_that_case(self):
        res = store.forget(self._stored(), "30", "QX", "V1|IP")
        assert "30_QX|V1|IP" not in res and "30_QX|V2|IP" in res

    def test_malformed_entries_are_skipped_not_fatal(self):
        assert store.restore({"30_QX|V1|IP": "not a dict"}, "30", "QX", ["V1|IP"]) == {}
