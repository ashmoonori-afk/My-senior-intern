# Copyright (c) 2026 My Senior Intern contributors

"""Shared fixtures for Win32 path probe tests."""

from pathlib import Path
from typing import override

from senior_intern.fileops.path_policy import (
    ObjectKind,
    PathPolicyRequest,
    PathRole,
)
from senior_intern.fileops.win32_path_probe import (
    DRIVE_FIXED,
    Win32ProbeBackend,
    Win32ProbeBackendError,
    Win32Snapshot,
)


class FakeWin32Backend(Win32ProbeBackend):
    """Deterministic native-boundary fixture."""

    snapshots: dict[tuple[Path, PathRole], Win32Snapshot]
    error: bool

    def __init__(
        self,
        snapshots: dict[tuple[Path, PathRole], Win32Snapshot],
    ) -> None:
        """Store one complete snapshot per requested role."""
        self.snapshots = snapshots
        self.error = False

    @override
    def snapshot(
        self,
        path: Path,
        role: PathRole,
        source_root: Path,
    ) -> Win32Snapshot:
        """Return one snapshot or a typed native failure."""
        del source_root
        if self.error:
            message = "GetFileInformationByHandleEx"
            raise Win32ProbeBackendError(message)
        return self.snapshots[(path, role)]


def make_snapshot(
    path: Path,
    role: PathRole,
    *,
    kind: ObjectKind,
    file_id: bytes,
) -> Win32Snapshot:
    """Build one complete fixed-NTFS snapshot."""
    return Win32Snapshot(
        path=path,
        role=role,
        exists=True,
        kind=kind,
        filesystem_type="NTFS",
        drive_type=DRIVE_FIXED,
        volume_serial=11,
        volume_guid="volume-guid-11",
        file_id=file_id,
        attributes=0,
        ancestor_attributes=0,
        reparse_tag=None,
        final_path=path,
        within_source_root=True,
        no_follow_chain=True,
        crosses_mount=False,
        identity_stable=True,
        supports_no_replace=True,
        classification_complete=True,
    )


def make_fixture(
    tmp_path: Path,
) -> tuple[PathPolicyRequest, dict[tuple[Path, PathRole], Win32Snapshot]]:
    """Build three same-volume role snapshots."""
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
            file_id=b"root-id",
        ),
        (source_file, PathRole.SOURCE_FILE): make_snapshot(
            source_file,
            PathRole.SOURCE_FILE,
            kind=ObjectKind.FILE,
            file_id=b"file-id",
        ),
        (destination, PathRole.DESTINATION_DIRECTORY): make_snapshot(
            destination,
            PathRole.DESTINATION_DIRECTORY,
            kind=ObjectKind.DIRECTORY,
            file_id=b"destination-id",
        ),
    }
    return request, snapshots
