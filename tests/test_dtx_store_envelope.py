"""Every save names its author and bumps a revision; a stale write is refused."""

from __future__ import annotations

import pytest

from splice.dtxcircuits import store


def test_save_records_author_and_revision(tmp_path):
    path = tmp_path / "workbench.json"
    assert store.load(path)["revision"] == 0
    store.save({"mapping": {"IP": ["70101"]}}, path, by="MJ")
    data = store.load(path)
    assert data["saved_by"] == "MJ"
    assert data["revision"] == 1
    assert data["saved"]
    env = store.envelope(data)
    assert env == {"by": "MJ", "at": data["saved"], "revision": 1}


def test_a_stale_write_is_refused_and_says_who_moved_it(tmp_path):
    path = tmp_path / "workbench.json"
    store.save({"mapping": {}}, path, by="MJ")          # revision 1
    store.save({"mapping": {}}, path, by="KL")          # revision 2, someone else
    with pytest.raises(store.StaleWrite) as caught:
        store.save({"mapping": {}}, path, by="MJ", expected_revision=1)
    assert caught.value.by == "KL"
    assert caught.value.revision == 2
    assert store.load(path)["saved_by"] == "KL", "the refused write changed nothing"


def test_matching_revision_writes(tmp_path):
    path = tmp_path / "workbench.json"
    store.save({"mapping": {}}, path, by="MJ")
    store.save({"mapping": {"IP": ["x"]}}, path, by="MJ", expected_revision=1)
    assert store.load(path)["revision"] == 2
