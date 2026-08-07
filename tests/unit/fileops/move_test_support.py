# Copyright (c) 2026 My Senior Intern contributors

"""Shared fixtures for durable move tests."""

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import cast

from senior_intern.core.ids import AuditEventId, DocumentId, TransactionId
from senior_intern.fileops.move_types import MoveRequest, MoveTimeline
from senior_intern.fileops.mover import MoveBackendError
from senior_intern.fileops.path_policy import (
    ObjectKind,
    PathFacts,
    PathRole,
    SafePathTicket,
)

DOCUMENT_ID = DocumentId("doc_abcdefghij")
TRANSACTION_ID = TransactionId("txn_abcdefghij")
AUDIT_EVENT_ID = AuditEventId("aud_abcdefghij")
TIMELINE = MoveTimeline(
    planned_at="2026-08-07T03:00:00Z",
    validated_at="2026-08-07T03:00:01Z",
    moving_at="2026-08-07T03:00:02Z",
    moved_at="2026-08-07T03:00:03Z",
    verified_at="2026-08-07T03:00:04Z",
    committed_at="2026-08-07T03:00:05Z",
    failed_at="2026-08-07T03:00:06Z",
    rollback_required_at="2026-08-07T03:00:07Z",
)


class SimulatedCrash(BaseException):
    """Deterministic process interruption after filesystem mutation."""


class FixtureAtomicMoveBackend:
    """Deterministic fixture backend for the atomic backend boundary."""

    expected_content: bytes
    fail_revalidation: bool
    fail_verification: bool
    verification_error_code: str | None
    interrupt_after_rename: bool
    verification_hook: Callable[[], None] | None
    moved_identity: tuple[int, int] | None
    calls: list[str]

    def __init__(self, expected_content: bytes) -> None:
        """Create a successful backend with optional fault switches."""
        self.expected_content = expected_content
        self.fail_revalidation = False
        self.fail_verification = False
        self.verification_error_code = None
        self.interrupt_after_rename = False
        self.verification_hook = None
        self.moved_identity = None
        self.calls = []

    def revalidate_and_rename_no_replace(
        self,
        ticket: SafePathTicket,
        destination_name: str,
    ) -> None:
        """Revalidate identity and perform one deterministic fixture rename."""
        self.calls.append("revalidate_and_rename_no_replace")
        source_stat = ticket.source_file.path.stat()
        actual_identity = f"{source_stat.st_dev}:{source_stat.st_ino}"
        if self.fail_revalidation or ticket.source_file.object_id != actual_identity:
            error_code = "identity_changed"
            raise MoveBackendError(error_code)
        destination = ticket.destination_directory.path / destination_name
        if destination.exists():
            error_code = "destination_exists"
            raise MoveBackendError(error_code)
        _ = ticket.source_file.path.rename(destination)
        destination_stat = destination.stat()
        self.moved_identity = (destination_stat.st_dev, destination_stat.st_ino)
        if self.moved_identity != (source_stat.st_dev, source_stat.st_ino):
            error_code = "identity_changed"
            raise MoveBackendError(error_code)
        if self.interrupt_after_rename:
            raise SimulatedCrash

    def verify_destination(
        self,
        ticket: SafePathTicket,
        destination_name: str,
    ) -> bool:
        """Verify the fixture endpoint after mutation."""
        self.calls.append("verify_destination")
        if self.verification_hook is not None:
            self.verification_hook()
        if self.verification_error_code is not None:
            raise MoveBackendError(self.verification_error_code)
        destination = ticket.destination_directory.path / destination_name
        return (
            not self.fail_verification
            and not ticket.source_file.path.exists()
            and destination.is_file()
            and destination.read_bytes() == self.expected_content
        )


def _facts(path: Path, role: PathRole, kind: ObjectKind) -> PathFacts:
    object_id = f"object-{role.value}"
    if role is PathRole.SOURCE_FILE:
        path_stat = path.stat()
        object_id = f"{path_stat.st_dev}:{path_stat.st_ino}"
    return PathFacts(
        path=path,
        role=role,
        exists=True,
        kind=kind,
        filesystem_type="ntfs",
        volume_id="volume-1",
        object_id=object_id,
        is_local=True,
        is_network=False,
        is_link=False,
        no_follow_chain=True,
        within_source_root=True,
        is_cloud=False,
        is_placeholder=False,
        crosses_mount=False,
        identity_stable=True,
        supports_no_replace=True,
        classification_complete=True,
    )


def make_ticket(source: Path, destination_directory: Path) -> SafePathTicket:
    """Build one identity-bound fixture ticket."""
    return SafePathTicket(
        source_root=_facts(source.parent, PathRole.SOURCE_ROOT, ObjectKind.DIRECTORY),
        source_file=_facts(source, PathRole.SOURCE_FILE, ObjectKind.FILE),
        destination_directory=_facts(
            destination_directory,
            PathRole.DESTINATION_DIRECTORY,
            ObjectKind.DIRECTORY,
        ),
    )


def insert_document(
    connection: sqlite3.Connection,
    source: Path,
    content: bytes,
) -> None:
    """Insert the durable document row required by a move."""
    _ = connection.execute(
        """
        INSERT INTO documents (
            document_id, current_path, file_hash, file_size, file_type,
            modified_at, discovered_at, extraction_status,
            classification_status, security_flags_json, review_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            DOCUMENT_ID,
            str(source),
            "fixture-hash",
            len(content),
            "pdf",
            TIMELINE.planned_at,
            TIMELINE.planned_at,
            "pending",
            "pending",
            "[]",
            "pending",
        ),
    )


def transaction_states(connection: sqlite3.Connection) -> list[str]:
    """Return lifecycle states in append order."""
    rows = cast(
        "list[tuple[object, ...]]",
        connection.execute(
            """
            SELECT state FROM move_transaction_events
            WHERE transaction_id = ? ORDER BY sequence
            """,
            (TRANSACTION_ID,),
        ).fetchall(),
    )
    return [str(row[0]) for row in rows]


def make_request(
    ticket: SafePathTicket,
    destination_name: str = "moved.pdf",
) -> MoveRequest:
    """Build one valid deterministic move request."""
    return MoveRequest(
        transaction_id=TRANSACTION_ID,
        document_id=DOCUMENT_ID,
        audit_event_id=AUDIT_EVENT_ID,
        ticket=ticket,
        destination_name=destination_name,
        timeline=TIMELINE,
    )
