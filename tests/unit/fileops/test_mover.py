# Copyright (c) 2026 My Senior Intern contributors

"""Successful and collision-safe atomic move tests."""

import json
from pathlib import Path
from typing import cast

import pytest

from senior_intern.core.database import open_database
from senior_intern.core.models import TransactionState
from senior_intern.fileops.mover import MoveBackendError, execute_atomic_move
from tests.unit.fileops.move_test_support import (
    AUDIT_EVENT_ID,
    DOCUMENT_ID,
    TIMELINE,
    TRANSACTION_ID,
    FixtureAtomicMoveBackend,
    insert_document,
    make_request,
    make_ticket,
    transaction_states,
)


def test_atomic_move_commits_ordered_state_and_document_path(tmp_path: Path) -> None:
    """One verified rename commits history and digest-linked audit."""
    content = b"unchanged document bytes"
    source = tmp_path / "source" / "document.pdf"
    destination_directory = tmp_path / "destination"
    source.parent.mkdir()
    destination_directory.mkdir()
    _ = source.write_bytes(content)
    connection = open_database(tmp_path / "state.db")
    insert_document(connection, source, content)
    backend = FixtureAtomicMoveBackend(content)
    statements: list[str] = []
    connection.set_trace_callback(statements.append)

    result = execute_atomic_move(
        connection,
        make_request(make_ticket(source, destination_directory)),
        backend=backend,
    )

    destination = destination_directory / "moved.pdf"
    assert result.destination_path == destination
    assert not source.exists()
    assert destination.read_bytes() == content
    assert backend.calls == [
        "revalidate_and_rename_no_replace",
        "verify_destination",
    ]
    assert transaction_states(connection) == [
        TransactionState.PLANNED,
        TransactionState.VALIDATED,
        TransactionState.MOVING,
        TransactionState.MOVED,
        TransactionState.VERIFIED,
        TransactionState.COMMITTED,
    ]
    document_row = cast(
        "tuple[str, str] | None",
        connection.execute(
            "SELECT current_path, move_transaction_id FROM documents WHERE document_id = ?",
            (DOCUMENT_ID,),
        ).fetchone(),
    )
    assert document_row is not None
    assert tuple(document_row) == (str(destination), TRANSACTION_ID)
    event_rows = cast(
        "list[tuple[str, str]]",
        connection.execute(
            """
            SELECT state, recorded_at FROM move_transaction_events
            WHERE transaction_id = ? ORDER BY sequence
            """,
            (TRANSACTION_ID,),
        ).fetchall(),
    )
    assert [row[1] for row in event_rows] == [
        TIMELINE.planned_at,
        TIMELINE.validated_at,
        TIMELINE.moving_at,
        TIMELINE.moved_at,
        TIMELINE.verified_at,
        TIMELINE.committed_at,
    ]
    audit_row = cast(
        "tuple[str, str, str, str] | None",
        connection.execute(
            """
            SELECT event_type, transaction_id, document_id, payload_json
            FROM audit_events WHERE event_id = ?
            """,
            (AUDIT_EVENT_ID,),
        ).fetchone(),
    )
    assert audit_row is not None
    assert tuple(audit_row[:3]) == ("document_moved", TRANSACTION_ID, DOCUMENT_ID)
    assert json.loads(audit_row[3]) == {
        "destination_path": str(destination),
        "source_path": str(source),
    }
    plan_begin = statements.index("BEGIN IMMEDIATE")
    source_read = next(
        index
        for index, statement in enumerate(statements)
        if "SELECT current_path, file_hash" in statement
    )
    assert plan_begin < source_read
    connection.close()


def test_collision_fails_without_overwrite_and_records_failure(tmp_path: Path) -> None:
    """An occupied leaf preserves both files and records failure."""
    source_content = b"source bytes"
    destination_content = b"existing destination"
    source = tmp_path / "source" / "document.pdf"
    destination_directory = tmp_path / "destination"
    source.parent.mkdir()
    destination_directory.mkdir()
    _ = source.write_bytes(source_content)
    destination = destination_directory / "moved.pdf"
    _ = destination.write_bytes(destination_content)
    connection = open_database(tmp_path / "state.db")
    insert_document(connection, source, source_content)
    backend = FixtureAtomicMoveBackend(source_content)

    with pytest.raises(MoveBackendError, match="destination_exists"):
        _ = execute_atomic_move(
            connection,
            make_request(make_ticket(source, destination_directory)),
            backend=backend,
        )

    assert source.read_bytes() == source_content
    assert destination.read_bytes() == destination_content
    assert backend.calls == ["revalidate_and_rename_no_replace"]
    assert transaction_states(connection)[-1] == TransactionState.FAILED
    connection.close()
