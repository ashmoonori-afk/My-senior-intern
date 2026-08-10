# Copyright (c) 2026 My Senior Intern contributors

"""Typed loader for the bundled Objective-C Darwin URL helper."""

import ctypes
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast, final

from senior_intern.fileops.darwin_types import (
    DarwinProbeBackendError,
    FileProviderState,
)

_ID_CAPACITY = 512
_TEXT_CAPACITY = 256
_DEFAULT_TIMEOUT_MS = 250


class DarwinHelperFunction(Protocol):
    """Callable C ABI surface for URL inspection."""

    argtypes: list[object]
    restype: object

    def __call__(self, *args: object) -> object:
        """Invoke one configured C function."""
        ...


@final
class DarwinUrlInfoStruct(ctypes.Structure):
    """Fixed C ABI shared with the Objective-C helper."""

    _fields_ = [
        ("is_local", ctypes.c_int32),
        ("is_ubiquitous", ctypes.c_int32),
        ("is_placeholder", ctypes.c_int32),
        ("file_provider_state", ctypes.c_int32),
        ("path_st_dev", ctypes.c_uint64),
        ("path_st_ino", ctypes.c_uint64),
        ("path_st_mode", ctypes.c_uint32),
        ("object_resource_length", ctypes.c_uint32),
        ("volume_resource_length", ctypes.c_uint32),
        ("volume_uuid", ctypes.c_char * _TEXT_CAPACITY),
        ("volume_identifier", ctypes.c_char * _TEXT_CAPACITY),
        ("object_resource_id", ctypes.c_ubyte * _ID_CAPACITY),
        ("volume_resource_id", ctypes.c_ubyte * _ID_CAPACITY),
    ]


@dataclass(frozen=True)
class DarwinUrlInfo:
    """Foundation and File Provider facts for one URL."""

    is_local: bool
    is_ubiquitous: bool
    is_placeholder: bool
    file_provider_state: FileProviderState
    path_st_dev: int
    path_st_ino: int
    path_st_mode: int
    volume_uuid: str
    volume_identifier: str
    object_resource_id: bytes
    volume_resource_id: bytes


class DarwinUrlHelper:
    """Call the bundled universal2 Objective-C helper."""

    _inspect: DarwinHelperFunction
    _timeout_ms: int

    def __init__(
        self,
        *,
        library_path: Path | None = None,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
        inspect_function: DarwinHelperFunction | None = None,
    ) -> None:
        """Load the helper and bind its fixed C ABI."""
        if inspect_function is not None:
            self._inspect = inspect_function
            self._timeout_ms = timeout_ms
            return
        if sys.platform != "darwin":
            message = "Darwin URL helper is unavailable"
            raise DarwinProbeBackendError(message)
        helper_path = (
            Path(__file__).parent / "native" / "libomt_darwin_probe.dylib"
            if library_path is None
            else library_path
        )
        if not helper_path.is_file():
            message = f"Darwin URL helper is missing: {helper_path}"
            raise DarwinProbeBackendError(message)
        library = ctypes.CDLL(str(helper_path), use_errno=True)
        function = cast(
            "DarwinHelperFunction",
            cast("object", library.omt_darwin_url_inspect),
        )
        function.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.POINTER(DarwinUrlInfoStruct),
        ]
        function.restype = ctypes.c_int
        self._inspect = function
        self._timeout_ms = timeout_ms

    def inspect(
        self,
        file_descriptor: int,
        path: Path,
    ) -> DarwinUrlInfo:
        """Read identity-bound URL metadata in a trusted namespace."""
        output = DarwinUrlInfoStruct()
        result = cast(
            "int",
            self._inspect(
                file_descriptor,
                os.fsencode(path),
                self._timeout_ms,
                ctypes.byref(output),
            ),
        )
        if result != 0:
            message = f"Darwin identity-bound URL inspection failed at native stage {result}"
            raise DarwinProbeBackendError(message)
        state_value = int(cast("int", output.file_provider_state))
        try:
            provider_state = FileProviderState(
                {
                    -1: FileProviderState.UNKNOWN,
                    0: FileProviderState.NOT_MANAGED,
                    1: FileProviderState.MANAGED,
                }[state_value]
            )
        except KeyError as error:
            message = "Darwin helper returned invalid provider state"
            raise DarwinProbeBackendError(message) from error
        return DarwinUrlInfo(
            is_local=_binary_bool(cast("int", output.is_local), "is_local"),
            is_ubiquitous=_binary_bool(
                cast("int", output.is_ubiquitous),
                "is_ubiquitous",
            ),
            is_placeholder=_binary_bool(
                cast("int", output.is_placeholder),
                "is_placeholder",
            ),
            file_provider_state=provider_state,
            path_st_dev=int(cast("int", output.path_st_dev)),
            path_st_ino=int(cast("int", output.path_st_ino)),
            path_st_mode=int(cast("int", output.path_st_mode)),
            volume_uuid=_decode_text(
                cast("bytes", output.volume_uuid),
                "volume_uuid",
            ),
            volume_identifier=_decode_text(
                cast("bytes", output.volume_identifier),
                "volume_identifier",
            ),
            object_resource_id=_copy_identity(
                cast("bytes", output.object_resource_id),
                cast("int", output.object_resource_length),
                "object_resource_id",
            ),
            volume_resource_id=_copy_identity(
                cast("bytes", output.volume_resource_id),
                cast("int", output.volume_resource_length),
                "volume_resource_id",
            ),
        )


def _binary_bool(value: object, name: str) -> bool:
    numeric = int(cast("int", value))
    if numeric not in {0, 1}:
        message = f"Darwin helper returned invalid {name}"
        raise DarwinProbeBackendError(message)
    return bool(numeric)


def _decode_text(value: object, name: str) -> str:
    raw = bytes(cast("bytes", value)).split(b"\0", maxsplit=1)[0]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        message = f"Darwin helper returned invalid {name}"
        raise DarwinProbeBackendError(message) from error
    if not text:
        message = f"Darwin helper returned empty {name}"
        raise DarwinProbeBackendError(message)
    return text


def _copy_identity(
    value: object,
    length_value: object,
    name: str,
) -> bytes:
    length = int(cast("int", length_value))
    if length <= 0 or length > _ID_CAPACITY:
        message = f"Darwin helper returned invalid {name} length"
        raise DarwinProbeBackendError(message)
    return bytes(cast("bytes", value))[:length]
