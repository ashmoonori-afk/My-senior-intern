# Copyright (c) 2026 My Senior Intern contributors

"""Typed contracts shared by move orchestration and persistence."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Protocol

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
    rolling_back_at: str
    rolled_back_at: str
    rollback_failed_at: str

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
            TransactionState.ROLLING_BACK: self.rolling_back_at,
            TransactionState.ROLLED_BACK: self.rolled_back_at,
            TransactionState.ROLLBACK_FAILED: self.rollback_failed_at,
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

    @property
    def source_path(self) -> Path:
        """Return the identity-bound source path."""
        return self.ticket.source_file.path

    @property
    def destination_path(self) -> Path:
        """Return the nominated destination path."""
        return self.ticket.destination_directory.path / self.destination_name


class MoveContext(Protocol):
    """Persistence inputs shared by live moves and restart recovery."""

    @property
    def transaction_id(self) -> TransactionId:
        """Return the durable transaction identifier."""
        ...

    @property
    def document_id(self) -> DocumentId:
        """Return the durable document identifier."""
        ...

    @property
    def audit_event_id(self) -> AuditEventId:
        """Return the audit event identifier for this operation."""
        ...

    @property
    def timeline(self) -> MoveTimeline:
        """Return the operation lifecycle timestamps."""
        ...

    @property
    def source_path(self) -> Path:
        """Return the original source path."""
        ...

    @property
    def destination_path(self) -> Path:
        """Return the planned destination path."""
        ...


class RollbackContext(MoveContext, Protocol):
    """Persistence context that knows the forward move state."""

    @property
    def forward_state(self) -> TransactionState:
        """Return the durable forward move state being rolled back."""
        ...


@dataclass(frozen=True)
class TransitionOutcome:
    """Optional durable detail attached to one state transition."""

    detail: Mapping[str, DetailValue] | None = None
    error_code: str | None = None
    destination_path: Path | None = None
