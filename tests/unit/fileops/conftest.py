# Copyright (c) 2026 My Senior Intern contributors

"""File-operation test fixtures."""

import sys
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest


@pytest.fixture
def darwin_trusted_tmp_path(
    tmp_path: Path,
) -> Iterator[Path]:
    """Use a private current-user namespace for real Darwin policy tests."""
    if sys.platform != "darwin":
        yield tmp_path
        return
    with TemporaryDirectory(
        prefix="senior-intern-",
        dir=Path.home(),
    ) as directory:
        yield Path(directory)
