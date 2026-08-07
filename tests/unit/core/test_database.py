# Copyright (c) 2026 My Senior Intern contributors

"""SQLite connection and migration contract tests."""

import sqlite3
from pathlib import Path
from typing import cast

import pytest

from senior_intern.core.database import open_database
from senior_intern.core.migrations import (
    LATEST_SCHEMA_VERSION,
    UnsupportedSchemaVersionError,
    apply_migrations,
)

REQUIRED_DOCUMENT_COLUMNS = {
    "document_id",
    "current_path",
    "file_hash",
    "file_size",
    "file_type",
    "created_at",
    "modified_at",
    "discovered_at",
    "last_analyzed_at",
    "extraction_status",
    "classification_status",
    "proposed_category_id",
    "final_category_id",
    "confidence",
    "move_transaction_id",
    "security_flags_json",
    "review_status",
}


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = cast(
        "list[tuple[object, ...]]",
        connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall(),
    )
    names: set[str] = set()
    for row in rows:
        value = row[0]
        assert isinstance(value, str)
        names.add(value)
    return names


def _column_names(connection: sqlite3.Connection, table: str) -> set[str]:
    rows = cast(
        "list[tuple[object, ...]]",
        connection.execute(f"PRAGMA table_info({table})").fetchall(),
    )
    names: set[str] = set()
    for row in rows:
        value = row[1]
        assert isinstance(value, str)
        names.add(value)
    return names


def _open_and_close(path: Path) -> None:
    connection = open_database(path)
    connection.close()


def _journal_mode(path: Path) -> str:
    connection = sqlite3.connect(path)
    try:
        row = cast(
            "tuple[object, ...] | None",
            connection.execute("PRAGMA journal_mode").fetchone(),
        )
        assert row is not None
        mode = row[0]
        assert isinstance(mode, str)
        return mode
    finally:
        connection.close()


def test_open_database_applies_safety_pragmas(tmp_path: Path) -> None:
    """Every connection uses durable local safety settings."""
    connection = open_database(tmp_path / "senior-intern.db")
    try:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5_000
    finally:
        connection.close()


def test_initial_migration_creates_local_index_contract(tmp_path: Path) -> None:
    """The first schema contains traceable documents, paths, relations, and moves."""
    connection = open_database(tmp_path / "senior-intern.db")
    try:
        assert {
            "schema_migrations",
            "documents",
            "document_paths",
            "document_rule_matches",
            "document_relations",
            "move_transactions",
        } <= _table_names(connection)
        assert _column_names(connection, "documents") >= REQUIRED_DOCUMENT_COLUMNS

        with pytest.raises(sqlite3.IntegrityError):
            _ = connection.execute(
                """
                INSERT INTO move_transactions (
                    transaction_id,
                    document_id,
                    source_path,
                    destination_path,
                    state,
                    planned_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "txn_01HZX7F5K2",
                    "doc_01HZX7F5K2",
                    "source.docx",
                    "destination.docx",
                    "deleted",
                    "2026-08-07T00:00:00Z",
                ),
            )
    finally:
        connection.close()


def test_migrations_are_idempotent(tmp_path: Path) -> None:
    """Reapplying migrations never duplicates or rewrites migration history."""
    connection = open_database(tmp_path / "senior-intern.db")
    try:
        apply_migrations(connection)
        apply_migrations(connection)

        rows = cast(
            "list[tuple[object, ...]]",
            connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall(),
        )
        versions: list[int] = []
        for row in rows:
            value = row[0]
            assert isinstance(value, int)
            versions.append(value)
        assert versions == list(range(1, LATEST_SCHEMA_VERSION + 1))
    finally:
        connection.close()


def test_future_schema_version_fails_closed(tmp_path: Path) -> None:
    """An older binary cannot mutate a database created by a newer version."""
    database_path = tmp_path / "future.db"
    connection = sqlite3.connect(database_path)
    try:
        _ = connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        _ = connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (LATEST_SCHEMA_VERSION + 1, "2026-08-07T00:00:00Z"),
        )
        connection.commit()
    finally:
        connection.close()

    assert _journal_mode(database_path) == "delete"
    with pytest.raises(UnsupportedSchemaVersionError, match="newer schema"):
        _open_and_close(database_path)
    assert _journal_mode(database_path) == "delete"
