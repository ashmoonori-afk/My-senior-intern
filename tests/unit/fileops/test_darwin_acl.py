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
    darwin_trusted_tmp_path: Path,
) -> None:
    """An extended ACL cannot make a namespace look exclusively writable."""
    if sys.platform != "darwin":
        probe = DarwinPathProbe(source_root=darwin_trusted_tmp_path)
        with pytest.raises(PathProbeError):
            _ = probe.inspect(
                darwin_trusted_tmp_path,
                PathRole.SOURCE_ROOT,
            )
        return
    source_root = darwin_trusted_tmp_path / "source"
    destination = darwin_trusted_tmp_path / "destination"
    source_root.mkdir()
    destination.mkdir()
    source_file = source_root / "document.pdf"
    _ = source_file.write_bytes(b"acl fixture")
    _add_acl(
        source_root,
        "everyone allow add_file,delete_child",
    )
    request = PathPolicyRequest(
        source_root=source_root,
        source_file=source_file,
        destination_directory=destination,
    )

    decision = evaluate_path_policy(
        request,
        probe=DarwinPathProbe(source_root=source_root),
    )
    _clear_acl(source_root)

    assert decision.denial is PolicyDenial.API_ERROR
    assert source_file.read_bytes() == b"acl fixture"


def test_real_darwin_probe_accepts_deny_only_acl(
    darwin_trusted_tmp_path: Path,
) -> None:
    """A deny-only system-style ACL does not create a mutation principal."""
    if sys.platform != "darwin":
        return
    source_root = darwin_trusted_tmp_path / "deny-source"
    destination = darwin_trusted_tmp_path / "deny-destination"
    source_root.mkdir()
    destination.mkdir()
    source_file = source_root / "document.pdf"
    _ = source_file.write_bytes(b"deny acl fixture")
    _add_acl(source_root, "everyone deny delete")
    request = PathPolicyRequest(
        source_root=source_root,
        source_file=source_file,
        destination_directory=destination,
    )

    decision = evaluate_path_policy(
        request,
        probe=DarwinPathProbe(source_root=source_root),
    )
    _clear_acl(source_root)

    assert decision.allowed


def _add_acl(path: Path, entry: str) -> None:
    """Invoke the fixed macOS chmod ACL command through libc."""
    library = ctypes.CDLL(None)
    system = cast("_CFunction", cast("object", library.system))
    system.restype = ctypes.c_int
    command = " ".join(
        (
            "/bin/chmod",
            "+a",
            shlex.quote(entry),
            shlex.quote(str(path)),
        )
    )
    result = int(cast("int", system(os.fsencode(command))))
    assert result == 0


def _clear_acl(path: Path) -> None:
    """Remove the test ACL before temporary-directory cleanup."""
    library = ctypes.CDLL(None)
    system = cast("_CFunction", cast("object", library.system))
    system.restype = ctypes.c_int
    command = f"/bin/chmod -N {shlex.quote(str(path))}"
    result = int(cast("int", system(os.fsencode(command))))
    assert result == 0
