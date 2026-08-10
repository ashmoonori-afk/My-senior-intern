# Copyright (c) 2026 My Senior Intern contributors

"""Typed Darwin libc structures and metadata records."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from typing import Protocol, final


@final
class Fsid(ctypes.Structure):
    """Darwin fsid_t."""

    _fields_ = [("value", ctypes.c_int32 * 2)]


@final
class StatFs(ctypes.Structure):
    """Darwin LP64 statfs."""

    _fields_ = [
        ("block_size", ctypes.c_uint32),
        ("io_size", ctypes.c_int32),
        ("blocks", ctypes.c_uint64),
        ("blocks_free", ctypes.c_uint64),
        ("blocks_available", ctypes.c_uint64),
        ("files", ctypes.c_uint64),
        ("files_free", ctypes.c_uint64),
        ("fsid", Fsid),
        ("owner", ctypes.c_uint32),
        ("fs_type_number", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("fs_subtype", ctypes.c_uint32),
        ("fs_type_name", ctypes.c_char * 16),
        ("mount_on_name", ctypes.c_char * 1024),
        ("mount_from_name", ctypes.c_char * 1024),
        ("extended_flags", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 7),
    ]


@final
class AttrList(ctypes.Structure):
    """Darwin attrlist."""

    _fields_ = [
        ("bitmap_count", ctypes.c_uint16),
        ("reserved", ctypes.c_uint16),
        ("common_attributes", ctypes.c_uint32),
        ("volume_attributes", ctypes.c_uint32),
        ("directory_attributes", ctypes.c_uint32),
        ("file_attributes", ctypes.c_uint32),
        ("fork_attributes", ctypes.c_uint32),
    ]


@final
class VolumeCapabilities(ctypes.Structure):
    """Darwin vol_capabilities_attr_t."""

    _fields_ = [
        ("capabilities", ctypes.c_uint32 * 4),
        ("valid", ctypes.c_uint32 * 4),
    ]


@final
class CapabilityBuffer(ctypes.Structure):
    """Length-prefixed fgetattrlist response."""

    _fields_ = [
        ("length", ctypes.c_uint32),
        ("value", VolumeCapabilities),
    ]


@dataclass(frozen=True)
class DarwinObjectInfo:
    """Stable object, filesystem, and capability metadata."""

    st_dev: int
    st_ino: int
    st_mode: int
    st_nlink: int
    st_size: int
    st_mtime_ns: int
    st_ctime_ns: int
    fsid: tuple[int, int]
    filesystem_type: str
    mount_flags: int
    mount_point: str
    supports_persistent_ids: bool
    supports_rename_excl: bool


class DarwinMetadataReader(Protocol):
    """Read stable metadata from one retained descriptor."""

    def inspect_fd(self, file_descriptor: int) -> DarwinObjectInfo:
        """Return one metadata snapshot."""
        ...
