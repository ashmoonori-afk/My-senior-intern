# Copyright (c) 2026 My Senior Intern contributors

"""Fixed Darwin ctypes ABI layout tests."""

import ctypes

from senior_intern.fileops.darwin_api_types import (
    AttrList,
    CapabilityBuffer,
    Fsid,
    StatFs,
    VolumeCapabilities,
)
from senior_intern.fileops.darwin_helper import DarwinUrlInfoStruct


def test_darwin_lp64_statfs_layout_is_fixed_width() -> None:
    """The struct matches Darwin arm64 and x86_64 headers."""
    assert ctypes.sizeof(Fsid) == 8
    assert ctypes.sizeof(StatFs) == 2168
    assert StatFs.fsid.offset == 48
    assert StatFs.fs_type_name.offset == 72
    assert StatFs.mount_on_name.offset == 88
    assert StatFs.extended_flags.offset == 2136


def test_darwin_volume_capability_layout_is_exact() -> None:
    """fgetattrlist buffers preserve all validity and value words."""
    assert ctypes.sizeof(AttrList) == 24
    assert ctypes.sizeof(VolumeCapabilities) == 32
    assert ctypes.sizeof(CapabilityBuffer) == 36
    assert CapabilityBuffer.value.offset == 4


def test_objective_c_helper_struct_layout_matches_c_abi() -> None:
    """The Python loader and Objective-C helper share one fixed layout."""
    assert ctypes.sizeof(DarwinUrlInfoStruct) == 1584
    assert DarwinUrlInfoStruct.path_st_dev.offset == 16
    assert DarwinUrlInfoStruct.volume_uuid.offset == 44
    assert DarwinUrlInfoStruct.object_resource_id.offset == 556
