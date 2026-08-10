# Copyright (c) 2026 My Senior Intern contributors

"""Shared fixtures for Darwin path-probe tests."""

from pathlib import Path
from typing import override

from senior_intern.fileops.darwin_path_probe import (
    MNT_LOCAL,
    DarwinProbeBackend,
    DarwinProbeBackendError,
    DarwinSnapshot,
    FileProviderState,
)
from senior_intern.fileops.path_policy import (
    ObjectKind,
    PathPolicyRequest,
    PathRole,
)


class FakeDarwinBackend(DarwinProbeBackend):
    """Deterministic Darwin metadata fixture."""

    snapshots: dict[tuple[Path, PathRole], DarwinSnapshot]
    error: bool

    def __init__(
        self,
        snapshots: dict[tuple[Path, PathRole], DarwinSnapshot],
    ) -> None:
        """Store one complete snapshot per role."""
        self.snapshots = snapshots
        self.error = False

    @override
    def snapshot(
        self,
        path: Path,
        role: PathRole,
        source_root: Path,
    ) -> DarwinSnapshot:
        """Return a snapshot or a typed native failure."""
        del source_root
        if self.error:
            message = "fstatfs failed"
            raise DarwinProbeBackendError(message)
        return self.snapshots[(path, role)]


def make_snapshot(
    path: Path,
    role: PathRole,
    *,
    kind: ObjectKind,
    object_resource_id: bytes,
    filesystem_type: str = "apfs",
) -> DarwinSnapshot:
    """Build one complete local Darwin snapshot."""
    return DarwinSnapshot(
        path=path,
        role=role,
        exists=True,
        kind=kind,
        filesystem_type=filesystem_type,
        fsid=(11, 22),
        st_dev=33,
        mount_point="/",
        volume_identifier="volume-identifier",
        volume_uuid="01234567-89AB-CDEF-0123-456789ABCDEF",
        object_resource_id=object_resource_id,
        volume_resource_id=b"volume-resource",
        mount_flags=MNT_LOCAL,
        is_local=True,
        is_link=False,
        no_follow_chain=True,
        within_source_root=True,
        is_ubiquitous=False,
        is_placeholder=False,
        file_provider_state=FileProviderState.NOT_MANAGED,
        crosses_mount=False,
        identity_stable=True,
        supports_persistent_ids=True,
        supports_rename_excl=True,
        classification_complete=True,
    )


def make_fixture(
    tmp_path: Path,
    *,
    filesystem_type: str = "apfs",
) -> tuple[PathPolicyRequest, dict[tuple[Path, PathRole], DarwinSnapshot]]:
    """Build three same-volume Darwin role snapshots."""
    source_root = tmp_path / "source"
    source_file = source_root / "document.pdf"
    destination = tmp_path / "destination"
    request = PathPolicyRequest(
        source_root=source_root,
        source_file=source_file,
        destination_directory=destination,
    )
    snapshots = {
        (source_root, PathRole.SOURCE_ROOT): make_snapshot(
            source_root,
            PathRole.SOURCE_ROOT,
            kind=ObjectKind.DIRECTORY,
            object_resource_id=b"root-resource",
            filesystem_type=filesystem_type,
        ),
        (source_file, PathRole.SOURCE_FILE): make_snapshot(
            source_file,
            PathRole.SOURCE_FILE,
            kind=ObjectKind.FILE,
            object_resource_id=b"file-resource",
            filesystem_type=filesystem_type,
        ),
        (destination, PathRole.DESTINATION_DIRECTORY): make_snapshot(
            destination,
            PathRole.DESTINATION_DIRECTORY,
            kind=ObjectKind.DIRECTORY,
            object_resource_id=b"destination-resource",
            filesystem_type=filesystem_type,
        ),
    }
    return request, snapshots
