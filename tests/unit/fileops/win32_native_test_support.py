# Copyright (c) 2026 My Senior Intern contributors

"""Injected metadata reader for native Win32 orchestration tests."""

import ctypes
import ntpath
import struct
from ctypes import wintypes
from pathlib import Path
from typing import cast, override

from senior_intern.fileops.win32_api_types import (
    Win32HandleInfo,
    Win32MetadataReader,
    bind_function,
)
from senior_intern.fileops.win32_path_probe import DRIVE_FIXED
from senior_intern.fileops.win32_types import Win32ProbeBackendError

_GENERIC_WRITE = 0x40000000
_FILE_SHARE_ALL = 0x00000007
_OPEN_EXISTING = 3
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FSCTL_SET_REPARSE_POINT = 0x000900A4
_IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003


class FakeMetadataReader(Win32MetadataReader):
    """Scriptable no-follow metadata reader."""

    infos: dict[str, Win32HandleInfo]
    scripts: dict[str, list[Win32HandleInfo | None]]
    errors: set[str]
    calls: list[str]

    def __init__(self, infos: dict[Path, Win32HandleInfo]) -> None:
        """Index default metadata by case-insensitive Windows path."""
        self.infos = {_key(path): info for path, info in infos.items()}
        self.scripts = {}
        self.errors = set()
        self.calls = []

    @override
    def inspect(self, path: Path) -> Win32HandleInfo | None:
        """Return a scripted result, default result, or typed API error."""
        key = _key(path)
        self.calls.append(key)
        if key in self.errors:
            message = f"scripted metadata failure: {path}"
            raise Win32ProbeBackendError(message)
        scripted = self.scripts.get(key)
        if scripted:
            return scripted.pop(0)
        return self.infos.get(key)

    def script(
        self,
        path: Path,
        results: list[Win32HandleInfo | None],
    ) -> None:
        """Set ordered results for one path."""
        self.scripts[_key(path)] = results

    def fail(self, path: Path) -> None:
        """Make one path raise a typed metadata failure."""
        self.errors.add(_key(path))


def make_handle_info(
    path: Path,
    *,
    directory: bool,
) -> Win32HandleInfo:
    """Build one stable fixed-NTFS handle record."""
    identity = ntpath.normcase(str(path)).encode("utf-8").ljust(16, b"\0")[:16]
    return Win32HandleInfo(
        volume_serial=11,
        file_id=identity,
        attributes=0,
        reparse_tag=None,
        end_of_file=0 if directory else 12,
        number_of_links=1,
        delete_pending=False,
        directory=directory,
        final_path=path,
        drive_type=DRIVE_FIXED,
        filesystem_type="NTFS",
        volume_guid="volume-guid-11",
    )


def make_native_fixture() -> tuple[FakeMetadataReader, Path, Path]:
    """Build C:\\, source root, and one regular source file."""
    volume_root = Path("C:\\")
    source_root = Path(r"C:\source")
    source_file = Path(r"C:\source\document.pdf")
    reader = FakeMetadataReader(
        {
            volume_root: make_handle_info(volume_root, directory=True),
            source_root: make_handle_info(source_root, directory=True),
            source_file: make_handle_info(source_file, directory=False),
        }
    )
    return reader, source_root, source_file


def path_key(path: Path) -> str:
    """Expose normalization for test scripting."""
    return _key(path)


def create_junction(link: Path, target: Path) -> None:
    """Create a directory mount-point reparse entry without a shell."""
    link.mkdir()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = bind_function(
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
    device_control = bind_function(
        kernel32,
        "DeviceIoControl",
        [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.LPDWORD,
            wintypes.LPVOID,
        ],
        wintypes.BOOL,
    )
    close_handle = bind_function(
        kernel32,
        "CloseHandle",
        [wintypes.HANDLE],
        wintypes.BOOL,
    )
    raw_handle = create_file(
        str(link),
        _GENERIC_WRITE,
        _FILE_SHARE_ALL,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_OPEN_REPARSE_POINT | _FILE_FLAG_BACKUP_SEMANTICS,
        None,
    )
    handle = cast("int | None", raw_handle)
    invalid_handle = ctypes.c_void_p(-1).value
    if handle in {None, invalid_handle}:
        _raise_junction_error("CreateFileW")
    valid_handle = cast("int", handle)
    try:
        reparse_buffer = ctypes.create_string_buffer(_junction_data(target))
        returned = wintypes.DWORD()
        success = cast(
            "int",
            device_control(
                valid_handle,
                _FSCTL_SET_REPARSE_POINT,
                reparse_buffer,
                len(reparse_buffer) - 1,
                None,
                0,
                ctypes.byref(returned),
                None,
            ),
        )
        if not success:
            _raise_junction_error("DeviceIoControl")
    finally:
        _ = close_handle(valid_handle)


def _junction_data(target: Path) -> bytes:
    print_name = str(target.resolve()).encode("utf-16-le")
    substitute_name = ("\\??\\" + str(target.resolve())).encode("utf-16-le")
    path_buffer = substitute_name + b"\0\0" + print_name + b"\0\0"
    mount_data_length = 8 + len(path_buffer)
    return (
        struct.pack(
            "<IHHHHHH",
            _IO_REPARSE_TAG_MOUNT_POINT,
            mount_data_length,
            0,
            0,
            len(substitute_name),
            len(substitute_name) + 2,
            len(print_name),
        )
        + path_buffer
    )


def _raise_junction_error(api: str) -> None:
    error_code = ctypes.get_last_error()
    message = f"{api} failed with Win32 error {error_code}"
    raise RuntimeError(message)


def _key(path: Path) -> str:
    return ntpath.normcase(str(path))
