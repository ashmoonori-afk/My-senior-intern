# Copyright (c) 2026 My Senior Intern contributors

"""Darwin object-kind policy tests."""

from pathlib import Path

import pytest

from senior_intern.fileops.darwin_path_probe import DarwinPathProbe
from senior_intern.fileops.path_policy import (
    ObjectKind,
    PathRole,
    PolicyDenial,
    evaluate_path_policy,
)
from tests.unit.fileops.darwin_probe_test_support import (
    FakeDarwinBackend,
    make_fixture,
)


@pytest.mark.parametrize(
    ("role", "kind"),
    [
        (PathRole.SOURCE_ROOT, ObjectKind.FILE),
        (PathRole.SOURCE_FILE, ObjectKind.DIRECTORY),
        (PathRole.DESTINATION_DIRECTORY, ObjectKind.FILE),
    ],
)
def test_darwin_wrong_object_kind_is_denied(
    tmp_path: Path,
    role: PathRole,
    kind: ObjectKind,
) -> None:
    """Darwin mode classification preserves role expectations."""
    request, snapshots = make_fixture(tmp_path)
    paths = {
        PathRole.SOURCE_ROOT: request.source_root,
        PathRole.SOURCE_FILE: request.source_file,
        PathRole.DESTINATION_DIRECTORY: request.destination_directory,
    }
    key = (paths[role], role)
    snapshots[key] = snapshots[key].model_copy(update={"kind": kind})

    decision = evaluate_path_policy(
        request,
        probe=DarwinPathProbe(
            source_root=request.source_root,
            backend=FakeDarwinBackend(snapshots),
        ),
    )

    assert decision.denial is PolicyDenial.WRONG_TYPE
