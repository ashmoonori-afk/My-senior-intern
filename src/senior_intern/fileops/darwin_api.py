# Copyright (c) 2026 My Senior Intern contributors

"""Minimal Darwin descriptor metadata API."""

import ctypes
import os
import sys
from typing import Protocol, cast

from senior_intern.fileops.darwin_api_types import (
    AttrList,
    CapabilityBuffer,
    DarwinObjectInfo,
    Fsid,
    StatFs,
    VolumeCapabilities,
)
from senior_intern.fileops.darwin_types import DarwinProbeBackendError

_ATTR_BIT_MAP_COUNT = 5
_ATTR_VOL_INFO = 0x80000000
_ATTR_VOL_CAPABILITIES = 0x00020000
_VOL_CAP_FMT_PERSISTENT_OBJECT_IDS = 0x00000001
_VOL_CAP_INT_RENAME_EXCL = 0x00080000
_FORMAT_INDEX, _INTERFACES_INDEX = 0, 1


class _CFunction(Protocol):
    argtypes: list[object]
    restype: object

    def __call__(self, *args: object) -> object:
        """Invoke one configured libc function."""
        ...


class DarwinMetadataApi:
    """Query descriptor-bound filesystem identity and capabilities."""

    _fstatfs: _CFunction
    _fgetattrlist: _CFunction

    def __init__(self) -> None:
        """Bind libSystem only on Darwin."""
        if sys.platform != "darwin":
            message = "Darwin metadata APIs are unavailable"
            raise DarwinProbeBackendError(message)
        library = ctypes.CDLL(
            "/usr/lib/libSystem.B.dylib",
            use_errno=True,
        )
        self._fstatfs = _bind(
            library,
            "fstatfs",
            [ctypes.c_int, ctypes.POINTER(StatFs)],
            ctypes.c_int,
        )
        self._fgetattrlist = _bind(
            library,
            "fgetattrlist",
            [
                ctypes.c_int,
                ctypes.POINTER(AttrList),
                ctypes.c_void_p,
                ctypes.c_size_t,
                ctypes.c_uint32,
            ],
            ctypes.c_int,
        )

    def inspect_fd(self, file_descriptor: int) -> DarwinObjectInfo:
        """Read metadata without reading file contents."""
        stat_result = os.fstat(file_descriptor)
        filesystem = StatFs()
        result = cast(
            "int",
            self._fstatfs(file_descriptor, ctypes.byref(filesystem)),
        )
        if result != 0:
            _raise_errno("fstatfs")
        capabilities = self._capabilities(file_descriptor)
        fsid_values = cast(
            "ctypes.Array[ctypes.c_int32]",
            cast("Fsid", filesystem.fsid).value,
        )
        fsid = (
            int(cast("int", fsid_values[0])),
            int(cast("int", fsid_values[1])),
        )
        filesystem_type = _decode_c_string(
            cast("bytes", filesystem.fs_type_name),
            "filesystem type",
        )
        return DarwinObjectInfo(
            st_dev=stat_result.st_dev,
            st_ino=stat_result.st_ino,
            st_mode=stat_result.st_mode,
            st_nlink=stat_result.st_nlink,
            st_size=stat_result.st_size,
            st_mtime_ns=stat_result.st_mtime_ns,
            st_ctime_ns=stat_result.st_ctime_ns,
            fsid=fsid,
            filesystem_type=filesystem_type,
            mount_flags=int(cast("int", filesystem.flags)),
            mount_point=_decode_c_string(
                cast("bytes", filesystem.mount_on_name),
                "mount point",
            ),
            supports_persistent_ids=capabilities[0],
            supports_rename_excl=capabilities[1],
        )

    def _capabilities(self, file_descriptor: int) -> tuple[bool, bool]:
        attributes = AttrList(
            bitmap_count=_ATTR_BIT_MAP_COUNT,
            reserved=0,
            common_attributes=0,
            volume_attributes=_ATTR_VOL_INFO | _ATTR_VOL_CAPABILITIES,
            directory_attributes=0,
            file_attributes=0,
            fork_attributes=0,
        )
        output = CapabilityBuffer()
        result = cast(
            "int",
            self._fgetattrlist(
                file_descriptor,
                ctypes.byref(attributes),
                ctypes.byref(output),
                ctypes.sizeof(output),
                0,
            ),
        )
        if result != 0:
            _raise_errno("fgetattrlist")
        response_length = int(cast("int", output.length))
        if response_length < ctypes.sizeof(CapabilityBuffer):
            message = "fgetattrlist returned an incomplete capability buffer"
            raise DarwinProbeBackendError(message)
        value = cast("VolumeCapabilities", output.value)
        valid = cast(
            "ctypes.Array[ctypes.c_uint32]",
            value.valid,
        )
        capabilities = cast(
            "ctypes.Array[ctypes.c_uint32]",
            value.capabilities,
        )
        persistent_valid = bool(
            int(cast("int", valid[_FORMAT_INDEX])) & _VOL_CAP_FMT_PERSISTENT_OBJECT_IDS
        )
        rename_valid = bool(int(cast("int", valid[_INTERFACES_INDEX])) & _VOL_CAP_INT_RENAME_EXCL)
        persistent = bool(
            int(cast("int", capabilities[_FORMAT_INDEX])) & _VOL_CAP_FMT_PERSISTENT_OBJECT_IDS
        )
        rename_exclusive = bool(
            int(cast("int", capabilities[_INTERFACES_INDEX])) & _VOL_CAP_INT_RENAME_EXCL
        )
        return (
            persistent_valid and persistent,
            rename_valid and rename_exclusive,
        )


def _bind(
    library: object,
    name: str,
    argument_types: list[object],
    result_type: object,
) -> _CFunction:
    function = cast("_CFunction", getattr(library, name))
    function.argtypes = argument_types
    function.restype = result_type
    return function


def _decode_c_string(value: object, name: str) -> str:
    raw = bytes(cast("bytes", value)).split(b"\0", maxsplit=1)[0]
    try:
        text = os.fsdecode(raw)
    except UnicodeError as error:
        message = f"Darwin returned invalid {name}"
        raise DarwinProbeBackendError(message) from error
    if not text:
        message = f"Darwin returned empty {name}"
        raise DarwinProbeBackendError(message)
    return text


def _raise_errno(api: str) -> None:
    error_code = ctypes.get_errno()
    message = f"{api} failed with errno {error_code}"
    raise DarwinProbeBackendError(message)
