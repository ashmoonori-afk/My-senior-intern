# Copyright (c) 2026 My Senior Intern contributors

"""Win32 path-fact mapping edge matrix."""

from pathlib import Path

import pytest

from senior_intern.fileops.path_policy import (
    ObjectKind,
    PathRole,
    PolicyDenial,
    evaluate_path_policy,
)
from senior_intern.fileops.win32_path_probe import Win32PathProbe
from senior_intern.fileops.win32_types import (
    FILE_ATTRIBUTE_OFFLINE,
    FILE_ATTRIBUTE_PINNED,
    FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS,
    FILE_ATTRIBUTE_RECALL_ON_OPEN,
    FILE_ATTRIBUTE_UNPINNED,
)
from tests.unit.fileops.win32_probe_test_support import (
    FakeWin32Backend,
    make_fixture,
    make_snapshot,
)


@pytest.mark.parametrize(
    ("path_text", "is_network"),
    [
        (r"\\server\share\file.pdf", True),
        ("//server/share/file.pdf", True),
        (r"\\?\UNC\server\share\file.pdf", True),
        (r"\\?\C:\local\file.pdf", False),
    ],
)
def test_unc_spelling_maps_network_fact(
    tmp_path: Path,
    path_text: str,
    *,
    is_network: bool,
) -> None:
    """UNC variants are distinct from extended local drive paths."""
    path = Path(path_text)
    snapshot = make_snapshot(
        path,
        PathRole.SOURCE_FILE,
        kind=ObjectKind.FILE,
        file_id=b"network-file-id",
    )
    probe = Win32PathProbe(
        source_root=tmp_path,
        backend=FakeWin32Backend({(path, PathRole.SOURCE_FILE): snapshot}),
    )

    fact = probe.inspect(path, PathRole.SOURCE_FILE)

    assert fact.is_network is is_network


def test_unc_final_handle_path_reaches_network_denial(tmp_path: Path) -> None:
    """A fixed drive spelling cannot hide a UNC handle result."""
    request, snapshots = make_fixture(tmp_path)
    source_key = (request.source_file, PathRole.SOURCE_FILE)
    snapshots[source_key] = snapshots[source_key].model_copy(
        update={"final_path": Path(r"\\server\share\document.pdf")}
    )

    decision = evaluate_path_policy(
        request,
        probe=Win32PathProbe(
            source_root=request.source_root,
            backend=FakeWin32Backend(snapshots),
        ),
    )

    assert decision.denial is PolicyDenial.NETWORK_LOCATION


@pytest.mark.parametrize(
    ("attribute", "placeholder"),
    [
        (FILE_ATTRIBUTE_OFFLINE, True),
        (FILE_ATTRIBUTE_RECALL_ON_OPEN, True),
        (FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS, True),
        (FILE_ATTRIBUTE_PINNED, False),
        (FILE_ATTRIBUTE_UNPINNED, False),
    ],
)
def test_all_cloud_attributes_are_denied_and_placeholder_is_precise(
    tmp_path: Path,
    attribute: int,
    *,
    placeholder: bool,
) -> None:
    """Every cloud marker denies; hydration markers also set placeholder."""
    request, snapshots = make_fixture(tmp_path)
    source_key = (request.source_file, PathRole.SOURCE_FILE)
    snapshots[source_key] = snapshots[source_key].model_copy(update={"attributes": attribute})
    probe = Win32PathProbe(
        source_root=request.source_root,
        backend=FakeWin32Backend(snapshots),
    )

    fact = probe.inspect(request.source_file, PathRole.SOURCE_FILE)
    decision = evaluate_path_policy(request, probe=probe)

    assert fact.is_cloud
    assert fact.is_placeholder is placeholder
    assert decision.denial is PolicyDenial.CLOUD_LOCATION


@pytest.mark.parametrize(
    ("role", "wrong_kind"),
    [
        (PathRole.SOURCE_ROOT, ObjectKind.FILE),
        (PathRole.SOURCE_FILE, ObjectKind.DIRECTORY),
        (PathRole.DESTINATION_DIRECTORY, ObjectKind.FILE),
    ],
)
def test_wrong_win32_role_kind_is_denied(
    tmp_path: Path,
    role: PathRole,
    wrong_kind: ObjectKind,
) -> None:
    """Every role requires its exact physical object kind."""
    request, snapshots = make_fixture(tmp_path)
    path = {
        PathRole.SOURCE_ROOT: request.source_root,
        PathRole.SOURCE_FILE: request.source_file,
        PathRole.DESTINATION_DIRECTORY: request.destination_directory,
    }[role]
    key = (path, role)
    snapshots[key] = snapshots[key].model_copy(update={"kind": wrong_kind})

    decision = evaluate_path_policy(
        request,
        probe=Win32PathProbe(
            source_root=request.source_root,
            backend=FakeWin32Backend(snapshots),
        ),
    )

    assert decision.denial is PolicyDenial.WRONG_TYPE
