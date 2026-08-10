# Copyright (c) 2026 My Senior Intern contributors

"""Real Darwin namespace ACL rejection test."""

import ctypes
import os
import shlex
import sys
from pathlib import Path
from typing import Protocol, cast

import pytest

from senior_intern.fileops.darwin_path_probe import DarwinPathProbe
from senior_intern.fileops.path_policy import (
    PathPolicyRequest,
    PathProbeError,
    PathRole,
    PolicyDenial,
    evaluate_path_policy,
)


class _CFunction(Protocol):
    restype: object

    def __call__(self, *args: object) -> object:
        """Invoke a fixed C function."""
        ...


def test_real_darwin_probe_rejects_nontrivial_acl(
    tmp_path: Path,
) -> None:
    """An extended ACL cannot make a namespace look exclusively writable."""
    if sys.platform != "darwin":
        probe = DarwinPathProbe(source_root=tmp_path)
        with pytest.raises(PathProbeError):
            _ = probe.inspect(tmp_path, PathRole.SOURCE_ROOT)
        return
    source_root = tmp_path / "source"
    destination = tmp_path / "destination"
    source_root.mkdir()
    destination.mkdir()
    source_file = source_root / "document.pdf"
    _ = source_file.write_bytes(b"acl fixture")
    _add_acl(source_root)
    request = PathPolicyRequest(
        source_root=source_root,
        source_file=source_file,
        destination_directory=destination,
    )

    decision = evaluate_path_policy(
        request,
        probe=DarwinPathProbe(source_root=source_root),
    )

    assert decision.denial is PolicyDenial.API_ERROR
    assert source_file.read_bytes() == b"acl fixture"


def _add_acl(path: Path) -> None:
    """Invoke the fixed macOS chmod ACL command through libc."""
    library = ctypes.CDLL(None)
    system = cast("_CFunction", cast("object", library.system))
    system.restype = ctypes.c_int
    command = " ".join(
        (
            "/bin/chmod",
            "+a",
            shlex.quote("everyone allow add_file,delete_child"),
            shlex.quote(str(path)),
        )
    )
    result = int(cast("int", system(os.fsencode(command))))
    assert result == 0
