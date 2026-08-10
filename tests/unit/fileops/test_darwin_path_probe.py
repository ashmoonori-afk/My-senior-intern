# Copyright (c) 2026 My Senior Intern contributors

"""Darwin fail-closed path-policy adapter contract."""

import sys
from pathlib import Path

import pytest

from senior_intern.fileops.darwin_path_probe import (
    MNT_LOCAL,
    DarwinPathProbe,
    FileProviderState,
)
from senior_intern.fileops.path_policy import (
    PathPolicyRequest,
    PathProbeError,
    PathRole,
    PolicyDenial,
    evaluate_path_policy,
)
from tests.unit.fileops.darwin_probe_test_support import (
    FakeDarwinBackend,
    make_fixture,
)


@pytest.mark.parametrize("filesystem_type", ["apfs", "hfs"])
def test_local_darwin_allowlist_issues_stable_ticket(
    tmp_path: Path,
    filesystem_type: str,
) -> None:
    """APFS and HFS+ are the only accepted local Darwin filesystems."""
    request, snapshots = make_fixture(
        tmp_path,
        filesystem_type=filesystem_type,
    )

    decision = evaluate_path_policy(
        request,
        probe=DarwinPathProbe(
            source_root=request.source_root,
            backend=FakeDarwinBackend(snapshots),
        ),
    )

    assert decision.allowed
    assert decision.ticket is not None
    source_fact = decision.ticket.source_file
    assert source_fact.volume_id.startswith("darwin-volume:")
    assert source_fact.object_id.endswith(":66696c652d7265736f75726365")


@pytest.mark.parametrize(
    ("updates", "denial"),
    [
        ({"filesystem_type": "smbfs"}, PolicyDenial.UNSUPPORTED_FILESYSTEM),
        ({"filesystem_type": "nfs"}, PolicyDenial.UNSUPPORTED_FILESYSTEM),
        ({"mount_flags": 0}, PolicyDenial.NONLOCAL_VOLUME),
        ({"is_local": False}, PolicyDenial.NONLOCAL_VOLUME),
        ({"is_link": True}, PolicyDenial.LINK),
        ({"no_follow_chain": False}, PolicyDenial.LINK),
        ({"is_ubiquitous": True}, PolicyDenial.CLOUD_LOCATION),
        ({"is_placeholder": True}, PolicyDenial.PLACEHOLDER),
        (
            {"file_provider_state": FileProviderState.MANAGED},
            PolicyDenial.CLOUD_LOCATION,
        ),
        (
            {"file_provider_state": FileProviderState.UNKNOWN},
            PolicyDenial.API_UNAVAILABLE,
        ),
        ({"crosses_mount": True}, PolicyDenial.MOUNT_INDIRECTION),
        ({"identity_stable": False}, PolicyDenial.UNSTABLE_IDENTITY),
        (
            {"supports_persistent_ids": False},
            PolicyDenial.REQUIRED_CAPABILITY_MISSING,
        ),
        (
            {"supports_rename_excl": False},
            PolicyDenial.REQUIRED_CAPABILITY_MISSING,
        ),
        ({"classification_complete": False}, PolicyDenial.API_UNAVAILABLE),
    ],
)
def test_unsafe_darwin_snapshot_fails_closed(
    tmp_path: Path,
    updates: dict[str, object],
    denial: PolicyDenial,
) -> None:
    """Every nonlocal, indirect, cloud, or uncertain fact is denied."""
    request, snapshots = make_fixture(tmp_path)
    source_key = (request.source_file, PathRole.SOURCE_FILE)
    snapshots[source_key] = snapshots[source_key].model_copy(update=updates)

    decision = evaluate_path_policy(
        request,
        probe=DarwinPathProbe(
            source_root=request.source_root,
            backend=FakeDarwinBackend(snapshots),
        ),
    )

    assert decision.denial is denial


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fsid", (11, 23)),
        ("st_dev", 34),
        ("mount_point", "/Volumes/other"),
        ("volume_identifier", "other-volume"),
        ("volume_uuid", "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF"),
        ("volume_resource_id", b"other-volume-resource"),
    ],
)
def test_every_darwin_volume_identity_difference_is_denied(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    """All independent volume identities must agree across roles."""
    request, snapshots = make_fixture(tmp_path)
    destination_key = (
        request.destination_directory,
        PathRole.DESTINATION_DIRECTORY,
    )
    snapshots[destination_key] = snapshots[destination_key].model_copy(update={field: value})

    decision = evaluate_path_policy(
        request,
        probe=DarwinPathProbe(
            source_root=request.source_root,
            backend=FakeDarwinBackend(snapshots),
        ),
    )

    assert decision.denial is PolicyDenial.DIFFERENT_VOLUME


def test_darwin_backend_error_becomes_typed_probe_failure(
    tmp_path: Path,
) -> None:
    """Native API errors never become optimistic facts."""
    request, snapshots = make_fixture(tmp_path)
    backend = FakeDarwinBackend(snapshots)
    backend.error = True
    probe = DarwinPathProbe(source_root=request.source_root, backend=backend)

    with pytest.raises(PathProbeError):
        _ = probe.inspect(request.source_file, PathRole.SOURCE_FILE)


def test_real_darwin_probe_is_platform_gated_and_accepts_fixture(
    tmp_path: Path,
) -> None:
    """The real adapter rejects other OSes and accepts a local macOS fixture."""
    source_root = tmp_path / "source"
    destination = tmp_path / "destination"
    source_root.mkdir()
    destination.mkdir()
    source_file = source_root / "document.pdf"
    _ = source_file.write_bytes(b"darwin probe fixture")
    request = PathPolicyRequest(
        source_root=source_root,
        source_file=source_file,
        destination_directory=destination,
    )
    probe = DarwinPathProbe(source_root=source_root)
    if sys.platform != "darwin":
        with pytest.raises(PathProbeError):
            _ = probe.inspect(source_file, PathRole.SOURCE_FILE)
        return

    decision = evaluate_path_policy(request, probe=probe)
    missing = evaluate_path_policy(
        request.model_copy(update={"source_file": source_root / "missing.pdf"}),
        probe=probe,
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "outside.pdf"
    _ = outside_file.write_bytes(b"outside")
    linked_source = source_root / "linked"
    linked_source.symlink_to(outside, target_is_directory=True)
    direct_file_link = source_root / "direct-link.pdf"
    direct_file_link.symlink_to(outside_file)
    linked_root = tmp_path / "source-link"
    linked_root.symlink_to(source_root, target_is_directory=True)
    linked_destination = tmp_path / "destination-link"
    linked_destination.symlink_to(destination, target_is_directory=True)
    destination_parent_link = tmp_path / "destination-parent-link"
    destination_parent_link.symlink_to(tmp_path, target_is_directory=True)
    source_link_decision = evaluate_path_policy(
        request.model_copy(update={"source_file": linked_source / "outside.pdf"}),
        probe=probe,
    )
    destination_link_decision = evaluate_path_policy(
        request.model_copy(update={"destination_directory": linked_destination}),
        probe=probe,
    )
    direct_file_link_decision = evaluate_path_policy(
        request.model_copy(update={"source_file": direct_file_link}),
        probe=probe,
    )
    linked_root_decision = evaluate_path_policy(
        request.model_copy(
            update={
                "source_root": linked_root,
                "source_file": linked_root / source_file.name,
            }
        ),
        probe=DarwinPathProbe(source_root=linked_root),
    )
    nested_destination_link_decision = evaluate_path_policy(
        request.model_copy(
            update={"destination_directory": destination_parent_link / destination.name}
        ),
        probe=probe,
    )

    assert decision.allowed
    assert missing.denial is PolicyDenial.NOT_FOUND
    assert source_link_decision.denial is PolicyDenial.LINK
    assert destination_link_decision.denial is PolicyDenial.LINK
    assert direct_file_link_decision.denial is PolicyDenial.LINK
    assert linked_root_decision.denial is PolicyDenial.LINK
    assert nested_destination_link_decision.denial is PolicyDenial.LINK
    assert source_file.read_bytes() == b"darwin probe fixture"
    assert MNT_LOCAL != 0
