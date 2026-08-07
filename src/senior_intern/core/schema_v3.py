# Copyright (c) 2026 My Senior Intern contributors

"""Schema v3: persist object identities required for crash recovery."""

MIGRATION_3 = (
    "ALTER TABLE move_transactions ADD COLUMN source_root_path TEXT",
    "ALTER TABLE move_transactions ADD COLUMN source_root_object_id TEXT",
    "ALTER TABLE move_transactions ADD COLUMN source_object_id TEXT",
    "ALTER TABLE move_transactions ADD COLUMN destination_directory_object_id TEXT",
    "ALTER TABLE move_transactions ADD COLUMN volume_id TEXT",
    "ALTER TABLE move_transactions ADD COLUMN source_file_hash TEXT",
    "ALTER TABLE move_transactions ADD COLUMN source_file_size INTEGER",
    "ALTER TABLE move_transactions ADD COLUMN source_modified_at TEXT",
    """
    CREATE TABLE move_rollbacks (
        transaction_id TEXT PRIMARY KEY,
        state TEXT NOT NULL CHECK (
            state IN ('rolling_back', 'rolled_back', 'rollback_failed')
        ),
        attempt_id TEXT NOT NULL,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        error_code TEXT,
        FOREIGN KEY (transaction_id)
            REFERENCES move_transactions(transaction_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT
    ) STRICT
    """,
    """
    CREATE TABLE move_rollback_events (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        transaction_id TEXT NOT NULL,
        state TEXT NOT NULL CHECK (
            state IN ('rolling_back', 'rolled_back', 'rollback_failed')
        ),
        recorded_at TEXT NOT NULL,
        detail_json TEXT NOT NULL CHECK (json_valid(detail_json)),
        FOREIGN KEY (transaction_id)
            REFERENCES move_rollbacks(transaction_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT
    ) STRICT
    """,
    """
    CREATE INDEX idx_move_rollback_events_transaction_sequence
    ON move_rollback_events(transaction_id, sequence)
    """,
    """
    CREATE TRIGGER move_rollback_events_no_update
    BEFORE UPDATE ON move_rollback_events
    BEGIN
        SELECT RAISE(ABORT, 'move rollback events are append-only');
    END
    """,
    """
    CREATE TRIGGER move_rollback_events_no_delete
    BEFORE DELETE ON move_rollback_events
    BEGIN
        SELECT RAISE(ABORT, 'move rollback events are append-only');
    END
    """,
)
