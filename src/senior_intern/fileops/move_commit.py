# Copyright (c) 2026 My Senior Intern contributors

"""Validated SQLite updates for durable move transactions."""

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from senior_intern.core.audit import AuditEventInput, insert_audit_event
from senior_intern.core.models import TransactionState
from senior_intern.fileops.move_types import (
    MoveContext,
    MovePersistenceError,
    MoveRequest,
    RollbackContext,
)

_UPDATE_PREFIX = "UPDATE move_transactions SET state = ?, "
_UPDATE_SUFFIX = " = ?, error_code = ? WHERE transaction_id = ?"
_TIMESTAMP_UPDATE: Mapping[TransactionState, str] = {
    TransactionState.VALIDATED: _UPDATE_PREFIX + "validated_at" + _UPDATE_SUFFIX,
    TransactionState.MOVED: _UPDATE_PREFIX + "moved_at" + _UPDATE_SUFFIX,
    TransactionState.VERIFIED: _UPDATE_PREFIX + "verified_at" + _UPDATE_SUFFIX,
    TransactionState.COMMITTED: _UPDATE_PREFIX + "committed_at" + _UPDATE_SUFFIX,
}


@dataclass(frozen=True)
class DocumentMoveEvidence:
    """Immutable document evidence captured while planning."""

    file_hash: str
    file_size: int
    modified_at: str


def require_current_document_path(
    connection: sqlite3.Connection,
    request: MoveRequest,
) -> DocumentMoveEvidence:
    """Require source ownership and return persisted content evidence."""
    current_path_row = cast(
        "tuple[object, ...] | None",
        connection.execute(
            """
            SELECT current_path, file_hash, file_size, modified_at
            FROM documents WHERE document_id = ?
            """,
            (request.document_id,),
        ).fetchone(),
    )
    expected = str(request.ticket.source_file.path)
    if current_path_row is None or current_path_row[0] != expected:
        message = "document source path does not match durable state"
        raise MovePersistenceError(message)
    return DocumentMoveEvidence(
        file_hash=str(current_path_row[1]),
        file_size=int(str(current_path_row[2])),
        modified_at=str(current_path_row[3]),
    )


def current_state(
    connection: sqlite3.Connection,
    request: MoveContext,
) -> TransactionState:
    """Load state only when every stored transaction association matches."""
    row = cast(
        "tuple[object, ...] | None",
        connection.execute(
            """
            SELECT state, document_id, source_path, destination_path
            FROM move_transactions
            WHERE transaction_id = ?
            """,
            (request.transaction_id,),
        ).fetchone(),
    )
    if row is None:
        message = "move transaction does not exist"
        raise MovePersistenceError(message)
    expected = (
        str(request.document_id),
        str(request.source_path),
        str(request.destination_path),
    )
    if tuple(row[1:]) != expected:
        message = "move request does not match durable transaction"
        raise MovePersistenceError(message)
    return TransactionState(str(row[0]))


def update_transaction(
    connection: sqlite3.Connection,
    request: MoveContext,
    state: TransactionState,
    *,
    error_code: str | None,
) -> None:
    """Update one whitelisted snapshot column for the next state."""
    update_statement = _TIMESTAMP_UPDATE.get(state)
    if update_statement is None:
        _ = connection.execute(
            """
            UPDATE move_transactions
            SET state = ?, error_code = ?
            WHERE transaction_id = ?
            """,
            (state, error_code, request.transaction_id),
        )
        return
    _ = connection.execute(
        update_statement,
        (
            state,
            request.timeline.for_state(state),
            error_code,
            request.transaction_id,
        ),
    )


def commit_document_path(
    connection: sqlite3.Connection,
    request: MoveContext,
    destination_path: Path,
) -> None:
    """Commit document ownership, history, and digest-linked audit atomically."""
    cursor = connection.execute(
        """
        UPDATE documents
        SET current_path = ?, move_transaction_id = ?
        WHERE document_id = ? AND current_path = ?
        """,
        (
            str(destination_path),
            request.transaction_id,
            request.document_id,
            str(request.source_path),
        ),
    )
    if cursor.rowcount != 1:
        message = "document path changed after move planning"
        raise MovePersistenceError(message)
    _ = connection.execute(
        """
        INSERT INTO document_paths (
            document_id, sequence, path, recorded_at, reason
        )
        SELECT ?, COALESCE(MAX(sequence), -1) + 1, ?, ?, ?
        FROM document_paths
        WHERE document_id = ?
        """,
        (
            request.document_id,
            str(destination_path),
            request.timeline.for_state(TransactionState.COMMITTED),
            "automatic_move",
            request.document_id,
        ),
    )
    _ = insert_audit_event(
        connection,
        AuditEventInput(
            event_id=request.audit_event_id,
            event_type="document_moved",
            transaction_id=request.transaction_id,
            document_id=request.document_id,
            occurred_at=request.timeline.for_state(TransactionState.COMMITTED),
            actor="system",
            payload={
                "source_path": str(request.source_path),
                "destination_path": str(destination_path),
            },
        ),
    )


def restore_document_path(
    connection: sqlite3.Connection,
    request: RollbackContext,
) -> None:
    """Commit restored ownership, history, and digest-linked audit atomically."""
    expected_current_path = (
        request.destination_path
        if request.forward_state is TransactionState.COMMITTED
        else request.source_path
    )
    cursor = connection.execute(
        """
        UPDATE documents
        SET current_path = ?, move_transaction_id = NULL
        WHERE document_id = ? AND current_path = ?
        """,
        (
            str(request.source_path),
            request.document_id,
            str(expected_current_path),
        ),
    )
    if cursor.rowcount != 1:
        message = "document path changed before rollback commit"
        raise MovePersistenceError(message)
    if request.forward_state is TransactionState.COMMITTED:
        _ = connection.execute(
            """
            INSERT INTO document_paths (
                document_id, sequence, path, recorded_at, reason
            )
            SELECT ?, COALESCE(MAX(sequence), -1) + 1, ?, ?, ?
            FROM document_paths WHERE document_id = ?
            """,
            (
                request.document_id,
                str(request.source_path),
                request.timeline.for_state(TransactionState.ROLLED_BACK),
                "manual_undo",
                request.document_id,
            ),
        )
    event_type = (
        "move_undone" if request.forward_state is TransactionState.COMMITTED else "move_recovered"
    )
    _ = insert_audit_event(
        connection,
        AuditEventInput(
            event_id=request.audit_event_id,
            event_type=event_type,
            transaction_id=request.transaction_id,
            document_id=request.document_id,
            occurred_at=request.timeline.for_state(TransactionState.ROLLED_BACK),
            actor="user",
            payload={
                "source_path": str(request.source_path),
                "destination_path": str(request.destination_path),
            },
        ),
    )
