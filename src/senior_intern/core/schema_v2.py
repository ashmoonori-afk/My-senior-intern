# Copyright (c) 2026 My Senior Intern contributors

"""Append-only audit and transaction-event schema."""

from typing import Final

MIGRATION_2: Final[tuple[str, ...]] = (
    """
    CREATE TABLE move_transaction_events (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        transaction_id TEXT NOT NULL,
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
        recorded_at TEXT NOT NULL,
        detail_json TEXT NOT NULL CHECK (json_valid(detail_json)),
        FOREIGN KEY (transaction_id)
            REFERENCES move_transactions(transaction_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT
    ) STRICT
    """,
    """
    CREATE TABLE audit_events (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT NOT NULL UNIQUE
            CHECK (event_id GLOB 'aud_[A-Za-z0-9]*'),
        event_type TEXT NOT NULL CHECK (length(event_type) > 0),
        transaction_id TEXT,
        document_id TEXT,
        occurred_at TEXT NOT NULL,
        actor TEXT NOT NULL CHECK (length(actor) > 0),
        payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
        previous_digest TEXT CHECK (
            previous_digest IS NULL OR length(previous_digest) = 64
        ),
        event_digest TEXT NOT NULL UNIQUE CHECK (length(event_digest) = 64),
        FOREIGN KEY (transaction_id)
            REFERENCES move_transactions(transaction_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT,
        FOREIGN KEY (document_id)
            REFERENCES documents(document_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT
    ) STRICT
    """,
    """
    CREATE INDEX audit_events_occurred_at_idx
    ON audit_events(occurred_at, sequence)
    """,
    """
    CREATE INDEX move_transaction_events_transaction_idx
    ON move_transaction_events(transaction_id, sequence)
    """,
    """
    CREATE TRIGGER audit_events_no_update
    BEFORE UPDATE ON audit_events
    BEGIN
        SELECT RAISE(ABORT, 'audit_events are append-only');
    END
    """,
    """
    CREATE TRIGGER audit_events_no_delete
    BEFORE DELETE ON audit_events
    BEGIN
        SELECT RAISE(ABORT, 'audit_events are append-only');
    END
    """,
    """
    CREATE TRIGGER move_transaction_events_no_update
    BEFORE UPDATE ON move_transaction_events
    BEGIN
        SELECT RAISE(ABORT, 'move_transaction_events are append-only');
    END
    """,
    """
    CREATE TRIGGER move_transaction_events_no_delete
    BEFORE DELETE ON move_transaction_events
    BEGIN
        SELECT RAISE(ABORT, 'move_transaction_events are append-only');
    END
    """,
)
