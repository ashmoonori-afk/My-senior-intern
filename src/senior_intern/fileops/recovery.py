# Copyright (c) 2026 My Senior Intern contributors

"""Deterministic restart recovery and collision-safe undo."""

import sqlite3
from pathlib import Path
from typing import cast

from senior_intern.core.ids import (
    TransactionId,
    parse_document_id,
    parse_transaction_id,
)
from senior_intern.core.models import TransactionState
from senior_intern.fileops.move_store import transition
from senior_intern.fileops.move_types import (
    MovePersistenceError,
    TransitionOutcome,
)
from senior_intern.fileops.recovery_store import (
    complete_rollback,
    fail_rollback,
    rollback_state,
    start_rollback,
)
from senior_intern.fileops.recovery_types import (
    EndpointDisposition,
    RecoveryBackend,
    RecoveryBackendError,
    RecoveryContext,
    RecoveryRecord,
    RecoveryRequest,
    RecoveryResult,
    UndoResult,
)


def recover_interrupted_move(
    connection: sqlite3.Connection,
    request: RecoveryRequest,
    *,
    backend: RecoveryBackend,
) -> RecoveryResult:
    """Reconcile one interrupted forward move without another rename."""
    record = _load_record(connection, request.transaction_id)
    context = _context(record, request)
    state = record.state
    if state is TransactionState.MOVING:
        disposition = backend.classify_endpoints(record)
        if disposition is EndpointDisposition.SOURCE:
            error = RecoveryBackendError("interrupted_before_rename")
            _transition_error(connection, context, TransactionState.FAILED, error)
            raise error
        if disposition is not EndpointDisposition.DESTINATION:
            error = RecoveryBackendError("ambiguous_endpoints")
            _transition_error(
                connection,
                context,
                TransactionState.ROLLBACK_REQUIRED,
                error,
            )
            raise error
        transition(connection, context, TransactionState.MOVED)
        state = TransactionState.MOVED
    if state is TransactionState.MOVED:
        if not backend.verify_destination(record):
            error = RecoveryBackendError("destination_verification_failed")
            _transition_error(
                connection,
                context,
                TransactionState.ROLLBACK_REQUIRED,
                error,
            )
            raise error
        transition(connection, context, TransactionState.VERIFIED)
        state = TransactionState.VERIFIED
    if state is TransactionState.VERIFIED:
        transition(
            connection,
            context,
            TransactionState.COMMITTED,
            TransitionOutcome(destination_path=record.destination_path),
        )
        state = TransactionState.COMMITTED
    if state is not TransactionState.COMMITTED:
        message = f"transaction state is not recoverable forward: {state}"
        raise MovePersistenceError(message)
    return RecoveryResult(
        transaction_id=record.transaction_id,
        destination_path=record.destination_path,
    )


def undo_move(
    connection: sqlite3.Connection,
    request: RecoveryRequest,
    *,
    backend: RecoveryBackend,
) -> UndoResult:
    """Restore one committed move with an atomic no-replace rename."""
    record = _load_record(connection, request.transaction_id)
    existing_rollback_state = rollback_state(connection, str(request.transaction_id))
    if existing_rollback_state is TransactionState.ROLLED_BACK:
        return UndoResult(
            transaction_id=record.transaction_id,
            restored_path=record.source_path,
        )
    context = _context(record, request)
    if not start_rollback(connection, context):
        return UndoResult(
            transaction_id=record.transaction_id,
            restored_path=record.source_path,
        )
    disposition = backend.classify_endpoints(record)
    resumed_states = {
        TransactionState.ROLLING_BACK,
        TransactionState.ROLLBACK_FAILED,
    }
    if disposition is EndpointDisposition.SOURCE:
        if existing_rollback_state in resumed_states:
            if not backend.verify_source(record):
                error = RecoveryBackendError("source_verification_failed")
                fail_rollback(connection, context, error.code)
                raise error
            complete_rollback(connection, context)
            return UndoResult(
                transaction_id=record.transaction_id,
                restored_path=record.source_path,
            )
        error = RecoveryBackendError("unexpected_source_endpoint")
        fail_rollback(connection, context, error.code)
        raise error
    if disposition is not EndpointDisposition.DESTINATION:
        error = RecoveryBackendError("ambiguous_endpoints")
        fail_rollback(connection, context, error.code)
        raise error
    if not backend.verify_destination(record):
        error = RecoveryBackendError("destination_verification_failed")
        fail_rollback(connection, context, error.code)
        raise error
    try:
        backend.rollback_no_replace(record)
    except RecoveryBackendError as error:
        fail_rollback(connection, context, error.code)
        raise
    if not backend.verify_source(record):
        error = RecoveryBackendError("source_verification_failed")
        fail_rollback(connection, context, error.code)
        raise error
    complete_rollback(connection, context)
    return UndoResult(
        transaction_id=record.transaction_id,
        restored_path=record.source_path,
    )


def _load_record(
    connection: sqlite3.Connection,
    transaction_id: TransactionId,
) -> RecoveryRecord:
    row = cast(
        "tuple[object, ...] | None",
        connection.execute(
            """
            SELECT transaction_id, document_id, source_path, destination_path,
                   state, source_root_path, source_root_object_id,
                   source_object_id, destination_directory_object_id, volume_id,
                   source_file_hash, source_file_size, source_modified_at
            FROM move_transactions WHERE transaction_id = ?
            """,
            (transaction_id,),
        ).fetchone(),
    )
    if row is None or any(value is None for value in row):
        message = "move recovery identity record is unavailable"
        raise MovePersistenceError(message)
    return RecoveryRecord(
        transaction_id=parse_transaction_id(str(row[0])),
        document_id=parse_document_id(str(row[1])),
        source_path=Path(str(row[2])),
        destination_path=Path(str(row[3])),
        state=TransactionState(str(row[4])),
        source_root_path=Path(str(row[5])),
        source_root_object_id=str(row[6]),
        source_object_id=str(row[7]),
        destination_directory_object_id=str(row[8]),
        volume_id=str(row[9]),
        source_file_hash=str(row[10]),
        source_file_size=int(str(row[11])),
        source_modified_at=str(row[12]),
    )


def _context(
    record: RecoveryRecord,
    request: RecoveryRequest,
) -> RecoveryContext:
    return RecoveryContext(
        transaction_id=record.transaction_id,
        document_id=record.document_id,
        audit_event_id=request.audit_event_id,
        timeline=request.timeline,
        source_path=record.source_path,
        destination_path=record.destination_path,
        forward_state=record.state,
    )


def _transition_error(
    connection: sqlite3.Connection,
    context: RecoveryContext,
    state: TransactionState,
    error: RecoveryBackendError,
) -> None:
    transition(
        connection,
        context,
        state,
        TransitionOutcome(
            detail={"error_code": error.code},
            error_code=error.code,
        ),
    )
