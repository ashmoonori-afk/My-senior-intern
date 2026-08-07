# Copyright (c) 2026 My Senior Intern contributors

"""Win32 volume metadata collection."""

import ctypes
from pathlib import Path
from typing import cast

from senior_intern.fileops.win32_api_types import CFunction
from senior_intern.fileops.win32_types import Win32ProbeBackendError

_MAX_PATH_BUFFER = 32768


def read_volume_details(
    path: Path,
    *,
    get_volume_path: CFunction,
    get_volume_information: CFunction,
    get_volume_name: CFunction,
    get_drive_type: CFunction,
) -> tuple[int, str, str]:
    """Return drive type, filesystem allowlist name, and volume GUID."""
    root_buffer = ctypes.create_unicode_buffer(_MAX_PATH_BUFFER)
    success = cast(
        "int",
        get_volume_path(str(path), root_buffer, len(root_buffer)),
    )
    if not success:
        _raise_volume_error("GetVolumePathNameW")
    root = cast("str", root_buffer.value)
    filesystem_buffer = ctypes.create_unicode_buffer(64)
    success = cast(
        "int",
        get_volume_information(
            root,
            None,
            0,
            None,
            None,
            None,
            filesystem_buffer,
            len(filesystem_buffer),
        ),
    )
    if not success:
        _raise_volume_error("GetVolumeInformationW")
    volume_name_buffer = ctypes.create_unicode_buffer(64)
    success = cast(
        "int",
        get_volume_name(
            root,
            volume_name_buffer,
            len(volume_name_buffer),
        ),
    )
    if not success:
        _raise_volume_error("GetVolumeNameForVolumeMountPointW")
    drive_type = cast("int", get_drive_type(root))
    return (
        drive_type,
        cast("str", filesystem_buffer.value),
        cast("str", volume_name_buffer.value),
    )


def _raise_volume_error(api: str) -> None:
    error_code = ctypes.get_last_error()
    message = f"{api} failed with Win32 error {error_code}"
    raise Win32ProbeBackendError(message)
