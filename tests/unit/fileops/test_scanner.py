# Copyright (c) 2026 My Senior Intern contributors

"""Bounded local document-discovery tests."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from senior_intern.fileops.discovery import (
    EntryKind,
    FileSystemEntry,
    ScanIssueCode,
    ScanRequest,
)
from senior_intern.fileops.scanner import scan_documents


class FakeDirectoryReader:
    """Deterministic no-follow directory reader."""

    tree: dict[Path, tuple[FileSystemEntry, ...]]
    failures: set[Path]
    calls: list[Path]

    def __init__(
        self,
        tree: dict[Path, tuple[FileSystemEntry, ...]],
        *,
        failures: set[Path] | None = None,
    ) -> None:
        self.tree = tree
        self.failures = set() if failures is None else failures
        self.calls = []

    def entries(self, path: Path) -> tuple[FileSystemEntry, ...]:
        """Return configured entries and record every traversal."""
        self.calls.append(path)
        if path in self.failures:
            raise PermissionError(path)
        return self.tree.get(path, ())


def test_real_scan_is_supported_deterministic_excluded_and_depth_bounded(
    tmp_path: Path,
) -> None:
    """A real scan returns only supported files in stable order."""
    nested = tmp_path / "nested"
    deeper = nested / "deeper"
    ignored = tmp_path / "ignore"
    nested.mkdir()
    deeper.mkdir()
    ignored.mkdir()
    _ = (tmp_path / "A.PDF").write_bytes(b"a")
    _ = (tmp_path / "b.docx").write_bytes(b"bb")
    _ = (tmp_path / "notes.txt").write_text("ignored", encoding="utf-8")
    _ = (nested / "c.xlsx").write_bytes(b"ccc")
    _ = (deeper / "d.pptx").write_bytes(b"dddd")
    _ = (ignored / "e.csv").write_bytes(b"eeeee")

    result = scan_documents(
        ScanRequest(
            root=tmp_path,
            excluded_names=("ignore",),
            max_depth=1,
        )
    )

    assert [item.relative_path.as_posix() for item in result.documents] == [
        "A.PDF",
        "b.docx",
        "nested/c.xlsx",
    ]
    assert not result.truncated


def test_links_and_inaccessible_directories_are_never_followed(tmp_path: Path) -> None:
    """A link is reported, and an unreadable directory does not broaden traversal."""
    linked = tmp_path / "linked"
    blocked = tmp_path / "blocked"
    safe = tmp_path / "safe"
    reader = FakeDirectoryReader(
        {
            tmp_path: (
                FileSystemEntry(name="linked", path=linked, kind=EntryKind.LINK),
                FileSystemEntry(name="blocked", path=blocked, kind=EntryKind.DIRECTORY),
                FileSystemEntry(name="safe", path=safe, kind=EntryKind.DIRECTORY),
            ),
            safe: (
                FileSystemEntry(
                    name="ok.csv",
                    path=safe / "ok.csv",
                    kind=EntryKind.FILE,
                    size=2,
                    modified_ns=1,
                ),
            ),
        },
        failures={blocked},
    )

    result = scan_documents(ScanRequest(root=tmp_path), reader=reader)

    assert [item.relative_path.as_posix() for item in result.documents] == ["safe/ok.csv"]
    assert {(issue.relative_path.as_posix(), issue.code) for issue in result.issues} == {
        ("blocked", ScanIssueCode.INACCESSIBLE),
        ("linked", ScanIssueCode.LINK_SKIPPED),
    }
    assert linked not in reader.calls


def test_reader_cannot_return_a_document_outside_the_selected_root(tmp_path: Path) -> None:
    """Even a compromised reader cannot broaden the enrolled root."""
    outside = tmp_path.parent / "outside.pdf"
    reader = FakeDirectoryReader(
        {
            tmp_path: (
                FileSystemEntry(
                    name="outside.pdf",
                    path=outside,
                    kind=EntryKind.FILE,
                    size=2,
                    modified_ns=1,
                ),
            )
        }
    )

    result = scan_documents(ScanRequest(root=tmp_path), reader=reader)

    assert result.documents == ()
    assert [(issue.relative_path.as_posix(), issue.code) for issue in result.issues] == [
        (".", ScanIssueCode.OUTSIDE_ROOT)
    ]


def test_size_document_and_entry_limits_fail_closed(tmp_path: Path) -> None:
    """Limits stop discovery deterministically and never return oversized files."""
    reader = FakeDirectoryReader(
        {
            tmp_path: (
                FileSystemEntry(
                    name="a.pdf",
                    path=tmp_path / "a.pdf",
                    kind=EntryKind.FILE,
                    size=11,
                    modified_ns=1,
                ),
                FileSystemEntry(
                    name="b.pdf",
                    path=tmp_path / "b.pdf",
                    kind=EntryKind.FILE,
                    size=2,
                    modified_ns=2,
                ),
                FileSystemEntry(
                    name="c.pdf",
                    path=tmp_path / "c.pdf",
                    kind=EntryKind.FILE,
                    size=3,
                    modified_ns=3,
                ),
            )
        }
    )

    result = scan_documents(
        ScanRequest(
            root=tmp_path,
            max_entries=2,
            max_documents=1,
            max_document_bytes=10,
        ),
        reader=reader,
    )

    assert [item.relative_path.name for item in result.documents] == ["b.pdf"]
    assert result.inspected_entries == 2
    assert result.truncated
    assert {(issue.relative_path.as_posix(), issue.code) for issue in result.issues} == {
        ("a.pdf", ScanIssueCode.TOO_LARGE),
        (".", ScanIssueCode.ENTRY_LIMIT),
    }


def test_scan_limits_reject_zero_and_unbounded_depth(tmp_path: Path) -> None:
    """Invalid limits are rejected at the untrusted configuration boundary."""
    with pytest.raises(ValidationError):
        _ = ScanRequest(root=tmp_path, max_entries=0)
    with pytest.raises(ValidationError):
        _ = ScanRequest(root=tmp_path, max_depth=65)
