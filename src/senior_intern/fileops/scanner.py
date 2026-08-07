# Copyright (c) 2026 My Senior Intern contributors

"""Bounded local document discovery."""

import os
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from senior_intern.fileops.discovery import (
    SUPPORTED_EXTENSIONS,
    DirectoryReader,
    DiscoveredDocument,
    EntryKind,
    FileSystemEntry,
    ScanIssue,
    ScanIssueCode,
    ScanRequest,
    ScanResult,
)


class LocalDirectoryReader:
    """Read directory entries without following links."""

    def entries(self, path: Path) -> tuple[FileSystemEntry, ...]:
        """Snapshot one local directory."""
        with os.scandir(path) as iterator:
            return tuple(_snapshot_entry(entry) for entry in iterator)


def _snapshot_entry(entry: os.DirEntry[str]) -> FileSystemEntry:
    entry_path = Path(entry.path)
    if entry.is_symlink():
        return FileSystemEntry(name=entry.name, path=entry_path, kind=EntryKind.LINK)
    if entry.is_dir(follow_symlinks=False):
        return FileSystemEntry(name=entry.name, path=entry_path, kind=EntryKind.DIRECTORY)
    if entry.is_file(follow_symlinks=False):
        stat_result = entry.stat(follow_symlinks=False)
        return FileSystemEntry(
            name=entry.name,
            path=entry_path,
            kind=EntryKind.FILE,
            size=stat_result.st_size,
            modified_ns=stat_result.st_mtime_ns,
        )
    return FileSystemEntry(name=entry.name, path=entry_path, kind=EntryKind.OTHER)


@dataclass
class _ScanState:
    pending: deque[tuple[Path, int]]
    documents: list[DiscoveredDocument] = field(default_factory=list)
    issues: list[ScanIssue] = field(default_factory=list)
    inspected_entries: int = 0
    truncated: bool = False


def _add_issue(state: _ScanState, relative_path: Path, code: ScanIssueCode) -> None:
    state.issues.append(ScanIssue(relative_path=relative_path, code=code))


def _relative_path(
    entry: FileSystemEntry,
    request: ScanRequest,
    state: _ScanState,
) -> Path | None:
    try:
        return entry.path.relative_to(request.root)
    except ValueError:
        _add_issue(state, Path(), ScanIssueCode.OUTSIDE_ROOT)
        return None


def _file_outcome(
    entry: FileSystemEntry,
    relative_path: Path,
    request: ScanRequest,
) -> DiscoveredDocument | ScanIssue | None:
    extension = entry.path.suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        return None
    if entry.size is None or entry.modified_ns is None:
        return ScanIssue(relative_path=relative_path, code=ScanIssueCode.INACCESSIBLE)
    if entry.size > request.max_document_bytes:
        return ScanIssue(relative_path=relative_path, code=ScanIssueCode.TOO_LARGE)
    return DiscoveredDocument(
        path=entry.path,
        relative_path=relative_path,
        extension=extension,
        size=entry.size,
        modified_ns=entry.modified_ns,
    )


def _process_entry(
    entry: FileSystemEntry,
    *,
    depth: int,
    request: ScanRequest,
    excluded_names: frozenset[str],
    state: _ScanState,
) -> None:
    relative_path = _relative_path(entry, request, state)
    if relative_path is None or entry.name.casefold() in excluded_names:
        return

    match entry.kind:
        case EntryKind.LINK:
            _add_issue(state, relative_path, ScanIssueCode.LINK_SKIPPED)
            return
        case EntryKind.DIRECTORY:
            if depth < request.max_depth:
                state.pending.append((entry.path, depth + 1))
            return
        case EntryKind.OTHER:
            return
        case EntryKind.FILE:
            pass

    outcome = _file_outcome(entry, relative_path, request)
    if outcome is None:
        return
    if isinstance(outcome, ScanIssue):
        state.issues.append(outcome)
    elif len(state.documents) >= request.max_documents:
        _add_issue(state, relative_path, ScanIssueCode.DOCUMENT_LIMIT)
        state.truncated = True
    else:
        state.documents.append(outcome)


def scan_documents(
    request: ScanRequest,
    *,
    reader: DirectoryReader | None = None,
) -> ScanResult:
    """Discover supported documents without broadening the selected root."""
    active_reader = LocalDirectoryReader() if reader is None else reader
    excluded_names = frozenset(name.casefold() for name in request.excluded_names)
    state = _ScanState(pending=deque([(request.root, 0)]))

    while state.pending and not state.truncated:
        directory, depth = state.pending.popleft()
        try:
            entries = active_reader.entries(directory)
        except OSError:
            relative_directory = (
                Path() if directory == request.root else directory.relative_to(request.root)
            )
            _add_issue(state, relative_directory, ScanIssueCode.INACCESSIBLE)
            continue

        for entry in sorted(entries, key=lambda item: (item.name.casefold(), item.name)):
            if state.inspected_entries >= request.max_entries:
                _add_issue(state, Path(), ScanIssueCode.ENTRY_LIMIT)
                state.truncated = True
                break
            state.inspected_entries += 1
            _process_entry(
                entry,
                depth=depth,
                request=request,
                excluded_names=excluded_names,
                state=state,
            )
            if state.truncated:
                break

    return ScanResult(
        documents=tuple(state.documents),
        issues=tuple(state.issues),
        inspected_entries=state.inspected_entries,
        truncated=state.truncated,
    )
