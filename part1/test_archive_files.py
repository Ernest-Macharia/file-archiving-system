"""
test_archive_files.py
=====================
Automated tests for archive_files.py

Run inside the testenv container:
    pip install pytest
    pytest test_archive_files.py -v
"""

import grp
import os
import sys
import logging
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import archive_files as af

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dirs(tmp_path):
    home_root   = tmp_path / "home"
    archive_root = tmp_path / "archive"
    home_root.mkdir()
    archive_root.mkdir()
    return home_root, archive_root


@pytest.fixture
def mock_conn():
    """Return a mock psycopg2 connection that records write_event calls."""
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=MagicMock())
    conn.cursor.return_value.__exit__  = MagicMock(return_value=False)
    return conn


@pytest.fixture
def logger():
    log = logging.getLogger("test")
    log.addHandler(logging.NullHandler())
    return log


# ---------------------------------------------------------------------------
# resolve_group
# ---------------------------------------------------------------------------

class TestResolveGroup:
    def test_existing_group_returns_entry(self):
        # 'root' group exists on any Linux system
        result = af.resolve_group("root")
        assert result is not None
        assert result.gr_name == "root"

    def test_missing_group_returns_none(self):
        result = af.resolve_group("definitely_nonexistent_group_xyz")
        assert result is None


# ---------------------------------------------------------------------------
# resolve_home
# ---------------------------------------------------------------------------

class TestResolveHome:
    def test_existing_user(self):
        # 'root' always has a home
        result = af.resolve_home("root")
        assert result is not None
        assert isinstance(result, Path)

    def test_missing_user_returns_none(self):
        result = af.resolve_home("no_such_user_xyz_123")
        assert result is None


# ---------------------------------------------------------------------------
# archive_user_files
# ---------------------------------------------------------------------------

class TestArchiveUserFiles:

    def _seed(self, home_root: Path, username: str, files: list[str]) -> Path:
        home = home_root / username
        home.mkdir(parents=True)
        for rel in files:
            f = home / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(f"content of {rel}")
        return home

    def test_files_moved(self, tmp_dirs, mock_conn):
        home_root, archive_root = tmp_dirs
        home = self._seed(home_root, "alice", ["docs/report.txt", "downloads/setup.sh"])

        m, s, e = af.archive_user_files(
            mock_conn, run_id=1, username="alice",
            home_dir=home, archive_root=archive_root,
            timestamp="20240101_120000", dry_run=False,
        )
        assert m == 2
        assert e == 0
        assert (archive_root / "alice" / "20240101_120000" / "docs" / "report.txt").exists()
        assert (archive_root / "alice" / "20240101_120000" / "downloads" / "setup.sh").exists()
        # original files should be gone
        assert not (home / "docs" / "report.txt").exists()

    def test_missing_home_counted_as_skipped(self, tmp_dirs, mock_conn):
        home_root, archive_root = tmp_dirs
        m, s, e = af.archive_user_files(
            mock_conn, run_id=1, username="ghost",
            home_dir=home_root / "ghost",
            archive_root=archive_root,
            timestamp="20240101_120000", dry_run=False,
        )
        assert m == 0
        assert s == 1
        assert e == 0

    def test_empty_home_counted_as_skipped(self, tmp_dirs, mock_conn):
        home_root, archive_root = tmp_dirs
        (home_root / "emptyuser").mkdir()
        m, s, e = af.archive_user_files(
            mock_conn, run_id=1, username="emptyuser",
            home_dir=home_root / "emptyuser",
            archive_root=archive_root,
            timestamp="20240101_120000", dry_run=False,
        )
        assert m == 0
        assert s == 1
        assert e == 0

    def test_dry_run_does_not_move(self, tmp_dirs, mock_conn):
        home_root, archive_root = tmp_dirs
        home = self._seed(home_root, "bob", ["notes.txt"])

        m, s, e = af.archive_user_files(
            mock_conn, run_id=1, username="bob",
            home_dir=home, archive_root=archive_root,
            timestamp="20240101_120000", dry_run=True,
        )
        assert m == 1           # counted as "would move"
        assert (home / "notes.txt").exists()          # original still there
        assert not (archive_root / "bob").exists()    # nothing written

    def test_already_archived_files_skipped(self, tmp_dirs, mock_conn):
        home_root, archive_root = tmp_dirs
        home = self._seed(home_root, "carol", ["script.sh"])

        # First run
        af.archive_user_files(
            mock_conn, run_id=1, username="carol",
            home_dir=home, archive_root=archive_root,
            timestamp="20240101_120000", dry_run=False,
        )

        # Recreate the file so home is non-empty
        home.mkdir(parents=True, exist_ok=True)
        (home / "script.sh").write_text("recreated")

        # Second run with same timestamp to force "already exists"
        m, s, e = af.archive_user_files(
            mock_conn, run_id=2, username="carol",
            home_dir=home, archive_root=archive_root,
            timestamp="20240101_120000", dry_run=False,
        )
        assert s >= 1    # the file already at destination is skipped

    def test_second_run_different_timestamp_succeeds(self, tmp_dirs, mock_conn):
        home_root, archive_root = tmp_dirs
        home = self._seed(home_root, "dave", ["data.csv"])

        af.archive_user_files(
            mock_conn, run_id=1, username="dave",
            home_dir=home, archive_root=archive_root,
            timestamp="20240101_120000", dry_run=False,
        )

        # Re-seed
        home.mkdir(parents=True, exist_ok=True)
        (home / "data2.csv").write_text("new data")

        m, s, e = af.archive_user_files(
            mock_conn, run_id=2, username="dave",
            home_dir=home, archive_root=archive_root,
            timestamp="20240101_130000", dry_run=False,   # different timestamp
        )
        assert m == 1
        assert (archive_root / "dave" / "20240101_120000" / "data.csv").exists()
        assert (archive_root / "dave" / "20240101_130000" / "data2.csv").exists()

    def test_permission_error_counted_as_error(self, tmp_dirs, mock_conn):
        home_root, archive_root = tmp_dirs
        home = self._seed(home_root, "frank", ["locked.txt"])

        with patch("shutil.move", side_effect=PermissionError("access denied")):
            m, s, e = af.archive_user_files(
                mock_conn, run_id=1, username="frank",
                home_dir=home, archive_root=archive_root,
                timestamp="20240101_120000", dry_run=False,
            )
        assert e == 1
        assert m == 0

    def test_events_written_per_file(self, tmp_dirs, mock_conn):
        """write_event must be called once per file — not in a batch at the end."""
        home_root, archive_root = tmp_dirs
        self._seed(home_root, "grace", ["a.txt", "b.txt", "c.txt"])

        call_count_before = mock_conn.commit.call_count
        af.archive_user_files(
            mock_conn, run_id=1, username="grace",
            home_dir=home_root / "grace",
            archive_root=archive_root,
            timestamp="20240101_120000", dry_run=False,
        )
        # commit is called once per write_event call — should be ≥ 3
        commits_during = mock_conn.commit.call_count - call_count_before
        assert commits_during >= 3


# ---------------------------------------------------------------------------
# Database helpers (mocked)
# ---------------------------------------------------------------------------

class TestDbHelpers:

    def test_write_event_executes_insert(self, mock_conn):
        af.write_event(mock_conn, run_id=1, username="alice",
                       source="/home/alice/file.txt",
                       destination="/archive/alice/file.txt",
                       status="moved", reason=None)
        mock_conn.cursor.assert_called()
        mock_conn.commit.assert_called()

    def test_finish_run_updates_record(self, mock_conn):
        af.finish_run(mock_conn, run_id=1,
                      moved=10, skipped=2, errors=0,
                      duration=1.234, status="completed")
        mock_conn.commit.assert_called()


# ---------------------------------------------------------------------------
# Integration-style: happy path end-to-end (no real DB, no real groups)
# ---------------------------------------------------------------------------

class TestEndToEnd:

    def _make_group(self, name, members):
        g = MagicMock()
        g.gr_name  = name
        g.gr_gid   = 2001
        g.gr_mem   = members
        return g

    def test_group_not_found_exits_1(self):
        with patch("archive_files.resolve_group", return_value=None):
            with patch("sys.argv", ["archive_files.py", "--group", "phantom"]):
                result = af.main()
        assert result == 1

    def test_empty_group_exits_0(self):
        grp_mock = self._make_group("empty_grp", [])
        with patch("archive_files.resolve_group", return_value=grp_mock), \
             patch("archive_files.get_db_conn", return_value=MagicMock()), \
             patch("archive_files.ensure_schema"), \
             patch("archive_files.create_run", return_value=99), \
             patch("archive_files.finish_run"), \
             patch("sys.argv", ["archive_files.py", "--group", "empty_grp"]):
            result = af.main()
        assert result == 0

    def test_db_connection_failure_exits_1(self):
        import psycopg2
        grp_mock = self._make_group("developers", ["alice"])
        with patch("archive_files.resolve_group", return_value=grp_mock), \
             patch("archive_files.get_db_conn",
                   side_effect=psycopg2.OperationalError("no DB")), \
             patch("sys.argv", ["archive_files.py", "--group", "developers"]):
            result = af.main()
        assert result == 1
