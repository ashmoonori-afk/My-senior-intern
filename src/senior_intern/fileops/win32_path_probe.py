# Copyright (c) 2026 My Senior Intern contributors

"""Fail-closed Win32 path-policy adapter."""

from pathlib import Path

from senior_intern.fileops.path_policy import (
    PathFacts,
    PathProbeError,
    PathRole,
)
from senior_intern.fileops.win32_native import NativeWin32ProbeBackend
from senior_intern.fileops.win32_types import (
    CLOUD_ATTRIBUTE_MASK,
    DRIVE_FIXED,
    DRIVE_REMOTE,
    FILE_ATTRIBUTE_OFFLINE,
    FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS,
    FILE_ATTRIBUTE_REPARSE_POINT,
    PLACEHOLDER_ATTRIBUTE_MASK,
    Win32ProbeBackend,
    Win32ProbeBackendError,
    Win32Snapshot,
)

_SUPPORTED_FILESYSTEMS = frozenset({"ntfs", "refs"})


class Win32PathProbe:
    """Map stable Win32 handle metadata into common policy facts."""

    _source_root: Path
    _backend: Win32ProbeBackend

    def __init__(
        self,
        *,
        source_root: Path,
        backend: Win32ProbeBackend | None = None,
    ) -> None:
        """Bind source-root context and a native or injected backend."""
        self._source_root = source_root
        self._backend = NativeWin32ProbeBackend() if backend is None else backend

    def inspect(self, path: Path, role: PathRole) -> PathFacts:
        """Return complete facts without opening document data."""
        try:
            snapshot = self._backend.snapshot(path, role, self._source_root)
        except Win32ProbeBackendError as error:
            raise PathProbeError(str(error)) from error
        if snapshot.path != path or snapshot.role is not role:
            message = "Win32 backend returned mismatched path facts"
            raise PathProbeError(message)
        filesystem_type = snapshot.filesystem_type.casefold()
        is_network = (
            snapshot.drive_type == DRIVE_REMOTE or _is_unc(path) or _is_unc(snapshot.final_path)
        )
        all_attributes = snapshot.attributes | snapshot.ancestor_attributes
        cloud_attributes = all_attributes & CLOUD_ATTRIBUTE_MASK
        is_link = snapshot.reparse_tag is not None or bool(
            snapshot.attributes & FILE_ATTRIBUTE_REPARSE_POINT
        )
        volume_id = ""
        object_id = ""
        if snapshot.exists:
            serial = f"{snapshot.volume_serial:016x}"
            volume_guid = snapshot.volume_guid.casefold()
            volume_id = f"win32-volume:{volume_guid}:{serial}"
            object_id = f"win32-object:{volume_guid}:{serial}:{snapshot.file_id.hex()}"
        return PathFacts(
            path=path,
            role=role,
            exists=snapshot.exists,
            kind=snapshot.kind,
            filesystem_type=filesystem_type,
            volume_id=volume_id,
            object_id=object_id,
            is_local=(
                snapshot.drive_type == DRIVE_FIXED and filesystem_type in _SUPPORTED_FILESYSTEMS
            ),
            is_network=is_network,
            is_link=is_link,
            no_follow_chain=snapshot.no_follow_chain,
            within_source_root=snapshot.within_source_root,
            is_cloud=bool(cloud_attributes),
            is_placeholder=bool(all_attributes & PLACEHOLDER_ATTRIBUTE_MASK),
            crosses_mount=snapshot.crosses_mount,
            identity_stable=snapshot.identity_stable,
            supports_no_replace=snapshot.supports_no_replace,
            classification_complete=snapshot.classification_complete,
        )


def _is_unc(path: Path) -> bool:
    text = str(path)
    folded = text.casefold()
    if folded.startswith("\\\\?\\unc\\"):
        return True
    if folded.startswith("\\\\?\\"):
        return False
    return text.startswith(("\\\\", "//"))


__all__ = [
    "DRIVE_FIXED",
    "DRIVE_REMOTE",
    "FILE_ATTRIBUTE_OFFLINE",
    "FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS",
    "NativeWin32ProbeBackend",
    "Win32PathProbe",
    "Win32ProbeBackend",
    "Win32ProbeBackendError",
    "Win32Snapshot",
]
