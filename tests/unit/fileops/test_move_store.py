# Copyright (c) 2026 My Senior Intern contributors

"""Move store identity and lifecycle contract tests."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from senior_intern.core.database import open_database
from senior_intern.core.models import TransactionState
from senior_intern.fileops.move_store import record_plan, transition
from senior_intern.fileops.move_types import MovePersistenceError, MoveRequest
from tests.unit.fileops.move_test_support import (
    insert_document,
    make_request,
    make_ticket,
    transaction_states,
)


def test_store_rejects_illegal_transition_and_request_mismatch(tmp_path: Path) -> None:
    """Stored identity and lifecycle cannot be bypassed."""
    content = b"source bytes"
    source = tmp_path / "source" / "document.pdf"
    destination_directory = tmp_path / "destination"
    source.parent.mkdir()
    destination_directory.mkdir()
    _ = source.write_bytes(content)
    connection = open_database(tmp_path / "state.db")
    insert_document(connection, source, content)
    request = make_request(make_ticket(source, destination_directory))
    destination = destination_directory / request.destination_name
    record_plan(connection, request, destination)

    with pytest.raises(MovePersistenceError, match="invalid move transition"):
        transition(connection, request, TransactionState.MOVED)
    with pytest.raises(MovePersistenceError, match="requires destination_path"):
        transition(connection, request, TransactionState.COMMITTED)
    tampered_request = request.model_copy(update={"destination_name": "tampered.pdf"})
    with pytest.raises(MovePersistenceError, match="does not match"):
        transition(connection, tampered_request, TransactionState.VALIDATED)

    assert transaction_states(connection) == [TransactionState.PLANNED]
    connection.close()


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("transaction_id", "not-a-transaction"),
        ("document_id", "not-a-document"),
        ("audit_event_id", "not-an-audit-event"),
    ],
)
def test_move_request_rejects_malformed_branded_ids(
    tmp_path: Path,
    field: str,
    invalid_value: str,
) -> None:
    """Strict move inputs preserve every opaque identifier boundary."""
    source = tmp_path / "source" / "document.pdf"
    destination_directory = tmp_path / "destination"
    source.parent.mkdir()
    destination_directory.mkdir()
    _ = source.write_bytes(b"source bytes")
    payload = make_request(make_ticket(source, destination_directory)).model_dump()
    payload[field] = invalid_value

    with pytest.raises(ValidationError):
        _ = MoveRequest.model_validate(payload)
