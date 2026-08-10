# Copyright (c) 2026 My Senior Intern contributors

"""Darwin coherent snapshot composition tests."""

from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from senior_intern.fileops.darwin_types import FileProviderState
from tests.unit.fileops.darwin_native_test_support import (
    inspect_native_fixture,
    make_native_fixture,
)


def test_paired_darwin_sweeps_issue_stable_snapshot(
    tmp_path: Path,
) -> None:
    """Unchanged descriptor and URL sweeps remain complete."""
    fixture = make_native_fixture(tmp_path)

    snapshot = inspect_native_fixture(fixture)

    assert snapshot.classification_complete
    assert snapshot.identity_stable
    assert snapshot.within_source_root
    assert not snapshot.crosses_mount


def test_darwin_descriptor_change_invalidates_composed_snapshot(
    tmp_path: Path,
) -> None:
    """A replacement between full sweeps fails closed."""
    fixture = make_native_fixture(tmp_path)
    changed_file = replace(fixture[3], st_ino=999)

    snapshot = inspect_native_fixture(
        fixture,
        file_infos=[fixture[3], changed_file],
    )

    assert not snapshot.classification_complete
    assert not snapshot.identity_stable


def test_darwin_url_identity_change_invalidates_snapshot(
    tmp_path: Path,
) -> None:
    """A resource-ID change between sweeps is unstable."""
    fixture = make_native_fixture(tmp_path)
    changed_url = replace(
        fixture[5],
        object_resource_id=b"replacement-resource",
    )

    snapshot = inspect_native_fixture(
        fixture,
        file_urls=[fixture[5], changed_url],
    )

    assert not snapshot.classification_complete
    assert not snapshot.identity_stable


def test_darwin_url_path_identity_must_match_descriptor(
    tmp_path: Path,
) -> None:
    """Path-based URL facts are bound to retained descriptor identity."""
    fixture = make_native_fixture(tmp_path)
    unrelated_url = replace(fixture[5], path_st_ino=fixture[5].path_st_ino + 1)

    snapshot = inspect_native_fixture(
        fixture,
        file_urls=[unrelated_url, unrelated_url],
    )

    assert not snapshot.classification_complete
    assert not snapshot.identity_stable


def test_unknown_file_provider_state_is_incomplete(
    tmp_path: Path,
) -> None:
    """UNKNOWN ownership never collapses to a local unmanaged result."""
    fixture = make_native_fixture(tmp_path)
    unknown_root = replace(
        fixture[4],
        file_provider_state=FileProviderState.UNKNOWN,
    )

    snapshot = inspect_native_fixture(
        fixture,
        root_urls=[unknown_root, unknown_root],
    )

    assert snapshot.file_provider_state is FileProviderState.UNKNOWN
    assert not snapshot.classification_complete


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("st_dev", -1),
        ("fsid", (55, 66)),
    ],
)
def test_darwin_nested_volume_transition_is_detected(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    """Each descriptor volume identity independently marks a mount."""
    fixture = make_native_fixture(tmp_path)
    other_root = (
        replace(fixture[2], st_dev=cast("int", value))
        if field == "st_dev"
        else replace(fixture[2], fsid=cast("tuple[int, int]", value))
    )

    snapshot = inspect_native_fixture(
        fixture,
        root_infos=[other_root, other_root],
    )

    assert snapshot.crosses_mount


def test_darwin_same_volume_mount_transition_is_detected(
    tmp_path: Path,
) -> None:
    """Mount-point identity catches same-volume indirection."""
    fixture = make_native_fixture(tmp_path)
    mounted_root = replace(fixture[2], mount_point="/Volumes/remount")

    snapshot = inspect_native_fixture(
        fixture,
        root_infos=[mounted_root, mounted_root],
    )

    assert snapshot.crosses_mount


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("volume_uuid", "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF"),
        ("volume_resource_id", b"other-volume-resource"),
    ],
)
def test_darwin_url_volume_transition_is_detected(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    """Each Foundation volume identity independently marks a mount."""
    fixture = make_native_fixture(tmp_path)
    other_root_url = (
        replace(fixture[4], volume_uuid=cast("str", value))
        if field == "volume_uuid"
        else replace(fixture[4], volume_resource_id=cast("bytes", value))
    )

    snapshot = inspect_native_fixture(
        fixture,
        root_urls=[other_root_url, other_root_url],
    )

    assert snapshot.crosses_mount


def test_darwin_cloud_ancestor_is_aggregated(
    tmp_path: Path,
) -> None:
    """A normal file below a managed ancestor remains cloud-backed."""
    fixture = make_native_fixture(tmp_path)
    managed_root = replace(
        fixture[4],
        file_provider_state=FileProviderState.MANAGED,
        is_ubiquitous=True,
        is_placeholder=True,
    )

    snapshot = inspect_native_fixture(
        fixture,
        root_urls=[managed_root, managed_root],
    )

    assert snapshot.file_provider_state is FileProviderState.MANAGED
    assert snapshot.is_ubiquitous
    assert snapshot.is_placeholder
