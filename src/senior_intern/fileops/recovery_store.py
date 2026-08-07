# Copyright (c) 2026 My Senior Intern contributors

"""Durable SQLite state machine for move rollback."""

import json
import sqlite3
from collections.abc import Mapping
from typing import cast

from senior_intern.core.models import TransactionState
from senior_intern.fileops.move_commit import restore_document_path
from senior_intern.fileops.move_types import (
    DetailValue,
    MovePersistenceError,
    RollbackContext,
)


def rollback_state(
    connection: sqlite3.Connection,
    transaction_id: str,
) -> TransactionState | None:
    """Return the durable rollback state when one exists."""
    record = _rollback_record(connection, transaction_id)
    return None if record is None else record[0]


def start_rollback(
    connection: sqlite3.Connection,
    context: RollbackContext,
) -> bool:
    """Start or resume rollback; return false when already complete."""
    _ = connection.execute("BEGIN IMMEDIATE")
    try:
        record = _rollback_record(connection, str(context.transaction_id))
        state = None if record is None else record[0]
        if state is TransactionState.ROLLED_BACK:
            connection.commit()
            return False
        if (
            state is TransactionState.ROLLING_BACK
            and record is not None
            and record[1] != str(context.audit_event_id)
        ):
            _raise_active_attempt()
        _require_undoable_move(connection, context)
        if state is None:
            _ = connection.execute(
                """
                INSERT INTO move_rollbacks (
                    transaction_id, state, attempt_id, started_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    context.transaction_id,
                    TransactionState.ROLLING_BACK,
                    context.audit_event_id,
                    context.timeline.for_state(TransactionState.ROLLING_BACK),
                ),
            )
            _insert_event(connection, context, TransactionState.ROLLING_BACK, {})
        elif state is TransactionState.ROLLBACK_FAILED:
            _ = connection.execute(
                """
                UPDATE move_rollbacks
                SET state = ?, started_at = ?, completed_at = NULL,
                    error_code = NULL, attempt_id = ?
                WHERE transaction_id = ?
                """,
                (
                    TransactionState.ROLLING_BACK,
                    context.timeline.for_state(TransactionState.ROLLING_BACK),
                    context.audit_event_id,
                    context.transaction_id,
                ),
            )
            _insert_event(connection, context, TransactionState.ROLLING_BACK, {})
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return True


def complete_rollback(
    connection: sqlite3.Connection,
    context: RollbackContext,
) -> None:
    """Commit restored document state and rollback audit atomically."""
    _ = connection.execute("BEGIN IMMEDIATE")
    try:
        _require_rollback_state(
            connection,
            context,
            TransactionState.ROLLING_BACK,
        )
        restore_document_path(connection, context)
        _ = connection.execute(
            """
            UPDATE move_rollbacks
            SET state = ?, completed_at = ?, error_code = NULL
            WHERE transaction_id = ?
            """,
            (
                TransactionState.ROLLED_BACK,
                context.timeline.for_state(TransactionState.ROLLED_BACK),
                context.transaction_id,
            ),
        )
        _insert_event(connection, context, TransactionState.ROLLED_BACK, {})
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def fail_rollback(
    connection: sqlite3.Connection,
    context: RollbackContext,
    error_code: str,
) -> None:
    """Persist a typed rollback failure without changing document ownership."""
    _ = connection.execute("BEGIN IMMEDIATE")
    try:
        _require_rollback_state(
            connection,
            context,
            TransactionState.ROLLING_BACK,
        )
        _ = connection.execute(
            """
            UPDATE move_rollbacks
            SET state = ?, completed_at = ?, error_code = ?
            WHERE transaction_id = ?
            """,
            (
                TransactionState.ROLLBACK_FAILED,
                context.timeline.for_state(TransactionState.ROLLBACK_FAILED),
                error_code,
                context.transaction_id,
            ),
        )
        _insert_event(
            connection,
            context,
            TransactionState.ROLLBACK_FAILED,
            {"error_code": error_code},
        )
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def _require_undoable_move(
    connection: sqlite3.Connection,
    context: RollbackContext,
) -> None:
    row = cast(
        "tuple[object, ...] | None",
        connection.execute(
            """
            SELECT state, document_id, source_path, destination_path
            FROM move_transactions WHERE transaction_id = ?
            """,
            (context.transaction_id,),
        ).fetchone(),
    )
    expected = (
        str(context.document_id),
        str(context.source_path),
        str(context.destination_path),
    )
    allowed = {TransactionState.COMMITTED, TransactionState.ROLLBACK_REQUIRED}
    if row is None or TransactionState(str(row[0])) not in allowed:
        message = "move transaction is not undoable"
        raise MovePersistenceError(message)
    if tuple(row[1:]) != expected:
        message = "rollback context does not match durable transaction"
        raise MovePersistenceError(message)


def _require_rollback_state(
    connection: sqlite3.Connection,
    context: RollbackContext,
    expected: TransactionState,
) -> None:
    record = _rollback_record(connection, str(context.transaction_id))
    state = None if record is None else record[0]
    attempt_id = None if record is None else record[1]
    if state is not expected or attempt_id != str(context.audit_event_id):
        message = f"invalid rollback state or attempt: {state} -> {expected}"
        raise MovePersistenceError(message)


def _insert_event(
    connection: sqlite3.Connection,
    context: RollbackContext,
    state: TransactionState,
    detail: Mapping[str, DetailValue],
) -> None:
    detail_json = json.dumps(
        dict(detail),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    _ = connection.execute(
        """
        INSERT INTO move_rollback_events (
            transaction_id, state, recorded_at, detail_json
        ) VALUES (?, ?, ?, ?)
        """,
        (
            context.transaction_id,
            state,
            context.timeline.for_state(state),
            detail_json,
        ),
    )


def _rollback_record(
    connection: sqlite3.Connection,
    transaction_id: str,
) -> tuple[TransactionState, str] | None:
    row = cast(
        "tuple[object, ...] | None",
        connection.execute(
            "SELECT state, attempt_id FROM move_rollbacks WHERE transaction_id = ?",
            (transaction_id,),
        ).fetchone(),
    )
    if row is None:
        return None
    return TransactionState(str(row[0])), str(row[1])


def _raise_active_attempt() -> None:
    message = "rollback is already active under another attempt"
    raise MovePersistenceError(message)
