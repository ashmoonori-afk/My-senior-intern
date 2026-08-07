# Copyright (c) 2026 My Senior Intern contributors

"""Recovery regressions discovered by independent review."""

import sqlite3
from pathlib import Path

import pytest

from senior_intern.core.database import open_database
from senior_intern.core.ids import AuditEventId
from senior_intern.core.models import TransactionState
from senior_intern.fileops.move_types import MovePersistenceError
from senior_intern.fileops.mover import MoveBackendError, execute_atomic_move
from senior_intern.fileops.recovery import undo_move
from senior_intern.fileops.recovery_types import RecoveryBackendError
from tests.unit.fileops.move_test_support import (
    FixtureAtomicMoveBackend,
    insert_document,
    make_request,
    make_ticket,
)
from tests.unit.fileops.recovery_test_support import (
    FixtureRecoveryBackend,
    committed_move,
    make_recovery_request,
    rollback_states,
)


def test_rollback_required_restores_without_document_path_conflict(
    tmp_path: Path,
) -> None:
    """Uncommitted document ownership remains valid after file restoration."""
    content = b"unchanged bytes"
    source = tmp_path / "source" / "document.pdf"
    destination_directory = tmp_path / "destination"
    source.parent.mkdir()
    destination_directory.mkdir()
    _ = source.write_bytes(content)
    connection = open_database(tmp_path / "state.db")
    insert_document(connection, source, content)
    move_backend = FixtureAtomicMoveBackend(content)
    move_backend.fail_verification = True
    with pytest.raises(MoveBackendError, match="verification_failed"):
        _ = execute_atomic_move(
            connection,
            make_request(make_ticket(source, destination_directory)),
            backend=move_backend,
        )

    result = undo_move(
        connection,
        make_recovery_request(),
        backend=FixtureRecoveryBackend(content),
    )

    assert result.restored_path == source
    assert source.read_bytes() == content
    assert rollback_states(connection)[-1] == TransactionState.ROLLED_BACK
    connection.close()


def test_modified_destination_is_blocked_before_undo_mutation(tmp_path: Path) -> None:
    """Undo eligibility verifies unchanged content before rename."""
    connection, source, destination, content = committed_move(tmp_path)
    modified = b"modified after move"
    _ = destination.write_bytes(modified)
    backend = FixtureRecoveryBackend(content)

    with pytest.raises(RecoveryBackendError, match="destination_verification_failed"):
        _ = undo_move(
            connection,
            make_recovery_request(),
            backend=backend,
        )

    assert not source.exists()
    assert destination.read_bytes() == modified
    assert "rollback_no_replace" not in backend.calls
    assert rollback_states(connection)[-1] == TransactionState.ROLLBACK_FAILED
    connection.close()


def test_failed_post_rename_verification_reconciles_on_retry(tmp_path: Path) -> None:
    """A retry classifies restored source instead of renaming twice."""
    connection, source, destination, content = committed_move(tmp_path)
    failing_backend = FixtureRecoveryBackend(content)
    failing_backend.fail_source_verification = True
    with pytest.raises(RecoveryBackendError, match="source_verification_failed"):
        _ = undo_move(
            connection,
            make_recovery_request(),
            backend=failing_backend,
        )
    assert source.read_bytes() == content
    assert not destination.exists()

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


def test_concurrent_undo_attempt_cannot_take_active_ownership(tmp_path: Path) -> None:
    """A second audit identity cannot race one active rollback."""
    connection, source, destination, content = committed_move(tmp_path)
    first_request = make_recovery_request()
    second_request = first_request.model_copy(
        update={"audit_event_id": AuditEventId("aud_uvwxyzABCD")}
    )
    nested_errors: list[MovePersistenceError] = []
    backend = FixtureRecoveryBackend(content)

    def attempt_concurrent_undo() -> None:
        try:
            _ = undo_move(
                connection,
                second_request,
                backend=FixtureRecoveryBackend(content),
            )
        except MovePersistenceError as error:
            nested_errors.append(error)

    backend.before_rollback_hook = attempt_concurrent_undo
    result = undo_move(connection, first_request, backend=backend)

    assert result.restored_path == source
    assert not destination.exists()
    assert len(nested_errors) == 1
    assert "already active" in str(nested_errors[0])
    connection.close()


def test_rollback_events_are_append_only(tmp_path: Path) -> None:
    """Rollback history rejects direct update and deletion."""
    connection, _source, _destination, content = committed_move(tmp_path)
    _ = undo_move(
        connection,
        make_recovery_request(),
        backend=FixtureRecoveryBackend(content),
    )

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        _ = connection.execute("UPDATE move_rollback_events SET detail_json = '{}'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        _ = connection.execute("DELETE FROM move_rollback_events")
    connection.close()
