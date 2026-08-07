# Copyright (c) 2026 My Senior Intern contributors

"""SQLite connection boundary."""

import sqlite3
from pathlib import Path
from typing import cast

from senior_intern.core.migrations import apply_migrations, require_supported_schema


class DatabaseConfigurationError(RuntimeError):
    """SQLite could not enable a required durability setting."""


def _require_wal(connection: sqlite3.Connection) -> None:
    row = cast(
        "tuple[object, ...] | None",
        connection.execute("PRAGMA journal_mode = WAL").fetchone(),
    )
    if row is None:
        message = "SQLite did not report a journal mode"
        raise DatabaseConfigurationError(message)
    journal_mode = row[0]
    if not isinstance(journal_mode, str) or journal_mode.lower() != "wal":
        message = "SQLite WAL mode is required"
        raise DatabaseConfigurationError(message)


def open_database(path: Path) -> sqlite3.Connection:
    """Open and migrate a local application database."""
    connection = sqlite3.connect(path, timeout=5.0, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        require_supported_schema(connection)
        _ = connection.execute("PRAGMA foreign_keys = ON")
        _require_wal(connection)
        _ = connection.execute("PRAGMA synchronous = FULL")
        _ = connection.execute("PRAGMA busy_timeout = 5000")
        apply_migrations(connection)
    except BaseException:
        connection.close()
        raise
    return connection
