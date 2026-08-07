# Copyright (c) 2026 My Senior Intern contributors

"""Minimal typed Win32 metadata API wrapper."""

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path
from typing import cast

from senior_intern.fileops.win32_api_types import (
    CFunction,
    FileAttributeTagInfo,
    FileIdInfo,
    FileStandardInfo,
    Win32HandleInfo,
    bind_function,
)
from senior_intern.fileops.win32_types import Win32ProbeBackendError
from senior_intern.fileops.win32_volume import read_volume_details

_FILE_READ_ATTRIBUTES = 0x00000080
_FILE_SHARE_ALL = 0x00000001 | 0x00000002 | 0x00000004
_OPEN_EXISTING = 3
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_TYPE_DISK = 0x0001
_FILE_STANDARD_INFO_CLASS = 1
_FILE_ATTRIBUTE_TAG_INFO_CLASS = 9
_FILE_ID_INFO_CLASS = 18
_ERROR_FILE_NOT_FOUND = 2
_ERROR_PATH_NOT_FOUND = 3
_MAX_PATH_BUFFER = 32768


class Win32MetadataApi:
    """Read attributes from handles opened without following reparse points."""

    _create_file: CFunction
    _close_handle: CFunction
    _get_file_type: CFunction
    _get_file_information: CFunction
    _get_final_path: CFunction
    _get_volume_path: CFunction
    _get_drive_type: CFunction
    _get_volume_information: CFunction
    _get_volume_name: CFunction

    def __init__(self) -> None:
        """Bind kernel32 only on Windows."""
        if sys.platform != "win32":
            message = "Win32 metadata APIs are unavailable on this platform"
            raise Win32ProbeBackendError(message)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._create_file = bind_function(
            kernel32,
            "CreateFileW",
            [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.LPVOID,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.HANDLE,
            ],
            wintypes.HANDLE,
        )
        self._close_handle = bind_function(
            kernel32,
            "CloseHandle",
            [wintypes.HANDLE],
            wintypes.BOOL,
        )
        self._get_file_type = bind_function(
            kernel32,
            "GetFileType",
            [wintypes.HANDLE],
            wintypes.DWORD,
        )
        self._get_file_information = bind_function(
            kernel32,
            "GetFileInformationByHandleEx",
            [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD],
            wintypes.BOOL,
        )
        self._get_final_path = bind_function(
            kernel32,
            "GetFinalPathNameByHandleW",
            [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD],
            wintypes.DWORD,
        )
        self._get_volume_path = bind_function(
            kernel32,
            "GetVolumePathNameW",
            [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD],
            wintypes.BOOL,
        )
        self._get_drive_type = bind_function(
            kernel32,
            "GetDriveTypeW",
            [wintypes.LPCWSTR],
            wintypes.UINT,
        )
        self._get_volume_information = bind_function(
            kernel32,
            "GetVolumeInformationW",
            [
                wintypes.LPCWSTR,
                wintypes.LPWSTR,
                wintypes.DWORD,
                wintypes.LPDWORD,
                wintypes.LPDWORD,
                wintypes.LPDWORD,
                wintypes.LPWSTR,
                wintypes.DWORD,
            ],
            wintypes.BOOL,
        )
        self._get_volume_name = bind_function(
            kernel32,
            "GetVolumeNameForVolumeMountPointW",
            [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD],
            wintypes.BOOL,
        )

    def inspect(self, path: Path) -> Win32HandleInfo | None:
        """Open one object without following its final reparse point."""
        handle_value = self._create_file(
            str(path),
            _FILE_READ_ATTRIBUTES,
            _FILE_SHARE_ALL,
            None,
            _OPEN_EXISTING,
            _FILE_FLAG_OPEN_REPARSE_POINT | _FILE_FLAG_BACKUP_SEMANTICS,
            None,
        )
        handle = cast("int | None", handle_value)
        invalid_handle = ctypes.c_void_p(-1).value
        if handle in {None, invalid_handle}:
            error_code = ctypes.get_last_error()
            if error_code in {_ERROR_FILE_NOT_FOUND, _ERROR_PATH_NOT_FOUND}:
                return None
            _raise_api_error("CreateFileW", error_code)
        if handle is None:
            _raise_api_error("CreateFileW", ctypes.get_last_error())
        valid_handle = cast("int", handle)
        try:
            return self._inspect_open_handle(valid_handle, path)
        finally:
            closed = cast("int", self._close_handle(valid_handle))
            if not closed:
                _raise_api_error("CloseHandle", ctypes.get_last_error())

    def _inspect_open_handle(self, handle: int, path: Path) -> Win32HandleInfo:
        if cast("int", self._get_file_type(handle)) != _FILE_TYPE_DISK:
            _raise_api_error("GetFileType", ctypes.get_last_error())
        standard = FileStandardInfo()
        tag = FileAttributeTagInfo()
        identity = FileIdInfo()
        self._fill_info(handle, _FILE_STANDARD_INFO_CLASS, standard)
        self._fill_info(handle, _FILE_ATTRIBUTE_TAG_INFO_CLASS, tag)
        self._fill_info(handle, _FILE_ID_INFO_CLASS, identity)
        final_path = self._final_path(handle)
        drive_type, filesystem_type, volume_guid = read_volume_details(
            path,
            get_volume_path=self._get_volume_path,
            get_volume_information=self._get_volume_information,
            get_volume_name=self._get_volume_name,
            get_drive_type=self._get_drive_type,
        )
        reparse_tag = int(cast("int", tag.reparse_tag)) or None
        return Win32HandleInfo(
            volume_serial=int(cast("int", identity.volume_serial_number)),
            file_id=bytes(cast("bytes", identity.file_id)),
            attributes=int(cast("int", tag.file_attributes)),
            reparse_tag=reparse_tag,
            end_of_file=int(cast("int", standard.end_of_file)),
            number_of_links=int(cast("int", standard.number_of_links)),
            delete_pending=bool(cast("int", standard.delete_pending)),
            directory=bool(cast("int", standard.directory)),
            final_path=final_path,
            drive_type=drive_type,
            filesystem_type=filesystem_type,
            volume_guid=volume_guid,
        )

    def _fill_info(
        self,
        handle: int,
        information_class: int,
        target: ctypes.Structure,
    ) -> None:
        success = cast(
            "int",
            self._get_file_information(
                handle,
                information_class,
                ctypes.byref(target),
                ctypes.sizeof(target),
            ),
        )
        if not success:
            _raise_api_error(
                "GetFileInformationByHandleEx",
                ctypes.get_last_error(),
            )

    def _final_path(self, handle: int) -> Path:
        buffer = ctypes.create_unicode_buffer(_MAX_PATH_BUFFER)
        length = cast(
            "int",
            self._get_final_path(handle, buffer, len(buffer), 0),
        )
        if length == 0 or length >= len(buffer):
            _raise_api_error("GetFinalPathNameByHandleW", ctypes.get_last_error())
        return Path(cast("str", buffer.value))


def _raise_api_error(api: str, error_code: int) -> None:
    message = f"{api} failed with Win32 error {error_code}"
    raise Win32ProbeBackendError(message)
