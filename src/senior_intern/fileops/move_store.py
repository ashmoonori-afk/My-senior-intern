# Copyright (c) 2026 My Senior Intern contributors

"""Durable SQLite state machine for file moves."""

import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from senior_intern.core.models import TransactionState
from senior_intern.fileops.move_commit import (
    commit_document_path,
    current_state,
    require_current_document_path,
    update_transaction,
)
from senior_intern.fileops.move_types import (
    DetailValue,
    MovePersistenceError,
    MoveRequest,
    TransitionOutcome,
)

_ALLOWED: Mapping[TransactionState, frozenset[TransactionState]] = {
    TransactionState.PLANNED: frozenset({TransactionState.VALIDATED, TransactionState.FAILED}),
    TransactionState.VALIDATED: frozenset({TransactionState.MOVING, TransactionState.FAILED}),
    TransactionState.MOVING: frozenset(
        {
            TransactionState.MOVED,
            TransactionState.FAILED,
            TransactionState.ROLLBACK_REQUIRED,
        }
    ),
    TransactionState.MOVED: frozenset(
        {TransactionState.VERIFIED, TransactionState.ROLLBACK_REQUIRED}
    ),
    TransactionState.VERIFIED: frozenset(
        {TransactionState.COMMITTED, TransactionState.ROLLBACK_REQUIRED}
    ),
}


def _canonical_detail(detail: Mapping[str, DetailValue]) -> str:
    return json.dumps(
        dict(detail),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _insert_event(
    connection: sqlite3.Connection,
    request: MoveRequest,
    state: TransactionState,
    detail: Mapping[str, DetailValue],
) -> None:
    _ = connection.execute(
        """
        INSERT INTO move_transaction_events (
            transaction_id, state, recorded_at, detail_json
        ) VALUES (?, ?, ?, ?)
        """,
        (
            request.transaction_id,
            state,
            request.timeline.for_state(state),
            _canonical_detail(detail),
        ),
    )


def record_plan(
    connection: sqlite3.Connection,
    request: MoveRequest,
    destination_path: Path,
) -> None:
    """Persist the plan before platform inspection or mutation."""
    _ = connection.execute("BEGIN IMMEDIATE")
    try:
        require_current_document_path(connection, request)
        _ = connection.execute(
            """
            INSERT INTO move_transactions (
                transaction_id, document_id, source_path, destination_path,
                state, planned_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                request.transaction_id,
                request.document_id,
                str(request.ticket.source_file.path),
                str(destination_path),
                TransactionState.PLANNED,
                request.timeline.for_state(TransactionState.PLANNED),
            ),
        )
        _insert_event(
            connection,
            request,
            TransactionState.PLANNED,
            {"destination_path": str(destination_path)},
        )
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def transition(
    connection: sqlite3.Connection,
    request: MoveRequest,
    state: TransactionState,
    outcome: TransitionOutcome | None = None,
) -> None:
    """Atomically update the snapshot row and append its state event."""
    if outcome is None:
        outcome = TransitionOutcome()
    _require_transition_outcome(state, outcome)
    _ = connection.execute("BEGIN IMMEDIATE")
    try:
        current = current_state(connection, request)
        _require_allowed_transition(current, state)
        update_transaction(
            connection,
            request,
            state,
            error_code=outcome.error_code,
        )
        if state is TransactionState.COMMITTED:
            destination_path = cast("Path", outcome.destination_path)
            commit_document_path(connection, request, destination_path)
        detail: Mapping[str, DetailValue] = {} if outcome.detail is None else outcome.detail
        _insert_event(connection, request, state, detail)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def _require_transition_outcome(
    state: TransactionState,
    outcome: TransitionOutcome,
) -> None:
    if state is TransactionState.COMMITTED and outcome.destination_path is None:
        message = "committed transition requires destination_path"
        raise MovePersistenceError(message)


def _require_allowed_transition(
    current: TransactionState,
    state: TransactionState,
) -> None:
    if state not in _ALLOWED.get(current, frozenset()):
        message = f"invalid move transition: {current} -> {state}"
        raise MovePersistenceError(message)
