# Copyright (c) 2026 My Senior Intern contributors

"""Move identity and destination-leaf refusal tests."""

from pathlib import Path
from typing import cast

import pytest

from senior_intern.core.database import open_database
from senior_intern.core.models import TransactionState
from senior_intern.fileops.mover import MoveBackendError, execute_atomic_move
from tests.unit.fileops.move_test_support import (
    FixtureAtomicMoveBackend,
    insert_document,
    make_request,
    make_ticket,
    transaction_states,
)


def test_stale_ticket_fails_before_rename(tmp_path: Path) -> None:
    """Configured stale identity records failure without mutation."""
    content = b"source bytes"
    source = tmp_path / "source" / "document.pdf"
    destination_directory = tmp_path / "destination"
    source.parent.mkdir()
    destination_directory.mkdir()
    _ = source.write_bytes(content)
    connection = open_database(tmp_path / "state.db")
    insert_document(connection, source, content)
    backend = FixtureAtomicMoveBackend(content)
    backend.fail_revalidation = True

    with pytest.raises(MoveBackendError, match="identity_changed"):
        _ = execute_atomic_move(
            connection,
            make_request(make_ticket(source, destination_directory)),
            backend=backend,
        )

    assert source.read_bytes() == content
    assert transaction_states(connection) == [
        TransactionState.PLANNED,
        TransactionState.VALIDATED,
        TransactionState.MOVING,
        TransactionState.FAILED,
    ]
    connection.close()


def test_same_path_replacement_fails_identity_revalidation(tmp_path: Path) -> None:
    """Replacing the object behind a path never moves the replacement."""
    original_content = b"original bytes"
    replacement_content = b"replacement bytes"
    source = tmp_path / "source" / "document.pdf"
    destination_directory = tmp_path / "destination"
    source.parent.mkdir()
    destination_directory.mkdir()
    _ = source.write_bytes(original_content)
    ticket = make_ticket(source, destination_directory)
    original = source.parent / "original.pdf"
    _ = source.rename(original)
    _ = source.write_bytes(replacement_content)
    connection = open_database(tmp_path / "state.db")
    insert_document(connection, source, replacement_content)

    with pytest.raises(MoveBackendError, match="identity_changed"):
        _ = execute_atomic_move(
            connection,
            make_request(ticket),
            backend=FixtureAtomicMoveBackend(replacement_content),
        )

    assert source.read_bytes() == replacement_content
    assert original.read_bytes() == original_content
    assert transaction_states(connection)[-1] == TransactionState.FAILED
    connection.close()


@pytest.mark.parametrize(
    "destination_name",
    [
        "",
        ".",
        "..",
        "../escape.pdf",
        "a/b.pdf",
        "a\\b.pdf",
        "report.pdf:stream",
        "report.pdf.",
        "report.pdf ",
        "CON",
        "con.txt",
        "LPT9.xlsx",
        "a?.pdf",
        "a\0.pdf",
        "a\x01.pdf",
    ],
)
def test_invalid_destination_leaf_is_rejected_before_transaction(
    tmp_path: Path,
    destination_name: str,
) -> None:
    """Only one plain cross-platform leaf reaches persistence."""
    content = b"source bytes"
    source = tmp_path / "source" / "document.pdf"
    destination_directory = tmp_path / "destination"
    source.parent.mkdir()
    destination_directory.mkdir()
    _ = source.write_bytes(content)
    connection = open_database(tmp_path / "state.db")
    insert_document(connection, source, content)
    backend = FixtureAtomicMoveBackend(content)

    with pytest.raises(ValueError, match="destination_name"):
        _ = execute_atomic_move(
            connection,
            make_request(make_ticket(source, destination_directory), destination_name),
            backend=backend,
        )

    count = cast(
        "tuple[int] | None",
        connection.execute("SELECT COUNT(*) FROM move_transactions").fetchone(),
    )
    assert count is not None
    assert tuple(count) == (0,)
    assert source.read_bytes() == content
    assert backend.calls == []
    connection.close()
