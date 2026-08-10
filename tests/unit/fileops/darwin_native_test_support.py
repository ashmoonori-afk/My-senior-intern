# Copyright (c) 2026 My Senior Intern contributors

"""Injected readers for Darwin snapshot composition tests."""

from pathlib import Path
from typing import override

from senior_intern.fileops.darwin_api_types import (
    DarwinMetadataReader,
    DarwinObjectInfo,
)
from senior_intern.fileops.darwin_helper import DarwinUrlInfo
from senior_intern.fileops.darwin_snapshot import (
    DarwinUrlInspector,
    inspect_opened,
)
from senior_intern.fileops.darwin_types import (
    MNT_LOCAL,
    DarwinSnapshot,
    FileProviderState,
)
from senior_intern.fileops.path_policy import PathRole

_ROOT_FD = 10
_FILE_FD = 11


class FakeDarwinMetadataReader(DarwinMetadataReader):
    """Return ordered descriptor snapshots."""

    results: dict[int, list[DarwinObjectInfo]]

    def __init__(
        self,
        results: dict[int, list[DarwinObjectInfo]],
    ) -> None:
        """Store paired results per descriptor."""
        self.results = results

    @override
    def inspect_fd(self, file_descriptor: int) -> DarwinObjectInfo:
        """Pop the next descriptor result."""
        return self.results[file_descriptor].pop(0)


class FakeDarwinUrlInspector(DarwinUrlInspector):
    """Return ordered URL snapshots."""

    results: dict[int, list[DarwinUrlInfo]]

    def __init__(
        self,
        results: dict[int, list[DarwinUrlInfo]],
    ) -> None:
        """Store paired results per path."""
        self.results = results

    @override
    def inspect(
        self,
        file_descriptor: int,
        path: Path,
    ) -> DarwinUrlInfo:
        """Pop the next URL result."""
        del path
        return self.results[file_descriptor].pop(0)


def make_object_info(
    path: Path,
) -> DarwinObjectInfo:
    """Build stable APFS descriptor metadata."""
    path_stat = path.stat()
    return DarwinObjectInfo(
        st_dev=path_stat.st_dev,
        st_ino=path_stat.st_ino,
        st_mode=path_stat.st_mode,
        st_nlink=path_stat.st_nlink,
        st_size=path_stat.st_size,
        st_mtime_ns=path_stat.st_mtime_ns,
        st_ctime_ns=path_stat.st_ctime_ns,
        fsid=(11, 22),
        filesystem_type="apfs",
        mount_flags=MNT_LOCAL,
        mount_point="/",
        supports_persistent_ids=True,
        supports_rename_excl=True,
    )


def make_url_info(
    *,
    object_id: bytes,
    path_info: DarwinObjectInfo,
) -> DarwinUrlInfo:
    """Build local non-File-Provider URL metadata."""
    return DarwinUrlInfo(
        is_local=True,
        is_ubiquitous=False,
        is_placeholder=False,
        file_provider_state=FileProviderState.NOT_MANAGED,
        path_st_dev=path_info.st_dev,
        path_st_ino=path_info.st_ino,
        path_st_mode=path_info.st_mode,
        volume_uuid="01234567-89AB-CDEF-0123-456789ABCDEF",
        volume_identifier="volume-identifier",
        object_resource_id=object_id,
        volume_resource_id=b"volume-resource",
    )


def make_native_fixture(
    tmp_path: Path,
) -> tuple[
    Path,
    Path,
    DarwinObjectInfo,
    DarwinObjectInfo,
    DarwinUrlInfo,
    DarwinUrlInfo,
]:
    """Build root/file descriptor and URL metadata."""
    source_root = tmp_path / "source"
    source_file = source_root / "document.pdf"
    source_root.mkdir()
    _ = source_file.write_bytes(b"darwin native")
    root_info = make_object_info(source_root)
    file_info = make_object_info(source_file)
    root_url = make_url_info(
        object_id=b"root-resource",
        path_info=root_info,
    )
    file_url = make_url_info(
        object_id=b"file-resource",
        path_info=file_info,
    )
    return (
        source_root,
        source_file,
        root_info,
        file_info,
        root_url,
        file_url,
    )


def inspect_native_fixture(
    fixture: tuple[
        Path,
        Path,
        DarwinObjectInfo,
        DarwinObjectInfo,
        DarwinUrlInfo,
        DarwinUrlInfo,
    ],
    *,
    root_infos: list[DarwinObjectInfo] | None = None,
    file_infos: list[DarwinObjectInfo] | None = None,
    root_urls: list[DarwinUrlInfo] | None = None,
    file_urls: list[DarwinUrlInfo] | None = None,
) -> DarwinSnapshot:
    """Compose one source-file snapshot from injected paired sweeps."""
    source_root, source_file, root_info, file_info, root_url, file_url = fixture
    metadata = FakeDarwinMetadataReader(
        {
            _ROOT_FD: list(root_infos or [root_info, root_info]),
            _FILE_FD: list(file_infos or [file_info, file_info]),
        }
    )
    urls = FakeDarwinUrlInspector(
        {
            _ROOT_FD: list(root_urls or [root_url, root_url]),
            _FILE_FD: list(file_urls or [file_url, file_url]),
        }
    )
    return inspect_opened(
        source_file,
        source_root,
        PathRole.SOURCE_FILE,
        (_ROOT_FD, _FILE_FD),
        (metadata, urls),
    )
