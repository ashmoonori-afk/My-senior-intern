# Copyright (c) 2026 My Senior Intern contributors

"""Ordered SQLite schema migration orchestration."""

import sqlite3
from typing import Final, cast

from senior_intern.core.schema_v1 import MIGRATION_1
from senior_intern.core.schema_v2 import MIGRATION_2
from senior_intern.core.schema_v3 import MIGRATION_3

LATEST_SCHEMA_VERSION = 3

type Migration = tuple[int, tuple[str, ...]]

MIGRATIONS: Final[tuple[Migration, ...]] = (
    (1, MIGRATION_1),
    (2, MIGRATION_2),
    (3, MIGRATION_3),
)


class UnsupportedSchemaVersionError(RuntimeError):
    """The database was created by a newer application version."""


class InvalidMigrationStateError(RuntimeError):
    """The migration history contains an invalid value."""


def _schema_version(connection: sqlite3.Connection) -> int:
    table_row = cast(
        "tuple[object, ...] | None",
        connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'schema_migrations'
            """
        ).fetchone(),
    )
    if table_row is None:
        return 0

    version_row = cast(
        "tuple[object, ...] | None",
        connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone(),
    )
    raw_version = 0 if version_row is None else version_row[0]
    if not isinstance(raw_version, int):
        message = "schema migration version must be an integer"
        raise InvalidMigrationStateError(message)
    return raw_version


def require_supported_schema(connection: sqlite3.Connection) -> None:
    """Reject a newer schema without changing the database."""
    current_version = _schema_version(connection)
    if current_version > LATEST_SCHEMA_VERSION:
        message = (
            f"database uses newer schema {current_version}; "
            f"this application supports {LATEST_SCHEMA_VERSION}"
        )
        raise UnsupportedSchemaVersionError(message)


def apply_migrations(connection: sqlite3.Connection) -> None:
    """Apply every pending schema migration exactly once."""
    _ = connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY CHECK (version > 0),
            applied_at TEXT NOT NULL
        ) STRICT
        """
    )
    current_version = _schema_version(connection)
    require_supported_schema(connection)

    for version, statements in MIGRATIONS:
        if version <= current_version:
            continue
        _ = connection.execute("BEGIN IMMEDIATE")
        try:
            for statement in statements:
                _ = connection.execute(statement)
            _ = connection.execute(
                """
                INSERT INTO schema_migrations (version, applied_at)
                VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                """,
                (version,),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
