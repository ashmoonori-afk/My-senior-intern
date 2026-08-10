# Copyright (c) 2026 My Senior Intern contributors

"""Retained no-follow descriptor traversal for Darwin."""

import errno
import os
import stat
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from senior_intern.fileops.darwin_types import DarwinProbeBackendError
from senior_intern.fileops.path_policy import PathRole

_O_NONBLOCK = 0x00000004
_O_EVTONLY = 0x00008000
_O_NOFOLLOW = 0x00000100
_O_CLOEXEC = 0x01000000
_O_DIRECTORY = 0x00100000
_O_NOFOLLOW_ANY = 0x20000000
_O_RESOLVE_BENEATH = 0x00001000
_MAX_COMPONENTS = 32


@contextmanager
def open_role(
    path: Path,
    role: PathRole,
    source_root: Path,
) -> Generator[tuple[int, ...], None, None]:
    """Open one role and retain every source-relative descriptor."""
    descriptors: list[int] = []
    try:
        if role is not PathRole.SOURCE_FILE:
            descriptors.append(os.open(path, _absolute_flags()))
        else:
            relative = _source_components(path, source_root)
            root_descriptor = os.open(source_root, _directory_flags())
            descriptors.append(root_descriptor)
            current_descriptor = root_descriptor
            for component in relative[:-1]:
                current_descriptor = _open_at(
                    current_descriptor,
                    component,
                    _intermediate_flags(),
                )
                descriptors.append(current_descriptor)
            descriptors.append(
                _open_at(
                    current_descriptor,
                    relative[-1],
                    _file_flags(),
                )
            )
        yield tuple(descriptors)
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _source_components(path: Path, source_root: Path) -> tuple[str, ...]:
    try:
        relative = path.relative_to(source_root)
    except ValueError as error:
        message = "Darwin source escapes its root"
        raise DarwinProbeBackendError(message) from error
    components = tuple(relative.parts)
    invalid = (
        not components
        or len(components) > _MAX_COMPONENTS
        or any(component in {"", ".", ".."} or "/" in component for component in components)
    )
    if invalid:
        message = "Darwin source components are invalid"
        raise DarwinProbeBackendError(message)
    return components


def _open_at(
    directory_descriptor: int,
    component: str,
    flags: int,
) -> int:
    try:
        return os.open(
            component,
            flags | _O_RESOLVE_BENEATH,
            dir_fd=directory_descriptor,
        )
    except OSError as error:
        if error.errno != errno.EINVAL:
            raise
    return os.open(component, flags, dir_fd=directory_descriptor)


def _directory_flags() -> int:
    return _O_EVTONLY | _O_CLOEXEC | _O_NOFOLLOW_ANY | _O_DIRECTORY


def _absolute_flags() -> int:
    return _O_EVTONLY | _O_CLOEXEC | _O_NOFOLLOW_ANY


def _intermediate_flags() -> int:
    return _O_EVTONLY | _O_CLOEXEC | _O_NOFOLLOW | _O_DIRECTORY


def _file_flags() -> int:
    return _O_EVTONLY | _O_CLOEXEC | _O_NOFOLLOW | _O_NONBLOCK


def path_has_symlink(path: Path) -> bool:
    """Best-effort denial-only classification of a failed open."""
    if not path.is_absolute():
        return False
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        try:
            if stat.S_ISLNK(os.lstat(current).st_mode):
                return True
        except OSError:
            return False
    return False
