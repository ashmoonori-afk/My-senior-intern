# Copyright (c) 2026 My Senior Intern contributors

"""Typed Win32 filesystem classification contracts."""

from pathlib import Path
from typing import ClassVar, Protocol

from pydantic import BaseModel, ConfigDict

from senior_intern.fileops.path_policy import ObjectKind, PathRole

DRIVE_UNKNOWN = 0
DRIVE_NO_ROOT_DIR = 1
DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
DRIVE_REMOTE = 4
DRIVE_CDROM = 5
DRIVE_RAMDISK = 6

FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
FILE_ATTRIBUTE_OFFLINE = 0x00001000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x00040000
FILE_ATTRIBUTE_PINNED = 0x00080000
FILE_ATTRIBUTE_UNPINNED = 0x00100000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000

CLOUD_ATTRIBUTE_MASK = (
    FILE_ATTRIBUTE_OFFLINE
    | FILE_ATTRIBUTE_RECALL_ON_OPEN
    | FILE_ATTRIBUTE_PINNED
    | FILE_ATTRIBUTE_UNPINNED
    | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
)
PLACEHOLDER_ATTRIBUTE_MASK = (
    FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
)


class Win32ProbeBackendError(RuntimeError):
    """A Win32 metadata API failed or returned uncertain data."""


class Win32Snapshot(BaseModel):
    """One stable no-follow Win32 metadata snapshot."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True, strict=True)

    path: Path
    role: PathRole
    exists: bool
    kind: ObjectKind
    filesystem_type: str
    drive_type: int
    volume_serial: int
    volume_guid: str
    file_id: bytes
    attributes: int
    ancestor_attributes: int
    reparse_tag: int | None
    final_path: Path
    within_source_root: bool
    no_follow_chain: bool
    crosses_mount: bool
    identity_stable: bool
    supports_no_replace: bool
    classification_complete: bool


class Win32ProbeBackend(Protocol):
    """Native metadata boundary used by the policy adapter."""

    def snapshot(
        self,
        path: Path,
        role: PathRole,
        source_root: Path,
    ) -> Win32Snapshot:
        """Return one complete no-follow snapshot."""
        ...
