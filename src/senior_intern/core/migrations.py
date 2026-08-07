# Copyright (c) 2026 My Senior Intern contributors

"""Ordered SQLite schema migrations."""

import sqlite3
from typing import Final, cast

LATEST_SCHEMA_VERSION = 1

type Migration = tuple[int, tuple[str, ...]]

MIGRATIONS: Final[tuple[Migration, ...]] = (
    (
        1,
        (
            """
            CREATE TABLE move_transactions (
                transaction_id TEXT PRIMARY KEY
                    CHECK (transaction_id GLOB 'txn_[A-Za-z0-9]*'),
                document_id TEXT NOT NULL,
                source_path TEXT NOT NULL,
                destination_path TEXT NOT NULL,
                state TEXT NOT NULL CHECK (
                    state IN (
                        'planned',
                        'validated',
                        'moving',
                        'moved',
                        'verified',
                        'committed',
                        'rollback_required',
                        'failed'
                    )
                ),
                planned_at TEXT NOT NULL,
                validated_at TEXT,
                moved_at TEXT,
                verified_at TEXT,
                committed_at TEXT,
                error_code TEXT,
                rollback_of_transaction_id TEXT,
                FOREIGN KEY (document_id)
                    REFERENCES documents(document_id)
                    ON UPDATE RESTRICT ON DELETE RESTRICT,
                FOREIGN KEY (rollback_of_transaction_id)
                    REFERENCES move_transactions(transaction_id)
                    ON UPDATE RESTRICT ON DELETE RESTRICT
            ) STRICT
            """,
            """
            CREATE TABLE documents (
                document_id TEXT PRIMARY KEY
                    CHECK (document_id GLOB 'doc_[A-Za-z0-9]*'),
                current_path TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                file_size INTEGER NOT NULL CHECK (file_size >= 0),
                file_type TEXT NOT NULL,
                created_at TEXT,
                modified_at TEXT NOT NULL,
                discovered_at TEXT NOT NULL,
                last_analyzed_at TEXT,
                extraction_status TEXT NOT NULL,
                classification_status TEXT NOT NULL,
                proposed_category_id TEXT,
                final_category_id TEXT,
                confidence REAL CHECK (
                    confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)
                ),
                move_transaction_id TEXT,
                security_flags_json TEXT NOT NULL DEFAULT '[]'
                    CHECK (json_valid(security_flags_json)),
                review_status TEXT NOT NULL,
                FOREIGN KEY (move_transaction_id)
                    REFERENCES move_transactions(transaction_id)
                    ON UPDATE RESTRICT ON DELETE RESTRICT
            ) STRICT
            """,
            """
            CREATE TABLE document_paths (
                document_id TEXT NOT NULL,
                sequence INTEGER NOT NULL CHECK (sequence >= 0),
                path TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                reason TEXT NOT NULL,
                PRIMARY KEY (document_id, sequence),
                FOREIGN KEY (document_id)
                    REFERENCES documents(document_id)
                    ON UPDATE RESTRICT ON DELETE RESTRICT
            ) STRICT
            """,
            """
            CREATE TABLE document_rule_matches (
                document_id TEXT NOT NULL,
                rule_id TEXT NOT NULL CHECK (rule_id GLOB 'rul_[A-Za-z0-9]*'),
                priority INTEGER NOT NULL,
                matched_at TEXT NOT NULL,
                PRIMARY KEY (document_id, rule_id),
                FOREIGN KEY (document_id)
                    REFERENCES documents(document_id)
                    ON UPDATE RESTRICT ON DELETE RESTRICT
            ) STRICT
            """,
            """
            CREATE TABLE document_relations (
                source_document_id TEXT NOT NULL,
                generated_document_id TEXT NOT NULL,
                relation_type TEXT NOT NULL CHECK (
                    relation_type IN ('source', 'generated', 'evidence')
                ),
                recorded_at TEXT NOT NULL,
                PRIMARY KEY (
                    source_document_id,
                    generated_document_id,
                    relation_type
                ),
                FOREIGN KEY (source_document_id)
                    REFERENCES documents(document_id)
                    ON UPDATE RESTRICT ON DELETE RESTRICT,
                FOREIGN KEY (generated_document_id)
                    REFERENCES documents(document_id)
                    ON UPDATE RESTRICT ON DELETE RESTRICT
            ) STRICT
            """,
            """
            CREATE INDEX documents_review_status_idx
            ON documents(review_status, classification_status)
            """,
            """
            CREATE INDEX move_transactions_state_idx
            ON move_transactions(state, planned_at)
            """,
        ),
    ),
)


class UnsupportedSchemaVersionError(RuntimeError):
    """The database was created by a newer application version."""


class InvalidMigrationStateError(RuntimeError):
    """The migration history contains an invalid value."""


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
    row = cast(
        "tuple[object, ...] | None",
        connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone(),
    )
    raw_version = 0 if row is None else row[0]
    if not isinstance(raw_version, int):
        message = "schema migration version must be an integer"
        raise InvalidMigrationStateError(message)
    current_version = raw_version
    if current_version > LATEST_SCHEMA_VERSION:
        message = (
            f"database uses newer schema {current_version}; "
            f"this application supports {LATEST_SCHEMA_VERSION}"
        )
        raise UnsupportedSchemaVersionError(message)

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
