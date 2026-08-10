# Copyright (c) 2026 My Senior Intern contributors

"""Typed Darwin filesystem classification contracts."""

from enum import StrEnum
from pathlib import Path
from typing import ClassVar, Protocol

from pydantic import BaseModel, ConfigDict

from senior_intern.fileops.path_policy import ObjectKind, PathRole

MNT_LOCAL = 0x00001000


class FileProviderState(StrEnum):
    """Documented File Provider ownership result."""

    NOT_MANAGED = "not_managed"
    MANAGED = "managed"
    UNKNOWN = "unknown"


class DarwinProbeBackendError(RuntimeError):
    """A Darwin metadata API failed or returned uncertain data."""


class DarwinSnapshot(BaseModel):
    """One stable no-follow Darwin metadata snapshot."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True, strict=True)

    path: Path
    role: PathRole
    exists: bool
    kind: ObjectKind
    filesystem_type: str
    fsid: tuple[int, int]
    st_dev: int
    mount_point: str
    volume_identifier: str
    volume_uuid: str
    object_resource_id: bytes
    volume_resource_id: bytes
    mount_flags: int
    is_local: bool
    is_link: bool
    no_follow_chain: bool
    within_source_root: bool
    is_ubiquitous: bool
    is_placeholder: bool
    file_provider_state: FileProviderState
    crosses_mount: bool
    identity_stable: bool
    supports_persistent_ids: bool
    supports_rename_excl: bool
    classification_complete: bool


class DarwinProbeBackend(Protocol):
    """Native Darwin metadata boundary."""

    def snapshot(
        self,
        path: Path,
        role: PathRole,
        source_root: Path,
    ) -> DarwinSnapshot:
        """Return one complete no-follow snapshot."""
        ...
