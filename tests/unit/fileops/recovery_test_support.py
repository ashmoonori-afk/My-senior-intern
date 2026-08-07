# Copyright (c) 2026 My Senior Intern contributors

"""Shared fixtures for crash recovery and undo tests."""

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import cast

from senior_intern.core.database import open_database
from senior_intern.core.ids import AuditEventId
from senior_intern.fileops.move_types import MoveTimeline
from senior_intern.fileops.mover import execute_atomic_move
from senior_intern.fileops.recovery_types import (
    EndpointDisposition,
    RecoveryBackendError,
    RecoveryRecord,
    RecoveryRequest,
)
from tests.unit.fileops.move_test_support import (
    TRANSACTION_ID,
    FixtureAtomicMoveBackend,
    SimulatedCrash,
    insert_document,
    make_request,
    make_ticket,
)

RECOVERY_EVENT_ID = AuditEventId("aud_klmnopqrst")
RECOVERY_TIMELINE = MoveTimeline(
    planned_at="2026-08-07T04:00:00Z",
    validated_at="2026-08-07T04:00:01Z",
    moving_at="2026-08-07T04:00:02Z",
    moved_at="2026-08-07T04:00:03Z",
    verified_at="2026-08-07T04:00:04Z",
    committed_at="2026-08-07T04:00:05Z",
    failed_at="2026-08-07T04:00:06Z",
    rollback_required_at="2026-08-07T04:00:07Z",
    rolling_back_at="2026-08-07T04:00:08Z",
    rolled_back_at="2026-08-07T04:00:09Z",
    rollback_failed_at="2026-08-07T04:00:10Z",
)


class FixtureRecoveryBackend:
    """Identity-bound fixture recovery backend."""

    expected_content: bytes
    fail_destination_verification: bool
    fail_source_verification: bool
    interrupt_after_rollback: bool
    before_rollback_hook: Callable[[], None] | None
    seen_records: list[RecoveryRecord]
    calls: list[str]

    def __init__(self, expected_content: bytes) -> None:
        """Create one successful recovery backend."""
        self.expected_content = expected_content
        self.fail_destination_verification = False
        self.fail_source_verification = False
        self.interrupt_after_rollback = False
        self.before_rollback_hook = None
        self.seen_records = []
        self.calls = []

    def classify_endpoints(self, record: RecoveryRecord) -> EndpointDisposition:
        """Classify exactly one matching endpoint or ambiguity."""
        self.calls.append("classify_endpoints")
        self.seen_records.append(record)
        source_matches = self._matches(record.source_path, record.source_object_id)
        destination_matches = self._matches(
            record.destination_path,
            record.source_object_id,
        )
        if source_matches and not record.destination_path.exists():
            return EndpointDisposition.SOURCE
        if destination_matches and not record.source_path.exists():
            return EndpointDisposition.DESTINATION
        return EndpointDisposition.AMBIGUOUS

    def rollback_no_replace(self, record: RecoveryRecord) -> None:
        """Move destination back only when the source leaf is vacant."""
        self.calls.append("rollback_no_replace")
        if self.before_rollback_hook is not None:
            self.before_rollback_hook()
        if record.source_path.exists():
            error_code = "source_exists"
            raise RecoveryBackendError(error_code)
        if not self._matches(record.destination_path, record.source_object_id):
            error_code = "identity_changed"
            raise RecoveryBackendError(error_code)
        _ = record.destination_path.rename(record.source_path)
        if self.interrupt_after_rollback:
            raise SimulatedCrash

    def verify_source(self, record: RecoveryRecord) -> bool:
        """Verify the restored fixture without changing it."""
        self.calls.append("verify_source")
        return (
            not self.fail_source_verification
            and self._matches(record.source_path, record.source_object_id)
            and not record.destination_path.exists()
            and record.source_path.read_bytes() == self.expected_content
        )

    def verify_destination(self, record: RecoveryRecord) -> bool:
        """Verify a move completed before interruption."""
        self.calls.append("verify_destination")
        return (
            not self.fail_destination_verification
            and self._matches(record.destination_path, record.source_object_id)
            and not record.source_path.exists()
            and record.destination_path.read_bytes() == self.expected_content
        )

    @staticmethod
    def _matches(path: Path, object_id: str) -> bool:
        if not path.is_file():
            return False
        path_stat = path.stat()
        return object_id == f"{path_stat.st_dev}:{path_stat.st_ino}"


def make_recovery_request() -> RecoveryRequest:
    """Build one valid deterministic recovery request."""
    return RecoveryRequest(
        transaction_id=TRANSACTION_ID,
        audit_event_id=RECOVERY_EVENT_ID,
        timeline=RECOVERY_TIMELINE,
    )


def committed_move(
    tmp_path: Path,
) -> tuple[sqlite3.Connection, Path, Path, bytes]:
    """Create one committed fixture move."""
    content = b"unchanged bytes"
    source = tmp_path / "source" / "document.pdf"
    destination_directory = tmp_path / "destination"
    source.parent.mkdir()
    destination_directory.mkdir()
    _ = source.write_bytes(content)
    connection = open_database(tmp_path / "state.db")
    insert_document(connection, source, content)
    _ = execute_atomic_move(
        connection,
        make_request(make_ticket(source, destination_directory)),
        backend=FixtureAtomicMoveBackend(content),
    )
    return connection, source, destination_directory / "moved.pdf", content


def rollback_states(connection: sqlite3.Connection) -> list[str]:
    """Return rollback states in append order."""
    rows = cast(
        "list[tuple[object, ...]]",
        connection.execute(
            """
            SELECT state FROM move_rollback_events
            WHERE transaction_id = ? ORDER BY sequence
            """,
            (TRANSACTION_ID,),
        ).fetchall(),
    )
    return [str(row[0]) for row in rows]


def audit_event_summaries(
    connection: sqlite3.Connection,
) -> list[tuple[str, str, str]]:
    """Return audit identity, type, and actor in append order."""
    rows = cast(
        "list[sqlite3.Row]",
        connection.execute(
            "SELECT event_id, event_type, actor FROM audit_events ORDER BY sequence"
        ).fetchall(),
    )
    return [
        (
            cast("str", row[0]),
            cast("str", row[1]),
            cast("str", row[2]),
        )
        for row in rows
    ]
