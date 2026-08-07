# Copyright (c) 2026 My Senior Intern contributors

"""Native Win32 ancestry and snapshot orchestration tests."""

from dataclasses import replace
from pathlib import Path

import pytest

from senior_intern.fileops.path_policy import PathProbeError, PathRole
from senior_intern.fileops.win32_native import NativeWin32ProbeBackend
from senior_intern.fileops.win32_path_probe import (
    FILE_ATTRIBUTE_OFFLINE,
    Win32PathProbe,
)
from senior_intern.fileops.win32_types import (
    FILE_ATTRIBUTE_REPARSE_POINT,
    Win32ProbeBackendError,
)
from tests.unit.fileops.win32_native_test_support import (
    make_handle_info,
    make_native_fixture,
    path_key,
)


def test_native_cloud_ancestor_is_aggregated_into_path_fact() -> None:
    """A normal file beneath a cloud-marked directory is cloud-backed."""
    reader, source_root, source_file = make_native_fixture()
    root_info = reader.infos[path_key(source_root)]
    reader.infos[path_key(source_root)] = replace(
        root_info,
        attributes=FILE_ATTRIBUTE_OFFLINE,
    )
    probe = Win32PathProbe(
        source_root=source_root,
        backend=NativeWin32ProbeBackend(api=reader),
    )

    fact = probe.inspect(source_file, PathRole.SOURCE_FILE)

    assert fact.is_cloud
    assert fact.is_placeholder


def test_native_reparse_ancestor_marks_chain_unsafe() -> None:
    """A junction-like source root invalidates the no-follow chain."""
    reader, source_root, source_file = make_native_fixture()
    root_info = reader.infos[path_key(source_root)]
    reader.infos[path_key(source_root)] = replace(
        root_info,
        attributes=FILE_ATTRIBUTE_REPARSE_POINT,
        reparse_tag=0xA0000003,
    )

    snapshot = NativeWin32ProbeBackend(api=reader).snapshot(
        source_file,
        PathRole.SOURCE_FILE,
        source_root,
    )

    assert not snapshot.no_follow_chain


def test_native_ancestor_volume_guid_change_marks_mount_crossing() -> None:
    """Both volume GUID and serial participate in ancestry identity."""
    reader, source_root, source_file = make_native_fixture()
    volume_root = Path("C:\\")
    root_info = reader.infos[path_key(volume_root)]
    reader.infos[path_key(volume_root)] = replace(
        root_info,
        volume_guid="different-volume-guid",
    )

    snapshot = NativeWin32ProbeBackend(api=reader).snapshot(
        source_file,
        PathRole.SOURCE_FILE,
        source_root,
    )

    assert snapshot.crosses_mount


def test_native_differing_target_reads_mark_identity_unstable() -> None:
    """A replacement between paired target reads cannot issue stable facts."""
    reader, source_root, source_file = make_native_fixture()
    initial = reader.infos[path_key(source_file)]
    reader.script(
        source_file,
        [initial, replace(initial, file_id=b"replacement-id!!")],
    )

    snapshot = NativeWin32ProbeBackend(api=reader).snapshot(
        source_file,
        PathRole.SOURCE_FILE,
        source_root,
    )

    assert not snapshot.identity_stable


def test_native_disappearance_between_target_reads_is_unstable() -> None:
    """An object disappearing during paired reads fails closed."""
    reader, source_root, source_file = make_native_fixture()
    initial = reader.infos[path_key(source_file)]
    reader.script(source_file, [initial, None])

    snapshot = NativeWin32ProbeBackend(api=reader).snapshot(
        source_file,
        PathRole.SOURCE_FILE,
        source_root,
    )

    assert not snapshot.identity_stable


def test_native_final_sweep_rejects_incoherent_ancestry() -> None:
    """Mutation after local pair checks invalidates the composed snapshot."""
    reader, source_root, source_file = make_native_fixture()
    initial = reader.infos[path_key(source_file)]
    changed = replace(initial, file_id=b"changed-in-sweep")
    reader.script(source_file, [initial, initial, initial, initial, changed])

    snapshot = NativeWin32ProbeBackend(api=reader).snapshot(
        source_file,
        PathRole.SOURCE_FILE,
        source_root,
    )

    assert not snapshot.classification_complete
    assert not snapshot.identity_stable


def test_native_missing_target_returns_expected_absence() -> None:
    """CreateFile file-not-found maps to an incomplete object, not optimism."""
    reader, source_root, source_file = make_native_fixture()
    del reader.infos[path_key(source_file)]

    snapshot = NativeWin32ProbeBackend(api=reader).snapshot(
        source_file,
        PathRole.SOURCE_FILE,
        source_root,
    )

    assert not snapshot.exists


def test_native_missing_source_root_raises_typed_failure() -> None:
    """An existing target without its nominated root fails closed."""
    reader, source_root, source_file = make_native_fixture()
    del reader.infos[path_key(source_root)]

    with pytest.raises(
        Win32ProbeBackendError,
        match="source root disappeared",
    ):
        _ = NativeWin32ProbeBackend(api=reader).snapshot(
            source_file,
            PathRole.SOURCE_FILE,
            source_root,
        )


def test_native_ancestor_api_error_becomes_probe_error() -> None:
    """A metadata error at any intermediate component is not swallowed."""
    reader, source_root, _source_file = make_native_fixture()
    child = Path(r"C:\source\child")
    source_file = child / "document.pdf"
    reader.infos[path_key(child)] = make_handle_info(child, directory=True)
    reader.infos[path_key(source_file)] = make_handle_info(
        source_file,
        directory=False,
    )
    reader.fail(child)
    probe = Win32PathProbe(
        source_root=source_root,
        backend=NativeWin32ProbeBackend(api=reader),
    )

    with pytest.raises(PathProbeError, match="scripted metadata failure"):
        _ = probe.inspect(source_file, PathRole.SOURCE_FILE)


def test_native_physical_path_outside_root_is_not_contained() -> None:
    """Final handle paths, not lexical spelling, prove containment."""
    reader, source_root, source_file = make_native_fixture()
    initial = reader.infos[path_key(source_file)]
    reader.infos[path_key(source_file)] = replace(
        initial,
        final_path=Path(r"C:\outside\document.pdf"),
    )

    snapshot = NativeWin32ProbeBackend(api=reader).snapshot(
        source_file,
        PathRole.SOURCE_FILE,
        source_root,
    )

    assert not snapshot.within_source_root
