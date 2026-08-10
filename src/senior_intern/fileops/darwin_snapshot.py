# Copyright (c) 2026 My Senior Intern contributors

"""Compose coherent Darwin descriptor and URL snapshots."""

import stat
from pathlib import Path
from typing import Protocol

from senior_intern.fileops.darwin_api_types import (
    DarwinMetadataReader,
    DarwinObjectInfo,
)
from senior_intern.fileops.darwin_helper import DarwinUrlInfo
from senior_intern.fileops.darwin_types import (
    DarwinSnapshot,
    FileProviderState,
)
from senior_intern.fileops.path_policy import ObjectKind, PathRole

_SOURCE_CHAIN_MINIMUM = 2


class DarwinUrlInspector(Protocol):
    """Inspect Foundation and File Provider URL facts."""

    def inspect(self, file_descriptor: int) -> DarwinUrlInfo:
        """Return complete URL metadata bound to a retained descriptor."""
        ...


def inspect_opened(
    path: Path,
    role: PathRole,
    descriptors: tuple[int, ...],
    api: DarwinMetadataReader,
    url_inspector: DarwinUrlInspector,
) -> DarwinSnapshot:
    """Perform paired full sweeps over every retained descriptor."""
    before = tuple(api.inspect_fd(descriptor) for descriptor in descriptors)
    before_urls = tuple(url_inspector.inspect(descriptor) for descriptor in descriptors)
    after = tuple(api.inspect_fd(descriptor) for descriptor in descriptors)
    after_urls = tuple(url_inspector.inspect(descriptor) for descriptor in descriptors)
    target = before[-1]
    target_url = before_urls[-1]
    coherent = (
        before == after
        and before_urls == after_urls
        and all(
            _url_matches_object(info, url) for info, url in zip(before, before_urls, strict=True)
        )
        and all(_url_matches_object(info, url) for info, url in zip(after, after_urls, strict=True))
    )
    kind = _object_kind(target.st_mode)
    expected_kind = ObjectKind.FILE if role is PathRole.SOURCE_FILE else ObjectKind.DIRECTORY
    crosses_mount = any(
        (info.st_dev, info.fsid, info.mount_point)
        != (target.st_dev, target.fsid, target.mount_point)
        for info in before
    ) or any(_url_volume_identity(url) != _url_volume_identity(target_url) for url in before_urls)
    provider_states = {url.file_provider_state for url in before_urls}
    if FileProviderState.UNKNOWN in provider_states:
        provider_state = FileProviderState.UNKNOWN
    elif FileProviderState.MANAGED in provider_states:
        provider_state = FileProviderState.MANAGED
    else:
        provider_state = FileProviderState.NOT_MANAGED
    return DarwinSnapshot(
        path=path,
        role=role,
        exists=True,
        kind=kind,
        filesystem_type=target.filesystem_type,
        fsid=target.fsid,
        st_dev=target.st_dev,
        mount_point=target.mount_point,
        volume_identifier=target_url.volume_identifier,
        volume_uuid=target_url.volume_uuid,
        object_resource_id=target_url.object_resource_id,
        volume_resource_id=target_url.volume_resource_id,
        mount_flags=target.mount_flags,
        is_local=all(url.is_local for url in before_urls),
        is_link=False,
        no_follow_chain=True,
        within_source_root=_within_opened_root(role, before),
        is_ubiquitous=any(url.is_ubiquitous for url in before_urls),
        is_placeholder=any(url.is_placeholder for url in before_urls),
        file_provider_state=provider_state,
        crosses_mount=crosses_mount,
        identity_stable=(
            coherent
            and kind is expected_kind
            and target.st_nlink > 0
            and bool(target_url.object_resource_id)
        ),
        supports_persistent_ids=target.supports_persistent_ids,
        supports_rename_excl=target.supports_rename_excl,
        classification_complete=(coherent and provider_state is not FileProviderState.UNKNOWN),
    )


def missing_snapshot(path: Path, role: PathRole) -> DarwinSnapshot:
    """Return expected absence facts."""
    return _unsafe_snapshot(path, role, exists=False, is_link=False)


def link_snapshot(path: Path, role: PathRole) -> DarwinSnapshot:
    """Return direct-link denial facts."""
    return _unsafe_snapshot(path, role, exists=True, is_link=True)


def _url_volume_identity(info: DarwinUrlInfo) -> tuple[str, bytes]:
    return info.volume_uuid.casefold(), info.volume_resource_id


def _object_kind(mode: int) -> ObjectKind:
    if stat.S_ISDIR(mode):
        return ObjectKind.DIRECTORY
    if stat.S_ISREG(mode):
        return ObjectKind.FILE
    return ObjectKind.OTHER


def _within_opened_root(
    role: PathRole,
    infos: tuple[DarwinObjectInfo, ...],
) -> bool:
    return role is not PathRole.SOURCE_FILE or len(infos) >= _SOURCE_CHAIN_MINIMUM


def _url_matches_object(
    info: DarwinObjectInfo,
    url: DarwinUrlInfo,
) -> bool:
    return (
        url.path_st_dev,
        url.path_st_ino,
        url.path_st_mode,
    ) == (
        info.st_dev,
        info.st_ino,
        info.st_mode,
    )


def _unsafe_snapshot(
    path: Path,
    role: PathRole,
    *,
    exists: bool,
    is_link: bool,
) -> DarwinSnapshot:
    return DarwinSnapshot(
        path=path,
        role=role,
        exists=exists,
        kind=ObjectKind.OTHER,
        filesystem_type="",
        fsid=(0, 0),
        st_dev=0,
        mount_point="",
        volume_identifier="",
        volume_uuid="",
        object_resource_id=b"",
        volume_resource_id=b"",
        mount_flags=0,
        is_local=False,
        is_link=is_link,
        no_follow_chain=False,
        within_source_root=False,
        is_ubiquitous=False,
        is_placeholder=False,
        file_provider_state=FileProviderState.NOT_MANAGED,
        crosses_mount=False,
        identity_stable=False,
        supports_persistent_ids=False,
        supports_rename_excl=False,
        classification_complete=True,
    )
