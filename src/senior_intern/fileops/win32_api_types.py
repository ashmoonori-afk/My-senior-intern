# Copyright (c) 2026 My Senior Intern contributors

"""Typed ctypes structures and binding helper for kernel32."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast, final

if TYPE_CHECKING:
    from pathlib import Path


class CFunction(Protocol):
    """One configured ctypes function."""

    argtypes: list[object]
    restype: object

    def __call__(self, *args: object) -> object:
        """Invoke the bound function."""
        ...


class Win32MetadataReader(Protocol):
    """Read one no-follow handle snapshot."""

    def inspect(self, path: Path) -> Win32HandleInfo | None:
        """Return metadata or expected absence."""
        ...


@final
class FileStandardInfo(ctypes.Structure):
    """FILE_STANDARD_INFO."""

    _fields_ = [
        ("allocation_size", ctypes.c_int64),
        ("end_of_file", ctypes.c_int64),
        ("number_of_links", wintypes.DWORD),
        ("delete_pending", wintypes.BOOLEAN),
        ("directory", wintypes.BOOLEAN),
    ]


@final
class FileAttributeTagInfo(ctypes.Structure):
    """FILE_ATTRIBUTE_TAG_INFO."""

    _fields_ = [
        ("file_attributes", wintypes.DWORD),
        ("reparse_tag", wintypes.DWORD),
    ]


@final
class FileIdInfo(ctypes.Structure):
    """FILE_ID_INFO."""

    _fields_ = [
        ("volume_serial_number", ctypes.c_uint64),
        ("file_id", ctypes.c_ubyte * 16),
    ]


@dataclass(frozen=True)
class Win32HandleInfo:
    """Metadata collected from one no-follow handle."""

    volume_serial: int
    file_id: bytes
    attributes: int
    reparse_tag: int | None
    end_of_file: int
    number_of_links: int
    delete_pending: bool
    directory: bool
    final_path: Path
    drive_type: int
    filesystem_type: str
    volume_guid: str


def bind_function(
    library: object,
    name: str,
    argument_types: list[object],
    result_type: object,
) -> CFunction:
    """Configure and return one kernel32 function."""
    function = cast("CFunction", getattr(library, name))
    function.argtypes = argument_types
    function.restype = result_type
    return function
