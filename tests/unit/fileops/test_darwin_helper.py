# Copyright (c) 2026 My Senior Intern contributors

"""Objective-C Darwin helper loader validation tests."""

import ctypes
from pathlib import Path
from typing import cast, override

import pytest

from senior_intern.fileops.darwin_helper import (
    DarwinHelperFunction,
    DarwinUrlHelper,
    DarwinUrlInfoStruct,
)
from senior_intern.fileops.darwin_types import (
    DarwinProbeBackendError,
    FileProviderState,
)


class FakeDarwinHelperFunction(DarwinHelperFunction):
    """Populate one deterministic C helper response."""

    argtypes: list[object]
    restype: object
    result: int
    invalid_bool: bool
    invalid_length: bool

    def __init__(
        self,
        *,
        result: int = 0,
        invalid_bool: bool = False,
        invalid_length: bool = False,
    ) -> None:
        """Configure one helper outcome."""
        self.argtypes = []
        self.restype = ctypes.c_int
        self.result = result
        self.invalid_bool = invalid_bool
        self.invalid_length = invalid_length

    @override
    def __call__(self, *args: object) -> object:
        """Write a complete C response before returning."""
        raw_pointer = cast("ctypes.c_void_p", args[3])
        output_pointer = ctypes.cast(
            raw_pointer,
            ctypes.POINTER(DarwinUrlInfoStruct),
        )
        output = output_pointer.contents
        output.is_local = 2 if self.invalid_bool else 1
        output.is_ubiquitous = 0
        output.is_placeholder = 0
        output.file_provider_state = 0
        output.path_st_dev = 33
        output.path_st_ino = 44
        output.path_st_mode = 0o100600
        output.volume_uuid = b"volume-uuid"
        output.volume_identifier = b"volume-identifier"
        object_identity = b"object-resource"
        volume_identity = b"volume-resource"
        output.object_resource_length = 999 if self.invalid_length else len(object_identity)
        output.volume_resource_length = len(volume_identity)
        object_output = cast(
            "ctypes.Array[ctypes.c_ubyte]",
            output.object_resource_id,
        )
        volume_output = cast(
            "ctypes.Array[ctypes.c_ubyte]",
            output.volume_resource_id,
        )
        for index, value in enumerate(object_identity):
            object_output[index] = value
        for index, value in enumerate(volume_identity):
            volume_output[index] = value
        return self.result


def test_darwin_helper_parses_complete_response(tmp_path: Path) -> None:
    """A complete helper response preserves all identity evidence."""
    helper = DarwinUrlHelper(inspect_function=FakeDarwinHelperFunction())

    result = helper.inspect(42, tmp_path)

    assert result.is_local
    assert result.file_provider_state is FileProviderState.NOT_MANAGED
    assert result.path_st_dev == 33
    assert result.path_st_ino == 44
    assert result.object_resource_id == b"object-resource"
    assert result.volume_resource_id == b"volume-resource"


@pytest.mark.parametrize(
    "function",
    [
        FakeDarwinHelperFunction(result=-1),
        FakeDarwinHelperFunction(invalid_bool=True),
        FakeDarwinHelperFunction(invalid_length=True),
    ],
)
def test_darwin_helper_malformed_or_failed_response_denies(
    tmp_path: Path,
    function: FakeDarwinHelperFunction,
) -> None:
    """Native failures and malformed output never become path facts."""
    helper = DarwinUrlHelper(inspect_function=cast("DarwinHelperFunction", function))

    with pytest.raises(DarwinProbeBackendError):
        _ = helper.inspect(42, tmp_path)
