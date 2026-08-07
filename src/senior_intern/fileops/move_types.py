# Copyright (c) 2026 My Senior Intern contributors

"""Typed contracts shared by move orchestration and persistence."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, field_validator

from senior_intern.core.ids import (
    AuditEventId,
    DocumentId,
    TransactionId,
    parse_audit_event_id,
    parse_document_id,
    parse_transaction_id,
)
from senior_intern.core.models import TransactionState
from senior_intern.fileops.path_policy import SafePathTicket

type DetailValue = str | int | float | bool | None


class MovePersistenceError(RuntimeError):
    """Stored move state violates the transaction contract."""


class MoveTimeline(BaseModel):
    """Caller-owned timestamps for every durable lifecycle event."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True, strict=True)

    planned_at: str
    validated_at: str
    moving_at: str
    moved_at: str
    verified_at: str
    committed_at: str
    failed_at: str
    rollback_required_at: str

    def for_state(self, state: TransactionState) -> str:
        """Return the timestamp dedicated to one lifecycle state."""
        return {
            TransactionState.PLANNED: self.planned_at,
            TransactionState.VALIDATED: self.validated_at,
            TransactionState.MOVING: self.moving_at,
            TransactionState.MOVED: self.moved_at,
            TransactionState.VERIFIED: self.verified_at,
            TransactionState.COMMITTED: self.committed_at,
            TransactionState.FAILED: self.failed_at,
            TransactionState.ROLLBACK_REQUIRED: self.rollback_required_at,
        }[state]


class MoveRequest(BaseModel):
    """Validated inputs for one automatic move."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True, strict=True)

    transaction_id: TransactionId
    document_id: DocumentId
    audit_event_id: AuditEventId
    ticket: SafePathTicket
    destination_name: str
    timeline: MoveTimeline

    @field_validator("transaction_id")
    @classmethod
    def validate_transaction_id(cls, value: TransactionId) -> TransactionId:
        """Require the branded transaction identifier."""
        return parse_transaction_id(str(value))

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, value: DocumentId) -> DocumentId:
        """Require the branded document identifier."""
        return parse_document_id(str(value))

    @field_validator("audit_event_id")
    @classmethod
    def validate_audit_event_id(cls, value: AuditEventId) -> AuditEventId:
        """Require the branded audit identifier."""
        return parse_audit_event_id(str(value))


@dataclass(frozen=True)
class TransitionOutcome:
    """Optional durable detail attached to one state transition."""

    detail: Mapping[str, DetailValue] | None = None
    error_code: str | None = None
    destination_path: Path | None = None
