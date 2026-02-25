"""Tests for the watch module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import click
import pytest

from vost.cli._watch import (
    _format_summary,
    _run_sync_cycle,
    watch_and_sync,
)
from vost.copy._types import ChangeReport, FileEntry
from vost.exceptions import StaleSnapshotError


# ---------------------------------------------------------------------------
# _format_summary
# ---------------------------------------------------------------------------

class TestFormatSummary:
    def test_empty_report(self):
        changes = ChangeReport()
        assert _format_summary(changes) == "no changes"

    def test_adds_only(self):
        changes = ChangeReport(add=[FileEntry("a.txt", "B"), FileEntry("b.txt", "B")])
        assert _format_summary(changes) == "+2"

    def test_updates_only(self):
        changes = ChangeReport(update=[FileEntry("a.txt", "B")])
        assert _format_summary(changes) == "~1"

    def test_deletes_only(self):
        changes = ChangeReport(delete=[FileEntry("a.txt", "B"), FileEntry("b.txt", "B"), FileEntry("c.txt", "B")])
        assert _format_summary(changes) == "-3"

    def test_mixed(self):
        changes = ChangeReport(
            add=[FileEntry("a.txt", "B")],
            update=[FileEntry("b.txt", "B"), FileEntry("c.txt", "B")],
            delete=[FileEntry("d.txt", "B")],
        )
        assert _format_summary(changes) == "+1 ~2 -1"


# ---------------------------------------------------------------------------
# watch_and_sync
# ---------------------------------------------------------------------------

def _make_store_and_fs(changes=None):
    """Create mock store + branches dict returning a mock FS."""
    fs = MagicMock()
    new_fs = MagicMock()
    new_fs.changes = changes
    new_fs.commit_hash = "abc1234def"

    store = MagicMock()
    store.branches = {"main": fs}
    return store, fs, new_fs


class TestInitialSync:
    def test_initial_sync_runs(self):
        """Initial sync runs before the watch loop starts."""
        store, fs, new_fs = _make_store_and_fs(changes=None)

        def fake_watch(path, debounce):
            raise KeyboardInterrupt

        mock_wf = MagicMock()
        mock_wf.watch = fake_watch

        with patch("vost.cli._watch.watchfiles", mock_wf):
            with patch("vost.cli._watch._run_sync_cycle") as mock_cycle:
                watch_and_sync(store, "main", "/tmp/test", "",
                               debounce=2000, message=None,
                               ignore_errors=False, checksum=False)

                # Initial sync should have been called once
                assert mock_cycle.call_count == 1


class TestWatchOneCycle:
    def test_watch_one_cycle(self):
        """Watch yields one changeset, then KeyboardInterrupt -> 2 sync calls."""
        store, fs, new_fs = _make_store_and_fs(changes=None)

        call_count = 0

        def fake_watch(path, debounce):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield {("changed", "/tmp/test/a.txt")}
            raise KeyboardInterrupt

        mock_wf = MagicMock()
        mock_wf.watch = fake_watch

        with patch("vost.cli._watch.watchfiles", mock_wf):
            with patch("vost.cli._watch._run_sync_cycle") as mock_cycle:
                watch_and_sync(store, "main", "/tmp/test", "",
                               debounce=2000, message=None,
                               ignore_errors=False, checksum=False)

                # Initial sync + 1 cycle = 2 calls
                assert mock_cycle.call_count == 2


class TestCycleErrorHandling:
    def test_stale_snapshot_continues(self):
        """StaleSnapshotError in a cycle doesn't stop the loop."""
        store, fs, new_fs = _make_store_and_fs(changes=None)

        cycle_calls = []

        def fake_watch(path, debounce):
            yield {("changed", "/tmp/test/a.txt")}
            yield {("changed", "/tmp/test/b.txt")}
            raise KeyboardInterrupt

        def fake_cycle(*args, **kwargs):
            cycle_calls.append(1)
            if len(cycle_calls) <= 2:
                # First two calls (initial + first change) raise StaleSnapshotError
                raise StaleSnapshotError("stale")

        mock_wf = MagicMock()
        mock_wf.watch = fake_watch

        with patch("vost.cli._watch.watchfiles", mock_wf):
            with patch("vost.cli._watch._run_sync_cycle", side_effect=fake_cycle):
                watch_and_sync(store, "main", "/tmp/test", "",
                               debounce=2000, message=None,
                               ignore_errors=False, checksum=False)

                # initial + 2 changes = 3 calls total, all survived
                assert len(cycle_calls) == 3

    def test_generic_exception_continues(self):
        """A generic exception in a cycle doesn't stop the loop."""
        store, fs, new_fs = _make_store_and_fs(changes=None)

        cycle_calls = []

        def fake_watch(path, debounce):
            yield {("changed", "/tmp/test/a.txt")}
            yield {("changed", "/tmp/test/b.txt")}
            raise KeyboardInterrupt

        def fake_cycle(*args, **kwargs):
            cycle_calls.append(1)
            if len(cycle_calls) == 2:
                raise FileNotFoundError("no such file")

        mock_wf = MagicMock()
        mock_wf.watch = fake_watch

        with patch("vost.cli._watch.watchfiles", mock_wf):
            with patch("vost.cli._watch._run_sync_cycle", side_effect=fake_cycle):
                watch_and_sync(store, "main", "/tmp/test", "",
                               debounce=2000, message=None,
                               ignore_errors=False, checksum=False)

                # initial + 2 changes = 3 calls total
                assert len(cycle_calls) == 3


# ---------------------------------------------------------------------------
# _run_sync_cycle
# ---------------------------------------------------------------------------

class TestRunSyncCycle:
    def test_prints_summary(self, capsys):
        """_run_sync_cycle prints a summary line on changes."""
        changes = ChangeReport(
            add=[FileEntry("a.txt", "B")],
            update=[FileEntry("b.txt", "B")],
        )
        new_fs = MagicMock()
        new_fs.changes = changes
        new_fs.commit_hash = "abc1234"

        store = MagicMock()
        store.branches = {"main": MagicMock()}

        fs = store.branches["main"]
        fs.sync_in.return_value = new_fs

        _run_sync_cycle(store, "main", "/tmp/test", "",
                        message=None, ignore_errors=False, checksum=False)

        captured = capsys.readouterr()
        assert "+1 ~1" in captured.out
        assert "abc1234" in captured.out

    def test_no_changes(self, capsys):
        """_run_sync_cycle prints 'no changes' when changes is None."""
        new_fs = MagicMock()
        new_fs.changes = None
        new_fs.commit_hash = "abc1234"

        store = MagicMock()
        store.branches = {"main": MagicMock()}
        fs = store.branches["main"]
        fs.sync_in.return_value = new_fs

        _run_sync_cycle(store, "main", "/tmp/test", "",
                        message=None, ignore_errors=False, checksum=False)

        captured = capsys.readouterr()
        assert "no changes" in captured.out
