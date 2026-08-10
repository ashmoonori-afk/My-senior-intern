# Copyright (c) 2026 My Senior Intern contributors

"""Fail-closed Darwin path-policy adapter."""

from pathlib import Path

from senior_intern.fileops.darwin_native import NativeDarwinProbeBackend
from senior_intern.fileops.darwin_types import (
    MNT_LOCAL,
    DarwinProbeBackend,
    DarwinProbeBackendError,
    DarwinSnapshot,
    FileProviderState,
)
from senior_intern.fileops.path_policy import PathFacts, PathProbeError, PathRole

_SUPPORTED_FILESYSTEMS = frozenset({"apfs", "hfs"})


class DarwinPathProbe:
    """Map stable Darwin metadata into common path-policy facts."""

    _source_root: Path
    _backend: DarwinProbeBackend

    def __init__(
        self,
        *,
        source_root: Path,
        backend: DarwinProbeBackend | None = None,
    ) -> None:
        """Bind source-root context and a native or injected backend."""
        self._source_root = source_root
        self._backend = NativeDarwinProbeBackend() if backend is None else backend

    def inspect(self, path: Path, role: PathRole) -> PathFacts:
        """Return complete facts without reading document data."""
        try:
            snapshot = self._backend.snapshot(path, role, self._source_root)
        except DarwinProbeBackendError as error:
            raise PathProbeError(str(error)) from error
        if snapshot.path != path or snapshot.role is not role:
            message = "Darwin backend returned mismatched path facts"
            raise PathProbeError(message)
        filesystem_type = snapshot.filesystem_type.casefold()
        volume_id = ""
        object_id = ""
        if snapshot.exists:
            fsid = f"{snapshot.fsid[0]}:{snapshot.fsid[1]}"
            stable_volume = (
                f"{snapshot.volume_uuid.casefold()}:{snapshot.st_dev}:{fsid}:"
                f"{snapshot.mount_point}:{snapshot.volume_identifier}:"
                f"{snapshot.volume_resource_id.hex()}"
            )
            volume_id = f"darwin-volume:{stable_volume}"
            object_id = f"darwin-object:{stable_volume}:{snapshot.object_resource_id.hex()}"
        provider_known = snapshot.file_provider_state is not FileProviderState.UNKNOWN
        is_local = (
            snapshot.is_local
            and bool(snapshot.mount_flags & MNT_LOCAL)
            and filesystem_type in _SUPPORTED_FILESYSTEMS
        )
        return PathFacts(
            path=path,
            role=role,
            exists=snapshot.exists,
            kind=snapshot.kind,
            filesystem_type=filesystem_type,
            volume_id=volume_id,
            object_id=object_id,
            is_local=is_local,
            is_network=not snapshot.is_local,
            is_link=snapshot.is_link,
            no_follow_chain=snapshot.no_follow_chain,
            within_source_root=snapshot.within_source_root,
            is_cloud=(
                snapshot.is_ubiquitous or snapshot.file_provider_state is FileProviderState.MANAGED
            ),
            is_placeholder=snapshot.is_placeholder,
            crosses_mount=snapshot.crosses_mount,
            identity_stable=snapshot.identity_stable,
            supports_no_replace=(
                snapshot.supports_persistent_ids and snapshot.supports_rename_excl
            ),
            classification_complete=(snapshot.classification_complete and provider_known),
        )


__all__ = [
    "MNT_LOCAL",
    "DarwinPathProbe",
    "DarwinProbeBackend",
    "DarwinProbeBackendError",
    "DarwinSnapshot",
    "FileProviderState",
]
