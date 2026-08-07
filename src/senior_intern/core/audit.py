# Copyright (c) 2026 My Senior Intern contributors

"""Append-only transaction and audit records."""

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from typing import ClassVar, cast

from pydantic import BaseModel, ConfigDict

from senior_intern.core.ids import (
    AuditEventId,
    DocumentId,
    TransactionId,
    parse_audit_event_id,
    parse_document_id,
    parse_transaction_id,
)
from senior_intern.core.models import TransactionState

type JsonScalar = str | int | float | bool | None
type AuditPayload = Mapping[str, JsonScalar]


class AuditEvent(BaseModel):
    """One immutable user-visible audit event."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True, strict=True)

    sequence: int
    event_id: AuditEventId
    event_type: str
    transaction_id: TransactionId | None
    document_id: DocumentId | None
    occurred_at: str
    actor: str
    payload_json: str
    previous_digest: str | None
    event_digest: str


class AuditEventInput(BaseModel):
    """Validated input for one audit append."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True, strict=True)

    event_id: AuditEventId
    event_type: str
    transaction_id: TransactionId | None = None
    document_id: DocumentId | None = None
    occurred_at: str
    actor: str
    payload: dict[str, JsonScalar]


class TransactionEvent(BaseModel):
    """One immutable transaction-state observation."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True, strict=True)

    sequence: int
    transaction_id: TransactionId
    state: TransactionState
    recorded_at: str
    detail_json: str


class AuditWriteError(RuntimeError):
    """An append did not produce a durable sequence number."""


def _canonical_json(payload: AuditPayload) -> str:
    return json.dumps(
        dict(payload),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _previous_digest(connection: sqlite3.Connection) -> str | None:
    row = cast(
        "tuple[object, ...] | None",
        connection.execute(
            "SELECT event_digest FROM audit_events ORDER BY sequence DESC LIMIT 1"
        ).fetchone(),
    )
    if row is None:
        return None
    digest = row[0]
    if not isinstance(digest, str):
        message = "stored audit digest must be text"
        raise AuditWriteError(message)
    return digest


def _audit_digest(
    event: AuditEventInput,
    *,
    payload_json: str,
    previous_digest: str | None,
) -> str:
    material = _canonical_json(
        {
            "actor": event.actor,
            "document_id": None if event.document_id is None else str(event.document_id),
            "event_id": str(event.event_id),
            "event_type": event.event_type,
            "occurred_at": event.occurred_at,
            "payload_json": payload_json,
            "previous_digest": previous_digest,
            "transaction_id": (None if event.transaction_id is None else str(event.transaction_id)),
        }
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _last_sequence(cursor: sqlite3.Cursor) -> int:
    sequence = cursor.lastrowid
    if sequence is None:
        message = "SQLite did not return an audit sequence"
        raise AuditWriteError(message)
    return sequence


def append_audit_event(
    connection: sqlite3.Connection,
    event_input: AuditEventInput,
) -> AuditEvent:
    """Append one digest-linked audit event."""
    parsed_event_id = parse_audit_event_id(str(event_input.event_id))
    parsed_transaction_id = (
        None
        if event_input.transaction_id is None
        else parse_transaction_id(str(event_input.transaction_id))
    )
    parsed_document_id = (
        None if event_input.document_id is None else parse_document_id(str(event_input.document_id))
    )
    validated_input = AuditEventInput(
        event_id=parsed_event_id,
        event_type=event_input.event_type,
        transaction_id=parsed_transaction_id,
        document_id=parsed_document_id,
        occurred_at=event_input.occurred_at,
        actor=event_input.actor,
        payload=event_input.payload,
    )
    payload_json = _canonical_json(validated_input.payload)

    _ = connection.execute("BEGIN IMMEDIATE")
    try:
        previous_digest = _previous_digest(connection)
        event_digest = _audit_digest(
            validated_input,
            payload_json=payload_json,
            previous_digest=previous_digest,
        )
        cursor = connection.execute(
            """
            INSERT INTO audit_events (
                event_id,
                event_type,
                transaction_id,
                document_id,
                occurred_at,
                actor,
                payload_json,
                previous_digest,
                event_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                validated_input.event_id,
                validated_input.event_type,
                validated_input.transaction_id,
                validated_input.document_id,
                validated_input.occurred_at,
                validated_input.actor,
                payload_json,
                previous_digest,
                event_digest,
            ),
        )
        audit_event = AuditEvent(
            sequence=_last_sequence(cursor),
            event_id=validated_input.event_id,
            event_type=validated_input.event_type,
            transaction_id=validated_input.transaction_id,
            document_id=validated_input.document_id,
            occurred_at=validated_input.occurred_at,
            actor=validated_input.actor,
            payload_json=payload_json,
            previous_digest=previous_digest,
            event_digest=event_digest,
        )
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return audit_event


def append_transaction_event(
    connection: sqlite3.Connection,
    *,
    transaction_id: TransactionId,
    state: TransactionState,
    recorded_at: str,
    detail: AuditPayload,
) -> TransactionEvent:
    """Append one immutable transaction-state event."""
    parsed_transaction_id = parse_transaction_id(str(transaction_id))
    detail_json = _canonical_json(detail)

    _ = connection.execute("BEGIN IMMEDIATE")
    try:
        cursor = connection.execute(
            """
            INSERT INTO move_transaction_events (
                transaction_id,
                state,
                recorded_at,
                detail_json
            ) VALUES (?, ?, ?, ?)
            """,
            (parsed_transaction_id, state, recorded_at, detail_json),
        )
        event = TransactionEvent(
            sequence=_last_sequence(cursor),
            transaction_id=parsed_transaction_id,
            state=state,
            recorded_at=recorded_at,
            detail_json=detail_json,
        )
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return event
