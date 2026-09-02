"""The production-facing pieces: version identity, backups, logs.

None of this touches an engine. It is the layer between a finished commit and
a working tool on someone's desk, which for a long time did not exist.
"""

from __future__ import annotations

import logging
import os
import tarfile
from pathlib import Path

import pytest

from splice import version
from splice.common import backup
from splice.common import logging as splog


class TestVersion:
    def test_a_build_stamp_is_trusted_first(self, monkeypatch):
        monkeypatch.setenv("SPLICE_GIT_SHA", "abc1234def")
        monkeypatch.setenv("SPLICE_BUILD_DATE", "2026-09-02T10:00:00Z")
        monkeypatch.setenv("SPLICE_GIT_BRANCH", "main")
        info = version.read()
        assert info.source == version.FROM_BUILD
        assert info.short_sha == "abc1234"
        assert info.label == "0.1.0 (abc1234)"
        assert info.built == "2026-09-02T10:00:00Z"

    def test_unknown_stamp_is_not_treated_as_a_commit(self, monkeypatch):
        """A bare `docker build` leaves the ARG at "unknown". That must fall
        through to the next source, not be reported as a commit called
        'unknown'."""
        monkeypatch.setenv("SPLICE_GIT_SHA", "unknown")
        info = version.read()
        assert info.source != version.FROM_BUILD

    def test_the_working_tree_answers_in_a_checkout(self, monkeypatch):
        monkeypatch.delenv("SPLICE_GIT_SHA", raising=False)
        info = version.read()
        if (version._ROOT / ".git").exists():
            assert info.source == version.FROM_GIT
            assert len(info.sha) == 40
            assert info.branch
        else:
            assert info.source == version.FROM_PACKAGE

    def test_the_dict_form_carries_the_label(self, monkeypatch):
        monkeypatch.setenv("SPLICE_GIT_SHA", "abc1234def")
        data = version.read().as_dict()
        assert data["label"] == "0.1.0 (abc1234)"
        assert data["source"] == version.FROM_BUILD

    def test_the_route_serves_it(self):
        pytest.importorskip("nicegui")
        import nicegui_app.main  # noqa: F401
        from nicegui import app
        assert any(getattr(r, "path", "") == "/version" for r in app.routes)


class TestBackup:
    @pytest.fixture()
    def data_dir(self, tmp_path: Path) -> Path:
        root = tmp_path / "data"
        root.mkdir()
        (root / "secr_database.db").write_bytes(b"sqlite" * 100)
        (root / "tickets.json").write_text("[]")
        (root / "inline_health").mkdir()
        (root / "inline_health" / "baseline.json").write_text("{}")
        (root / "logs").mkdir()
        (root / "logs" / "splice.log").write_text("noise")
        (root / "secr_database.db-wal").write_bytes(b"x")
        return root

    def test_it_archives_the_data_and_not_the_noise(self, data_dir):
        made = backup.create(data_dir)
        assert made.path.exists()
        with tarfile.open(made.path) as tar:
            names = set(tar.getnames())
        assert "secr_database.db" in names
        assert "inline_health/baseline.json" in names
        assert not any(n.startswith("logs") for n in names)
        assert not any(n.endswith(".db-wal") for n in names)
        assert not any(n.startswith("backups") for n in names), \
            "a backup must never contain the backups folder"

    def test_it_lives_inside_the_data_directory(self, data_dir):
        """So it sits on the persistent volume and survives a rebuild."""
        made = backup.create(data_dir)
        assert made.path.parent == data_dir / backup.BACKUP_DIR_NAME

    def test_newest_first_and_pruned(self, data_dir):
        from datetime import datetime, timedelta
        base = datetime(2026, 9, 2, 12, 0, 0)
        for minute in range(4):
            backup.create(data_dir, keep=3, now=base + timedelta(minutes=minute))
        found = backup.list_backups(data_dir)
        assert len(found) == 3
        assert found == sorted(found, key=lambda b: b.created, reverse=True)
        assert found[0].created == base + timedelta(minutes=3), "the newest survives"
        assert all(b.created != base for b in found), "the oldest was pruned"

    def test_data_size_excludes_backups_and_logs(self, data_dir):
        before = backup.data_size(data_dir)
        backup.create(data_dir)
        assert backup.data_size(data_dir) == before

    def test_restore_replaces_the_data_and_keeps_what_it_displaced(self, data_dir):
        made = backup.create(data_dir)
        (data_dir / "secr_database.db").write_bytes(b"newer")
        (data_dir / "extra.json").write_text("added later")
        kept = backup.restore(made.path, data_dir)
        assert (data_dir / "secr_database.db").read_bytes() == b"sqlite" * 100
        assert not (data_dir / "extra.json").exists()
        # the displaced data is still there, so the restore can be undone
        assert (kept / "secr_database.db").read_bytes() == b"newer"
        assert (kept / "extra.json").exists()
        assert kept.parent == data_dir / backup.BACKUP_DIR_NAME

    def test_restore_leaves_existing_backups_alone(self, data_dir):
        first = backup.create(data_dir)
        backup.restore(first.path, data_dir)
        assert first.path.exists()

    def test_a_missing_archive_is_an_error_not_a_wipe(self, data_dir):
        with pytest.raises(FileNotFoundError):
            backup.restore(data_dir / "nope.tar.gz", data_dir)
        assert (data_dir / "secr_database.db").exists()

    def test_an_archive_that_escapes_the_directory_is_refused(self, data_dir, tmp_path):
        evil = tmp_path / "evil.tar.gz"
        payload = tmp_path / "payload"
        payload.write_text("owned")
        with tarfile.open(evil, "w:gz") as tar:
            tar.add(payload, arcname="../../escaped.txt")
        with pytest.raises(ValueError):
            backup.restore(evil, data_dir)
        assert (data_dir / "secr_database.db").exists(), "live data untouched"

    def test_human_size(self):
        assert backup.human_size(512) == "512 B"
        assert backup.human_size(2048) == "2.0 KB"
        assert backup.human_size(5 * 1024 * 1024) == "5.0 MB"


class TestLogging:
    def test_tail_reports_a_missing_file_plainly(self, tmp_path):
        assert splog.tail(tmp_path) == "No log file yet."

    def test_tail_returns_the_last_lines(self, tmp_path):
        path = splog.log_file(tmp_path)
        path.write_text("\n".join(f"line {i}" for i in range(500)))
        text = splog.tail(tmp_path, lines=3)
        assert text.splitlines() == ["line 497", "line 498", "line 499"]

    def test_configure_attaches_a_file_handler(self, tmp_path, monkeypatch):
        monkeypatch.setattr(splog, "_CONFIGURED", False)
        root = logging.getLogger()
        before = list(root.handlers)
        try:
            splog.configure(log_dir=tmp_path / "logs")
            logging.getLogger("splice.test").warning("hello from the engine")
            for h in root.handlers:
                h.flush()
            assert "hello from the engine" in splog.log_file(tmp_path / "logs").read_text()
        finally:
            for h in root.handlers:
                if h not in before:
                    root.removeHandler(h)
                    h.close()
            monkeypatch.setattr(splog, "_CONFIGURED", False)


class TestAdminPage:
    def test_changelog_sections_newest_first(self):
        pytest.importorskip("nicegui")
        from nicegui_app.pages import admin
        sections = admin.changelog_sections()
        assert sections, "CHANGELOG.md must ship with the app"
        assert sections[0][0].startswith("Unreleased")

    def test_probe_never_raises(self):
        pytest.importorskip("nicegui")
        from nicegui_app.pages import admin
        ok, detail = admin.probe("http://127.0.0.1:1/", timeout=0.2)
        assert ok is False and detail

    def test_uptime_text(self):
        pytest.importorskip("nicegui")
        from nicegui_app.pages import admin
        assert admin.uptime_text(90) == "1m"
        assert admin.uptime_text(3700) == "1h 1m"
        assert admin.uptime_text(90000) == "1d 1h"
