# Copyright (c) 2026 My Senior Intern contributors

"""Durable mover crash and verification boundary tests."""

from pathlib import Path
from typing import cast

import pytest

from senior_intern.core.database import open_database
from senior_intern.core.models import TransactionState
from senior_intern.fileops.move_types import MovePersistenceError
from senior_intern.fileops.mover import MoveBackendError, execute_atomic_move
from tests.unit.fileops.move_test_support import (
    DOCUMENT_ID,
    TRANSACTION_ID,
    FixtureAtomicMoveBackend,
    SimulatedCrash,
    insert_document,
    make_request,
    make_ticket,
    transaction_states,
)


def _prepared_move(
    tmp_path: Path,
) -> tuple[Path, Path, bytes]:
    content = b"source bytes"
    source = tmp_path / "source" / "document.pdf"
    destination_directory = tmp_path / "destination"
    source.parent.mkdir()
    destination_directory.mkdir()
    _ = source.write_bytes(content)
    return source, destination_directory, content


def test_interruption_after_rename_leaves_durable_moving_state(tmp_path: Path) -> None:
    """A post-syscall crash leaves deterministic recovery evidence."""
    source, destination_directory, content = _prepared_move(tmp_path)
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

    assert not source.exists()
    assert (destination_directory / "moved.pdf").read_bytes() == content
    assert transaction_states(connection)[-1] == TransactionState.MOVING
    connection.close()


def test_failed_post_move_verification_requires_rollback(tmp_path: Path) -> None:
    """A moved but unverified object remains durable for recovery."""
    source, destination_directory, content = _prepared_move(tmp_path)
    connection = open_database(tmp_path / "state.db")
    insert_document(connection, source, content)
    backend = FixtureAtomicMoveBackend(content)
    backend.fail_verification = True

    with pytest.raises(MoveBackendError, match="verification_failed"):
        _ = execute_atomic_move(
            connection,
            make_request(make_ticket(source, destination_directory)),
            backend=backend,
        )

    assert not source.exists()
    assert (destination_directory / "moved.pdf").read_bytes() == content
    assert transaction_states(connection)[-1] == TransactionState.ROLLBACK_REQUIRED
    connection.close()


def test_verification_error_records_exact_rollback_detail(tmp_path: Path) -> None:
    """A typed verification error preserves code and document row."""
    source, destination_directory, content = _prepared_move(tmp_path)
    connection = open_database(tmp_path / "state.db")
    insert_document(connection, source, content)
    backend = FixtureAtomicMoveBackend(content)
    backend.verification_error_code = "verification_api_error"

    with pytest.raises(MoveBackendError, match="verification_api_error"):
        _ = execute_atomic_move(
            connection,
            make_request(make_ticket(source, destination_directory)),
            backend=backend,
        )

    assert transaction_states(connection) == [
        TransactionState.PLANNED,
        TransactionState.VALIDATED,
        TransactionState.MOVING,
        TransactionState.MOVED,
        TransactionState.ROLLBACK_REQUIRED,
    ]
    transaction_row = cast(
        "tuple[str, str] | None",
        connection.execute(
            "SELECT state, error_code FROM move_transactions WHERE transaction_id = ?",
            (TRANSACTION_ID,),
        ).fetchone(),
    )
    document_row = cast(
        "tuple[str, str | None] | None",
        connection.execute(
            "SELECT current_path, move_transaction_id FROM documents WHERE document_id = ?",
            (DOCUMENT_ID,),
        ).fetchone(),
    )
    assert transaction_row is not None
    assert tuple(transaction_row) == (
        TransactionState.ROLLBACK_REQUIRED,
        "verification_api_error",
    )
    assert document_row is not None
    assert tuple(document_row) == (str(source), None)
    connection.close()


def test_concurrent_document_path_change_is_never_overwritten(tmp_path: Path) -> None:
    """Commit refuses to clobber state changed after planning."""
    source, destination_directory, content = _prepared_move(tmp_path)
    database_path = tmp_path / "state.db"
    connection = open_database(database_path)
    insert_document(connection, source, content)
    concurrent_path = tmp_path / "other-owner.pdf"

    def change_document_path() -> None:
        concurrent = open_database(database_path)
        _ = concurrent.execute(
            "UPDATE documents SET current_path = ? WHERE document_id = ?",
            (str(concurrent_path), DOCUMENT_ID),
        )
        concurrent.close()

    backend = FixtureAtomicMoveBackend(content)
    backend.verification_hook = change_document_path
    with pytest.raises(MovePersistenceError, match="document path changed"):
        _ = execute_atomic_move(
            connection,
            make_request(make_ticket(source, destination_directory)),
            backend=backend,
        )

    row = cast(
        "tuple[str] | None",
        connection.execute(
            "SELECT current_path FROM documents WHERE document_id = ?",
            (DOCUMENT_ID,),
        ).fetchone(),
    )
    assert row is not None
    assert tuple(row) == (str(concurrent_path),)
    assert transaction_states(connection)[-1] == TransactionState.VERIFIED
    connection.close()
