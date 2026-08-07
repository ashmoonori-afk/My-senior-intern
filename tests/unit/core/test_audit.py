# Copyright (c) 2026 My Senior Intern contributors

"""Append-only audit and transaction-event tests."""

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import cast

import pytest

from senior_intern.core.audit import (
    AuditEventInput,
    append_audit_event,
    append_transaction_event,
)
from senior_intern.core.database import open_database
from senior_intern.core.ids import AuditEventId, DocumentId, TransactionId
from senior_intern.core.migrations import LATEST_SCHEMA_VERSION
from senior_intern.core.models import TransactionState


def _names(connection: sqlite3.Connection, kind: str) -> set[str]:
    rows = cast(
        "list[tuple[object, ...]]",
        connection.execute(
            "SELECT name FROM sqlite_master WHERE type = ? ORDER BY name",
            (kind,),
        ).fetchall(),
    )
    names: set[str] = set()
    for row in rows:
        name = row[0]
        assert isinstance(name, str)
        names.add(name)
    return names


def _seed_transaction(connection: sqlite3.Connection) -> TransactionId:
    document_id = DocumentId("doc_01HZX7F5K2")
    transaction_id = TransactionId("txn_01HZX7F5K2")
    _ = connection.execute(
        """
        INSERT INTO documents (
            document_id,
            current_path,
            file_hash,
            file_size,
            file_type,
            modified_at,
            discovered_at,
            extraction_status,
            classification_status,
            security_flags_json,
            review_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document_id,
            "source.docx",
            "a" * 64,
            10,
            "docx",
            "2026-08-07T00:00:00Z",
            "2026-08-07T00:00:00Z",
            "pending",
            "pending",
            "[]",
            "pending",
        ),
    )
    _ = connection.execute(
        """
        INSERT INTO move_transactions (
            transaction_id,
            document_id,
            source_path,
            destination_path,
            state,
            planned_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            transaction_id,
            document_id,
            "source.docx",
            "destination.docx",
            TransactionState.PLANNED,
            "2026-08-07T00:00:00Z",
        ),
    )
    return transaction_id


def test_version_two_creates_append_only_tables_and_triggers(tmp_path: Path) -> None:
    """Migration 2 installs both immutable event streams."""
    connection = open_database(tmp_path / "audit.db")
    try:
        assert LATEST_SCHEMA_VERSION == 2
        assert {"audit_events", "move_transaction_events"} <= _names(connection, "table")
        assert {
            "audit_events_no_update",
            "audit_events_no_delete",
            "move_transaction_events_no_update",
            "move_transaction_events_no_delete",
        } <= _names(connection, "trigger")
    finally:
        connection.close()


def test_audit_events_are_canonical_and_digest_linked(tmp_path: Path) -> None:
    """Every append records canonical payload and the previous event digest."""
    connection = open_database(tmp_path / "audit.db")
    try:
        first = append_audit_event(
            connection,
            AuditEventInput(
                event_id=AuditEventId("aud_01HZX7F5K2"),
                event_type="run_started",
                occurred_at="2026-08-07T00:00:00Z",
                actor="scheduled_worker",
                payload={"z": 2, "a": 1},
            ),
        )
        second = append_audit_event(
            connection,
            AuditEventInput(
                event_id=AuditEventId("aud_01HZX7F5K3"),
                event_type="run_finished",
                occurred_at="2026-08-07T00:01:00Z",
                actor="scheduled_worker",
                payload={"moved": 0},
            ),
        )

        assert first.payload_json == '{"a":1,"z":2}'
        assert first.previous_digest is None
        assert len(first.event_digest) == 64
        first_material = json.dumps(
            {
                "actor": "scheduled_worker",
                "document_id": None,
                "event_id": "aud_01HZX7F5K2",
                "event_type": "run_started",
                "occurred_at": "2026-08-07T00:00:00Z",
                "payload_json": '{"a":1,"z":2}',
                "previous_digest": None,
                "transaction_id": None,
            },
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        assert first.event_digest == hashlib.sha256(first_material.encode("utf-8")).hexdigest()
        assert second.previous_digest == first.event_digest
        assert len(second.event_digest) == 64
        assert second.event_digest != first.event_digest
    finally:
        connection.close()


def test_audit_rows_cannot_be_updated_or_deleted(tmp_path: Path) -> None:
    """Even direct SQL cannot rewrite or remove recorded audit history."""
    connection = open_database(tmp_path / "audit.db")
    try:
        event = append_audit_event(
            connection,
            AuditEventInput(
                event_id=AuditEventId("aud_01HZX7F5K2"),
                event_type="run_started",
                occurred_at="2026-08-07T00:00:00Z",
                actor="scheduled_worker",
                payload={},
            ),
        )

        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            _ = connection.execute(
                "UPDATE audit_events SET event_type = ? WHERE sequence = ?",
                ("changed", event.sequence),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            _ = connection.execute(
                "DELETE FROM audit_events WHERE sequence = ?",
                (event.sequence,),
            )
    finally:
        connection.close()


def test_transaction_events_are_append_only_and_state_checked(tmp_path: Path) -> None:
    """Transaction history accepts known states and rejects mutation."""
    connection = open_database(tmp_path / "audit.db")
    try:
        transaction_id = _seed_transaction(connection)
        event = append_transaction_event(
            connection,
            transaction_id=transaction_id,
            state=TransactionState.PLANNED,
            recorded_at="2026-08-07T00:00:00Z",
            detail={"reason": "approved_rule"},
        )

        assert event.state is TransactionState.PLANNED
        assert event.detail_json == '{"reason":"approved_rule"}'
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            _ = connection.execute(
                "UPDATE move_transaction_events SET state = ? WHERE sequence = ?",
                (TransactionState.FAILED, event.sequence),
            )
        with pytest.raises(sqlite3.IntegrityError):
            _ = connection.execute(
                """
                INSERT INTO move_transaction_events (
                    transaction_id,
                    state,
                    recorded_at,
                    detail_json
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    transaction_id,
                    "deleted",
                    "2026-08-07T00:00:01Z",
                    "{}",
                ),
            )
    finally:
        connection.close()
