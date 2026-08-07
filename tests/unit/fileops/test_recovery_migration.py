# Copyright (c) 2026 My Senior Intern contributors

"""Schema v2 to v3 recovery migration tests."""

import sqlite3
from pathlib import Path
from typing import cast

import pytest

from senior_intern.core.migrations import apply_migrations
from senior_intern.core.schema_v1 import MIGRATION_1
from senior_intern.core.schema_v2 import MIGRATION_2
from senior_intern.fileops.move_types import MovePersistenceError
from senior_intern.fileops.recovery import recover_interrupted_move
from tests.unit.fileops.recovery_test_support import (
    FixtureRecoveryBackend,
    make_recovery_request,
)


def _version_two_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, isolation_level=None)
    _ = connection.execute("PRAGMA foreign_keys = ON")
    _ = connection.execute(
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY CHECK (version > 0),
            applied_at TEXT NOT NULL
        ) STRICT
        """
    )
    for statement in (*MIGRATION_1, *MIGRATION_2):
        _ = connection.execute(statement)
    _ = connection.executemany(
        "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
        (
            (1, "2026-08-07T00:00:00Z"),
            (2, "2026-08-07T00:00:01Z"),
        ),
    )
    _ = connection.execute(
        """
        INSERT INTO documents (
            document_id, current_path, file_hash, file_size, file_type,
            modified_at, discovered_at, extraction_status,
            classification_status, security_flags_json, review_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "doc_abcdefghij",
            "source.pdf",
            "fixture-hash",
            7,
            "pdf",
            "2026-08-07T00:00:00Z",
            "2026-08-07T00:00:00Z",
            "pending",
            "pending",
            "[]",
            "pending",
        ),
    )
    _ = connection.execute(
        """
        INSERT INTO move_transactions (
            transaction_id, document_id, source_path, destination_path,
            state, planned_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "txn_abcdefghij",
            "doc_abcdefghij",
            "source.pdf",
            "destination.pdf",
            "moving",
            "2026-08-07T00:00:02Z",
        ),
    )
    return connection


def test_version_three_preserves_legacy_rows_and_fails_closed(tmp_path: Path) -> None:
    """Legacy moves survive migration but lack required recovery evidence."""
    connection = _version_two_database(tmp_path / "legacy.db")

    apply_migrations(connection)

    version = cast(
        "tuple[int] | None",
        connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone(),
    )
    assert version is not None
    assert tuple(version) == (3,)
    row = cast(
        "tuple[str, str, str, None] | None",
        connection.execute(
            """
            SELECT state, source_path, destination_path, source_object_id
            FROM move_transactions WHERE transaction_id = ?
            """,
            ("txn_abcdefghij",),
        ).fetchone(),
    )
    assert row == ("moving", "source.pdf", "destination.pdf", None)
    schema_rows = cast(
        "list[tuple[str]]",
        connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type IN ('table', 'index', 'trigger')
            """
        ).fetchall(),
    )
    schema_names = {item[0] for item in schema_rows}
    assert {
        "move_rollbacks",
        "move_rollback_events",
        "idx_move_rollback_events_transaction_sequence",
        "move_rollback_events_no_update",
        "move_rollback_events_no_delete",
    } <= schema_names

    with pytest.raises(MovePersistenceError, match="identity record is unavailable"):
        _ = recover_interrupted_move(
            connection,
            make_recovery_request(),
            backend=FixtureRecoveryBackend(b"legacy"),
        )
    connection.close()
