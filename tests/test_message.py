"""Tests for format_commit_message placeholder substitution."""

import pytest

from gitstore.copy._types import CopyReport, FileEntry, format_commit_message


def _report(add=0, update=0, delete=0):
    """Build a CopyReport with the given number of files."""
    return CopyReport(
        add=[FileEntry(f"a{i}.txt", "B") for i in range(add)],
        update=[FileEntry(f"u{i}.txt", "B") for i in range(update)],
        delete=[FileEntry(f"d{i}.txt", "B") for i in range(delete)],
    )


class TestPlainMessage:
    """No placeholders — backward compatible."""

    def test_plain_message_returned_as_is(self):
        report = _report(add=2)
        assert format_commit_message(report, "Deploy v2") == "Deploy v2"

    def test_none_message_uses_auto(self):
        report = _report(add=1)
        assert format_commit_message(report) == "+ a0.txt"


class TestDefaultPlaceholder:
    def test_single_add(self):
        report = _report(add=1)
        msg = format_commit_message(report, "Deploy: {default}")
        assert msg == "Deploy: + a0.txt"

    def test_batch_with_operation(self):
        report = _report(add=3, update=1)
        msg = format_commit_message(report, "Release: {default}", operation="cp")
        assert msg == "Release: Batch cp: +3 ~1"

    def test_batch_without_operation(self):
        report = _report(add=2, delete=1)
        msg = format_commit_message(report, "{default}")
        assert msg == "Batch: +2 -1"

    def test_empty_report(self):
        report = _report()
        msg = format_commit_message(report, "Deploy: {default}")
        assert msg == "Deploy: No changes"


class TestCountPlaceholders:
    def test_add_update_delete(self):
        report = _report(add=3, update=1, delete=2)
        msg = format_commit_message(report, "+{add_count} ~{update_count} -{delete_count}")
        assert msg == "+3 ~1 -2"

    def test_total(self):
        report = _report(add=2, update=3)
        msg = format_commit_message(report, "Changed {total_count} files")
        assert msg == "Changed 5 files"

    def test_zero_counts(self):
        report = _report()
        msg = format_commit_message(report, "+{add_count} ~{update_count} -{delete_count} ={total_count}")
        assert msg == "+0 ~0 -0 =0"


class TestOpPlaceholder:
    def test_with_operation(self):
        report = _report(add=1)
        msg = format_commit_message(report, "op={op}", operation="cp")
        assert msg == "op=cp"

    def test_without_operation(self):
        report = _report(add=1)
        msg = format_commit_message(report, "op={op}")
        assert msg == "op="


class TestMixed:
    def test_all_placeholders(self):
        report = _report(add=3, update=1, delete=0)
        msg = format_commit_message(
            report,
            "Deploy: {default} ({total_count} files, {op})",
            operation="cp",
        )
        assert msg == "Deploy: Batch cp: +3 ~1 (4 files, cp)"


class TestUnknownPlaceholder:
    def test_unknown_raises_key_error(self):
        report = _report(add=1)
        with pytest.raises(KeyError):
            format_commit_message(report, "bad {foo}")
