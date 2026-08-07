# Copyright (c) 2026 My Senior Intern contributors

"""Typed contracts for bounded document discovery."""

from enum import StrEnum
from pathlib import Path
from typing import ClassVar, Protocol

from pydantic import BaseModel, ConfigDict, Field

SUPPORTED_EXTENSIONS = frozenset({".docx", ".xlsx", ".pdf", ".csv", ".pptx"})


class EntryKind(StrEnum):
    """Physical kind observed without following links."""

    FILE = "file"
    DIRECTORY = "directory"
    LINK = "link"
    OTHER = "other"


class ScanIssueCode(StrEnum):
    """Non-fatal reason an entry was not discovered."""

    INACCESSIBLE = "inaccessible"
    LINK_SKIPPED = "link_skipped"
    TOO_LARGE = "too_large"
    ENTRY_LIMIT = "entry_limit"
    DOCUMENT_LIMIT = "document_limit"
    OUTSIDE_ROOT = "outside_root"


class FileSystemEntry(BaseModel):
    """One no-follow directory entry snapshot."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True, strict=True)

    name: str
    path: Path
    kind: EntryKind
    size: int | None = None
    modified_ns: int | None = None


class DirectoryReader(Protocol):
    """No-follow directory-enumeration boundary."""

    def entries(self, path: Path) -> tuple[FileSystemEntry, ...]:
        """Return physical entries or raise an operating-system error."""
        ...


class ScanRequest(BaseModel):
    """Explicit root, exclusions, and hard discovery limits."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True, strict=True)

    root: Path
    excluded_names: tuple[str, ...] = ()
    max_depth: int = Field(default=8, ge=0, le=64)
    max_entries: int = Field(default=50_000, ge=1, le=1_000_000)
    max_documents: int = Field(default=10_000, ge=1, le=100_000)
    max_document_bytes: int = Field(
        default=100 * 1024 * 1024,
        ge=1,
        le=10 * 1024 * 1024 * 1024,
    )


class DiscoveredDocument(BaseModel):
    """Supported local document metadata ready for policy checks."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True, strict=True)

    path: Path
    relative_path: Path
    extension: str
    size: int
    modified_ns: int


class ScanIssue(BaseModel):
    """A fail-closed discovery observation."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True, strict=True)

    relative_path: Path
    code: ScanIssueCode


class ScanResult(BaseModel):
    """Immutable bounded discovery result."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True, strict=True)

    documents: tuple[DiscoveredDocument, ...]
    issues: tuple[ScanIssue, ...]
    inspected_entries: int
    truncated: bool
