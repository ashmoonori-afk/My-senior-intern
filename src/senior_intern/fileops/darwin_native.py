# Copyright (c) 2026 My Senior Intern contributors

"""Native Darwin no-follow snapshot orchestration."""

import errno
import sys
from pathlib import Path

from senior_intern.fileops.darwin_api import DarwinMetadataApi
from senior_intern.fileops.darwin_api_types import DarwinMetadataReader
from senior_intern.fileops.darwin_helper import DarwinUrlHelper
from senior_intern.fileops.darwin_open import open_role, path_has_symlink
from senior_intern.fileops.darwin_snapshot import (
    DarwinUrlInspector,
    inspect_opened,
    link_snapshot,
    missing_snapshot,
)
from senior_intern.fileops.darwin_types import (
    DarwinProbeBackendError,
    DarwinSnapshot,
)
from senior_intern.fileops.path_policy import PathRole


class NativeDarwinProbeBackend:
    """Collect coherent descriptor and URL identity evidence."""

    _api: DarwinMetadataReader | None
    _url_inspector: DarwinUrlInspector | None

    def __init__(
        self,
        *,
        api: DarwinMetadataReader | None = None,
        url_inspector: DarwinUrlInspector | None = None,
    ) -> None:
        """Accept injected readers or bind Darwin APIs lazily."""
        self._api = api
        self._url_inspector = url_inspector

    def snapshot(
        self,
        path: Path,
        role: PathRole,
        source_root: Path,
    ) -> DarwinSnapshot:
        """Inspect one role through retained no-follow descriptors."""
        api, url_inspector = self._readers()
        try:
            with open_role(path, role, source_root) as descriptors:
                return inspect_opened(
                    path,
                    source_root,
                    role,
                    descriptors,
                    (api, url_inspector),
                )
        except FileNotFoundError:
            return missing_snapshot(path, role)
        except OSError as error:
            if error.errno == errno.ELOOP or path_has_symlink(path):
                return link_snapshot(path, role)
            message = f"Darwin open failed with errno {error.errno}"
            raise DarwinProbeBackendError(message) from error

    def _readers(
        self,
    ) -> tuple[DarwinMetadataReader, DarwinUrlInspector]:
        if self._api is not None and self._url_inspector is not None:
            return self._api, self._url_inspector
        if sys.platform != "darwin":
            message = "Darwin path classification is unavailable"
            raise DarwinProbeBackendError(message)
        self._api = DarwinMetadataApi()
        self._url_inspector = DarwinUrlHelper()
        return self._api, self._url_inspector
