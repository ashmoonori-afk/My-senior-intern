# Copyright (c) 2026 My Senior Intern contributors

"""Native Win32 no-follow snapshot orchestration."""

import ntpath
import sys
from pathlib import Path, PureWindowsPath
from typing import Final

from senior_intern.fileops.path_policy import ObjectKind, PathRole
from senior_intern.fileops.win32_api import Win32MetadataApi
from senior_intern.fileops.win32_api_types import (
    Win32HandleInfo,
    Win32MetadataReader,
)
from senior_intern.fileops.win32_types import (
    CLOUD_ATTRIBUTE_MASK,
    DRIVE_FIXED,
    FILE_ATTRIBUTE_REPARSE_POINT,
    Win32ProbeBackendError,
    Win32Snapshot,
)

_SUPPORTED_FILESYSTEMS: Final = frozenset({"ntfs", "refs"})


class NativeWin32ProbeBackend:
    """Collect stable handle identities and no-follow ancestry evidence."""

    _api: Win32MetadataReader | None

    def __init__(self, *, api: Win32MetadataReader | None = None) -> None:
        """Accept an injected reader or bind kernel32 lazily."""
        self._api = api

    def snapshot(
        self,
        path: Path,
        role: PathRole,
        source_root: Path,
    ) -> Win32Snapshot:
        """Inspect one path without following reparse-point handles."""
        api = self._api
        if api is None:
            if sys.platform != "win32":
                message = "Win32 path classification is unavailable"
                raise Win32ProbeBackendError(message)
            api = Win32MetadataApi()
            self._api = api
        target, target_stable = _stable_info(api, path)
        if target is None:
            return _missing_snapshot(path, role)
        root, root_stable = _stable_info(api, source_root)
        if root is None:
            message = "source root disappeared during classification"
            raise Win32ProbeBackendError(message)
        observations = [(path, target), (source_root, root)]
        chain_safe = True
        chain_stable = True
        crosses_mount = False
        ancestor_attributes = 0
        for ancestor in _ancestor_paths(path):
            info, stable = _stable_info(api, ancestor)
            if info is None:
                message = "path ancestor disappeared during classification"
                raise Win32ProbeBackendError(message)
            observations.append((ancestor, info))
            chain_safe = chain_safe and not _is_reparse(info)
            chain_stable = chain_stable and stable
            crosses_mount = crosses_mount or (
                info.volume_serial,
                info.volume_guid.casefold(),
            ) != (
                target.volume_serial,
                target.volume_guid.casefold(),
            )
            ancestor_attributes |= info.attributes & CLOUD_ATTRIBUTE_MASK
        filesystem_type = target.filesystem_type.casefold()
        within_source_root = (
            _is_within(target.final_path, root.final_path) if role is PathRole.SOURCE_FILE else True
        )
        coherent = _coherent_snapshot(api, observations)
        identity_stable = (
            target_stable
            and root_stable
            and chain_stable
            and coherent
            and bool(target.file_id)
            and bool(target.volume_guid)
            and target.number_of_links > 0
            and not target.delete_pending
        )
        return Win32Snapshot(
            path=path,
            role=role,
            exists=True,
            kind=(ObjectKind.DIRECTORY if target.directory else ObjectKind.FILE),
            filesystem_type=filesystem_type,
            drive_type=target.drive_type,
            volume_serial=target.volume_serial,
            volume_guid=target.volume_guid,
            file_id=target.file_id,
            attributes=target.attributes,
            ancestor_attributes=ancestor_attributes,
            reparse_tag=target.reparse_tag,
            final_path=target.final_path,
            within_source_root=within_source_root,
            no_follow_chain=chain_safe,
            crosses_mount=crosses_mount,
            identity_stable=identity_stable,
            supports_no_replace=(
                target.drive_type == DRIVE_FIXED and filesystem_type in _SUPPORTED_FILESYSTEMS
            ),
            classification_complete=coherent,
        )


def _stable_info(
    api: Win32MetadataReader,
    path: Path,
) -> tuple[Win32HandleInfo | None, bool]:
    first = api.inspect(path)
    second = api.inspect(path)
    return first, first is not None and first == second


def _coherent_snapshot(
    api: Win32MetadataReader,
    observations: list[tuple[Path, Win32HandleInfo]],
) -> bool:
    unique = {ntpath.normcase(str(path)): (path, info) for path, info in observations}
    return all(api.inspect(path) == info for path, info in unique.values())


def _ancestor_paths(path: Path) -> tuple[Path, ...]:
    absolute = PureWindowsPath(ntpath.abspath(str(path)))
    anchor = absolute.anchor
    if not anchor:
        message = "Win32 path must have an absolute anchor"
        raise Win32ProbeBackendError(message)
    current = PureWindowsPath(anchor)
    ancestors = [Path(str(current))]
    anchor_parts = len(current.parts)
    for component in absolute.parts[anchor_parts:]:
        current /= component
        ancestors.append(Path(str(current)))
    return tuple(ancestors)


def _is_reparse(info: Win32HandleInfo) -> bool:
    return info.reparse_tag is not None or bool(info.attributes & FILE_ATTRIBUTE_REPARSE_POINT)


def _is_within(path: Path, root: Path) -> bool:
    normalized_path = ntpath.normcase(_without_extended_prefix(str(path)))
    normalized_root = ntpath.normcase(_without_extended_prefix(str(root)))
    try:
        return ntpath.commonpath((normalized_path, normalized_root)) == normalized_root
    except ValueError:
        return False


def _without_extended_prefix(path: str) -> str:
    folded = path.casefold()
    if folded.startswith("\\\\?\\unc\\"):
        return "\\\\" + path[8:]
    if folded.startswith("\\\\?\\"):
        return path[4:]
    return path


def _missing_snapshot(path: Path, role: PathRole) -> Win32Snapshot:
    return Win32Snapshot(
        path=path,
        role=role,
        exists=False,
        kind=ObjectKind.OTHER,
        filesystem_type="",
        drive_type=0,
        volume_serial=0,
        volume_guid="",
        file_id=b"",
        attributes=0,
        ancestor_attributes=0,
        reparse_tag=None,
        final_path=path,
        within_source_root=False,
        no_follow_chain=False,
        crosses_mount=False,
        identity_stable=False,
        supports_no_replace=False,
        classification_complete=True,
    )
