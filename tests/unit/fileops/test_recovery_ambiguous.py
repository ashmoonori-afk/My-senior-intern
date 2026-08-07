# Copyright (c) 2026 My Senior Intern contributors

"""Ambiguous crash-recovery endpoint tests."""

import sqlite3
from pathlib import Path

import pytest

from senior_intern.core.database import open_database
from senior_intern.core.models import TransactionState
from senior_intern.fileops.mover import execute_atomic_move
from senior_intern.fileops.recovery import recover_interrupted_move, undo_move
from senior_intern.fileops.recovery_types import RecoveryBackendError
from tests.unit.fileops.move_test_support import (
    FixtureAtomicMoveBackend,
    SimulatedCrash,
    insert_document,
    make_request,
    make_ticket,
    transaction_states,
)
from tests.unit.fileops.recovery_test_support import (
    FixtureRecoveryBackend,
    committed_move,
    make_recovery_request,
    rollback_states,
)


def _interrupted_forward_move(
    tmp_path: Path,
) -> tuple[sqlite3.Connection, Path, Path, bytes]:
    content = b"unchanged bytes"
    source = tmp_path / "source" / "document.pdf"
    destination_directory = tmp_path / "destination"
    source.parent.mkdir()
    destination_directory.mkdir()
    _ = source.write_bytes(content)
    connection = open_database(tmp_path / "state.db")
    insert_document(connection, source, content)
    backend = FixtureAtomicMoveBackend(content)
    backend.interrupt_after_rename = True
    with pytest.raises(SimulatedCrash):
        _ = execute_atomic_move(
            connection,
            make_request(make_ticket(source, destination_directory)),
            backend=backend,
        )
    return connection, source, destination_directory / "moved.pdf", content


@pytest.mark.parametrize("ambiguous_case", ["both", "neither"])
def test_forward_recovery_ambiguous_endpoints_fail_closed(
    tmp_path: Path,
    ambiguous_case: str,
) -> None:
    """Both and neither matching endpoints require rollback without mutation."""
    connection, source, destination, content = _interrupted_forward_move(tmp_path)
    displaced = tmp_path / "displaced.pdf"
    if ambiguous_case == "both":
        _ = source.write_bytes(b"source occupant")
    else:
        _ = destination.rename(displaced)
    source_before = source.read_bytes() if source.exists() else None
    destination_before = destination.read_bytes() if destination.exists() else None

    with pytest.raises(RecoveryBackendError, match="ambiguous_endpoints"):
        _ = recover_interrupted_move(
            connection,
            make_recovery_request(),
            backend=FixtureRecoveryBackend(content),
        )

    assert (source.read_bytes() if source.exists() else None) == source_before
    assert (destination.read_bytes() if destination.exists() else None) == destination_before
    assert transaction_states(connection)[-1] == TransactionState.ROLLBACK_REQUIRED
    connection.close()


def test_resumed_rollback_ambiguous_endpoints_never_renames(tmp_path: Path) -> None:
    """A resumed rollback with both endpoints records failure without mutation."""
    connection, source, destination, content = committed_move(tmp_path)
    interrupted = FixtureRecoveryBackend(content)
    interrupted.interrupt_after_rollback = True
    with pytest.raises(SimulatedCrash):
        _ = undo_move(
            connection,
            make_recovery_request(),
            backend=interrupted,
        )
    _ = destination.write_bytes(b"new destination occupant")
    source_before = source.read_bytes()
    destination_before = destination.read_bytes()
    resumed = FixtureRecoveryBackend(content)

    with pytest.raises(RecoveryBackendError, match="ambiguous_endpoints"):
        _ = undo_move(
            connection,
            make_recovery_request(),
            backend=resumed,
        )

    assert source.read_bytes() == source_before
    assert destination.read_bytes() == destination_before
    assert "rollback_no_replace" not in resumed.calls
    assert rollback_states(connection)[-1] == TransactionState.ROLLBACK_FAILED
    connection.close()
