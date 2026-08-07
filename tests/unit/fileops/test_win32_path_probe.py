# Copyright (c) 2026 My Senior Intern contributors

"""Win32 no-follow filesystem classification contract tests."""

import sys
from pathlib import Path

import pytest

from senior_intern.fileops.path_policy import (
    PathPolicyRequest,
    PathProbeError,
    PathRole,
    PolicyDenial,
    evaluate_path_policy,
)
from senior_intern.fileops.win32_path_probe import (
    DRIVE_REMOTE,
    FILE_ATTRIBUTE_OFFLINE,
    FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS,
    Win32PathProbe,
)
from tests.unit.fileops.win32_native_test_support import create_junction
from tests.unit.fileops.win32_probe_test_support import (
    FakeWin32Backend,
    make_fixture,
)


def test_fixed_ntfs_snapshot_maps_stable_opaque_identity(tmp_path: Path) -> None:
    """Win32 identity combines the full volume serial and file ID."""
    request, snapshots = make_fixture(tmp_path)
    probe = Win32PathProbe(
        source_root=request.source_root,
        backend=FakeWin32Backend(snapshots),
    )

    fact = probe.inspect(request.source_file, PathRole.SOURCE_FILE)

    assert fact.filesystem_type == "ntfs"
    assert fact.volume_id == "win32-volume:volume-guid-11:000000000000000b"
    assert fact.object_id == "win32-object:volume-guid-11:000000000000000b:66696c652d6964"
    assert fact.is_local
    assert not fact.is_network
    assert not fact.is_link
    assert not fact.is_cloud


def test_fixed_ntfs_same_volume_policy_is_allowed(tmp_path: Path) -> None:
    """Three stable local snapshots issue one safe ticket."""
    request, snapshots = make_fixture(tmp_path)

    decision = evaluate_path_policy(
        request,
        probe=Win32PathProbe(
            source_root=request.source_root,
            backend=FakeWin32Backend(snapshots),
        ),
    )

    assert decision.allowed
    assert decision.ticket is not None


def test_real_win32_junction_target_and_ancestor_are_denied(
    tmp_path: Path,
) -> None:
    """Real Windows junctions fail closed without requiring symlink privilege."""
    source_root = tmp_path / "source"
    destination = tmp_path / "destination"
    outside = tmp_path / "outside"
    source_root.mkdir()
    destination.mkdir()
    outside.mkdir()
    source_file = source_root / "document.pdf"
    _ = source_file.write_bytes(b"junction fixture")
    probe = Win32PathProbe(source_root=source_root)
    if sys.platform != "win32":
        with pytest.raises(PathProbeError):
            _ = probe.inspect(source_file, PathRole.SOURCE_FILE)
        return
    ancestor_junction = source_root / "linked"
    destination_junction = tmp_path / "destination-link"
    create_junction(ancestor_junction, outside)
    create_junction(destination_junction, destination)
    external_file = outside / "external.pdf"
    _ = external_file.write_bytes(b"external")

    linked_source = evaluate_path_policy(
        PathPolicyRequest(
            source_root=source_root,
            source_file=ancestor_junction / "external.pdf",
            destination_directory=destination,
        ),
        probe=probe,
    )
    linked_destination = evaluate_path_policy(
        PathPolicyRequest(
            source_root=source_root,
            source_file=source_file,
            destination_directory=destination_junction,
        ),
        probe=probe,
    )

    assert linked_source.denial is PolicyDenial.LINK
    assert linked_destination.denial is PolicyDenial.LINK
    assert source_file.read_bytes() == b"junction fixture"
    ancestor_junction.rmdir()
    destination_junction.rmdir()


@pytest.mark.parametrize(
    ("updates", "denial"),
    [
        ({"drive_type": DRIVE_REMOTE}, PolicyDenial.NONLOCAL_VOLUME),
        ({"filesystem_type": "FAT32"}, PolicyDenial.UNSUPPORTED_FILESYSTEM),
        ({"reparse_tag": 0xA000000C}, PolicyDenial.LINK),
        ({"attributes": FILE_ATTRIBUTE_OFFLINE}, PolicyDenial.CLOUD_LOCATION),
        (
            {"attributes": FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS},
            PolicyDenial.CLOUD_LOCATION,
        ),
        ({"no_follow_chain": False}, PolicyDenial.LINK),
        ({"crosses_mount": True}, PolicyDenial.MOUNT_INDIRECTION),
        ({"identity_stable": False}, PolicyDenial.UNSTABLE_IDENTITY),
        ({"supports_no_replace": False}, PolicyDenial.REQUIRED_CAPABILITY_MISSING),
        ({"classification_complete": False}, PolicyDenial.API_UNAVAILABLE),
    ],
)
def test_unsafe_win32_snapshot_fails_closed(
    tmp_path: Path,
    updates: dict[str, object],
    denial: PolicyDenial,
) -> None:
    """Every uncertain or indirect snapshot is denied before movement."""
    request, snapshots = make_fixture(tmp_path)
    source_key = (request.source_file, PathRole.SOURCE_FILE)
    snapshots[source_key] = snapshots[source_key].model_copy(update=updates)

    decision = evaluate_path_policy(
        request,
        probe=Win32PathProbe(
            source_root=request.source_root,
            backend=FakeWin32Backend(snapshots),
        ),
    )

    assert not decision.allowed
    assert decision.denial is denial


def test_different_win32_volume_is_denied(tmp_path: Path) -> None:
    """Destination volume identity must match the source handles."""
    request, snapshots = make_fixture(tmp_path)
    destination_key = (
        request.destination_directory,
        PathRole.DESTINATION_DIRECTORY,
    )
    snapshots[destination_key] = snapshots[destination_key].model_copy(update={"volume_serial": 12})

    decision = evaluate_path_policy(
        request,
        probe=Win32PathProbe(
            source_root=request.source_root,
            backend=FakeWin32Backend(snapshots),
        ),
    )

    assert decision.denial is PolicyDenial.DIFFERENT_VOLUME


def test_native_backend_error_becomes_typed_probe_failure(tmp_path: Path) -> None:
    """Native API errors never become optimistic facts."""
    request, snapshots = make_fixture(tmp_path)
    backend = FakeWin32Backend(snapshots)
    backend.error = True
    probe = Win32PathProbe(source_root=request.source_root, backend=backend)

    with pytest.raises(PathProbeError):
        _ = probe.inspect(request.source_file, PathRole.SOURCE_FILE)


def test_real_win32_probe_is_platform_gated_and_accepts_fixture(
    tmp_path: Path,
) -> None:
    """The real adapter rejects other OSes and accepts a local Windows fixture."""
    source_root = tmp_path / "source"
    destination = tmp_path / "destination"
    source_root.mkdir()
    destination.mkdir()
    source_file = source_root / "document.pdf"
    _ = source_file.write_bytes(b"probe fixture")
    request = PathPolicyRequest(
        source_root=source_root,
        source_file=source_file,
        destination_directory=destination,
    )
    probe = Win32PathProbe(source_root=source_root)
    if sys.platform != "win32":
        with pytest.raises(PathProbeError):
            _ = probe.inspect(source_file, PathRole.SOURCE_FILE)
        return

    decision = evaluate_path_policy(
        request,
        probe=probe,
    )

    assert decision.allowed
    missing = evaluate_path_policy(
        request.model_copy(update={"source_file": source_root / "missing.pdf"}),
        probe=probe,
    )
    assert missing.denial is PolicyDenial.NOT_FOUND
