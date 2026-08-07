# Copyright (c) 2026 My Senior Intern contributors

"""Collision-safe undo and crash recovery RED tests."""

import json
from pathlib import Path
from typing import cast

import pytest

from senior_intern.core.database import open_database
from senior_intern.core.models import TransactionState
from senior_intern.fileops.mover import execute_atomic_move
from senior_intern.fileops.recovery import (
    recover_interrupted_move,
    undo_move,
)
from senior_intern.fileops.recovery_types import RecoveryBackendError
from tests.unit.fileops.move_test_support import (
    TRANSACTION_ID,
    FixtureAtomicMoveBackend,
    SimulatedCrash,
    insert_document,
    make_request,
    make_ticket,
    transaction_states,
)
from tests.unit.fileops.recovery_test_support import (
    FixtureRecoveryBackend,
    audit_event_summaries,
    committed_move,
    make_recovery_request,
    rollback_states,
)


def test_undo_restores_committed_move_byte_identically(tmp_path: Path) -> None:
    """Undo restores the original object and durable document path."""
    connection, source, destination, content = committed_move(tmp_path)
    backend = FixtureRecoveryBackend(content)

    result = undo_move(connection, make_recovery_request(), backend=backend)

    assert result.restored_path == source
    assert source.read_bytes() == content
    assert not destination.exists()
    assert rollback_states(connection)[-2:] == [
        TransactionState.ROLLING_BACK,
        TransactionState.ROLLED_BACK,
    ]
    audit_row = cast(
        "tuple[str, str, str, str, str] | None",
        connection.execute(
            """
            SELECT event_type, actor, transaction_id, occurred_at, payload_json
            FROM audit_events ORDER BY sequence DESC LIMIT 1
            """
        ).fetchone(),
    )
    assert audit_row is not None
    assert audit_row[:4] == (
        "move_undone",
        "user",
        TRANSACTION_ID,
        "2026-08-07T04:00:09Z",
    )
    assert json.loads(audit_row[4]) == {
        "destination_path": str(destination),
        "source_path": str(source),
    }
    connection.close()


def test_undo_collision_never_overwrites_source(tmp_path: Path) -> None:
    """An occupied source preserves both objects and records failure."""
    connection, source, destination, content = committed_move(tmp_path)
    collision = b"new source occupant"
    _ = source.write_bytes(collision)
    backend = FixtureRecoveryBackend(content)

    with pytest.raises(RecoveryBackendError, match="ambiguous_endpoints"):
        _ = undo_move(connection, make_recovery_request(), backend=backend)

    assert source.read_bytes() == collision
    assert destination.read_bytes() == content
    assert rollback_states(connection)[-2:] == [
        TransactionState.ROLLING_BACK,
        TransactionState.ROLLBACK_FAILED,
    ]
    connection.close()


def test_repeated_undo_is_idempotent(tmp_path: Path) -> None:
    """A completed undo never cycles or mutates again."""
    connection, source, destination, content = committed_move(tmp_path)
    backend = FixtureRecoveryBackend(content)
    first = undo_move(connection, make_recovery_request(), backend=backend)
    calls_after_first = list(backend.calls)
    counts_before = cast(
        "tuple[int, int, int]",
        connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM move_rollback_events),
                (SELECT COUNT(*) FROM audit_events),
                (SELECT COUNT(*) FROM document_paths)
            """
        ).fetchone(),
    )

    second = undo_move(connection, make_recovery_request(), backend=backend)

    assert second == first
    assert backend.calls == calls_after_first
    counts_after = cast(
        "tuple[int, int, int]",
        connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM move_rollback_events),
                (SELECT COUNT(*) FROM audit_events),
                (SELECT COUNT(*) FROM document_paths)
            """
        ).fetchone(),
    )
    assert counts_after == counts_before
    assert source.read_bytes() == content
    assert not destination.exists()
    connection.close()


def test_undo_interruption_resumes_without_second_rename(tmp_path: Path) -> None:
    """A crash after rollback rename resumes by identity classification."""
    connection, source, destination, content = committed_move(tmp_path)
    interrupted_backend = FixtureRecoveryBackend(content)
    interrupted_backend.interrupt_after_rollback = True

    with pytest.raises(SimulatedCrash):
        _ = undo_move(
            connection,
            make_recovery_request(),
            backend=interrupted_backend,
        )

    assert source.read_bytes() == content
    assert not destination.exists()
    assert rollback_states(connection) == [TransactionState.ROLLING_BACK]
    connection.close()
    connection = open_database(tmp_path / "state.db")
    resumed_backend = FixtureRecoveryBackend(content)

    result = undo_move(
        connection,
        make_recovery_request(),
        backend=resumed_backend,
    )

    assert result.restored_path == source
    assert resumed_backend.calls == ["classify_endpoints", "verify_source"]
    assert rollback_states(connection)[-1] == TransactionState.ROLLED_BACK
    connection.close()


def test_recovery_commits_move_interrupted_after_rename(tmp_path: Path) -> None:
    """A MOVING row with only matching destination resumes deterministically."""
    content = b"unchanged bytes"
    source = tmp_path / "source" / "document.pdf"
    destination_directory = tmp_path / "destination"
    source.parent.mkdir()
    destination_directory.mkdir()
    _ = source.write_bytes(content)
    connection = open_database(tmp_path / "state.db")
    insert_document(connection, source, content)
    move_backend = FixtureAtomicMoveBackend(content)
    move_backend.interrupt_after_rename = True
    with pytest.raises(SimulatedCrash):
        _ = execute_atomic_move(
            connection,
            make_request(make_ticket(source, destination_directory)),
            backend=move_backend,
        )

    connection.close()
    connection = open_database(tmp_path / "state.db")
    recovery_backend = FixtureRecoveryBackend(content)
    result = recover_interrupted_move(
        connection,
        make_recovery_request(),
        backend=recovery_backend,
    )

    assert result.destination_path.read_bytes() == content
    assert not source.exists()
    assert transaction_states(connection)[-3:] == [
        TransactionState.MOVED,
        TransactionState.VERIFIED,
        TransactionState.COMMITTED,
    ]
    assert audit_event_summaries(connection) == [("aud_klmnopqrst", "document_moved", "system")]
    record = recovery_backend.seen_records[0]
    assert record.source_root_path == source.parent
    assert record.source_root_object_id == "object-source_root"
    assert record.destination_directory_object_id == "object-destination_directory"
    assert record.volume_id == "volume-1"
    assert record.source_file_hash == "fixture-hash"
    assert record.source_file_size == len(content)
    connection.close()


def test_recovery_closes_move_interrupted_before_rename(tmp_path: Path) -> None:
    """A MOVING row with only matching source becomes failed without mutation."""
    content = b"unchanged bytes"
    source = tmp_path / "source" / "document.pdf"
    destination_directory = tmp_path / "destination"
    source.parent.mkdir()
    destination_directory.mkdir()
    _ = source.write_bytes(content)
    connection = open_database(tmp_path / "state.db")
    insert_document(connection, source, content)
    move_backend = FixtureAtomicMoveBackend(content)
    move_backend.interrupt_before_rename = True
    with pytest.raises(SimulatedCrash):
        _ = execute_atomic_move(
            connection,
            make_request(make_ticket(source, destination_directory)),
            backend=move_backend,
        )

    connection.close()
    connection = open_database(tmp_path / "state.db")
    with pytest.raises(RecoveryBackendError, match="interrupted_before_rename"):
        _ = recover_interrupted_move(
            connection,
            make_recovery_request(),
            backend=FixtureRecoveryBackend(content),
        )

    assert source.read_bytes() == content
    assert not (destination_directory / "moved.pdf").exists()
    assert transaction_states(connection)[-1] == TransactionState.FAILED
    connection.close()
