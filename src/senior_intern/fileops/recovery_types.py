# Copyright (c) 2026 My Senior Intern contributors

"""Typed contracts for deterministic move recovery."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import ClassVar, Protocol

from pydantic import BaseModel, ConfigDict, field_validator

from senior_intern.core.ids import (
    AuditEventId,
    DocumentId,
    TransactionId,
    parse_audit_event_id,
    parse_transaction_id,
)
from senior_intern.core.models import TransactionState
from senior_intern.fileops.move_types import MoveTimeline


class EndpointDisposition(StrEnum):
    """Identity-bound location of the moved object."""

    SOURCE = "source"
    DESTINATION = "destination"
    AMBIGUOUS = "ambiguous"


class RecoveryBackendError(RuntimeError):
    """A recovery backend safely refused one operation."""

    code: str

    def __init__(self, code: str) -> None:
        """Create one typed recovery refusal."""
        if not code:
            message = "recovery backend error code must not be empty"
            raise ValueError(message)
        self.code = code
        super().__init__(code)


class RecoveryRecord(BaseModel):
    """Persisted identity evidence for one move."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True, strict=True)

    transaction_id: TransactionId
    document_id: DocumentId
    source_path: Path
    destination_path: Path
    state: TransactionState
    source_root_path: Path
    source_root_object_id: str
    source_object_id: str
    destination_directory_object_id: str
    volume_id: str
    source_file_hash: str
    source_file_size: int
    source_modified_at: str


class RecoveryRequest(BaseModel):
    """Fresh audit identity and timestamps for recovery work."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True, strict=True)

    transaction_id: TransactionId
    audit_event_id: AuditEventId
    timeline: MoveTimeline

    @field_validator("transaction_id")
    @classmethod
    def validate_transaction_id(cls, value: TransactionId) -> TransactionId:
        """Require a branded transaction identifier."""
        return parse_transaction_id(str(value))

    @field_validator("audit_event_id")
    @classmethod
    def validate_audit_event_id(cls, value: AuditEventId) -> AuditEventId:
        """Require a branded audit event identifier."""
        return parse_audit_event_id(str(value))


@dataclass(frozen=True)
class RecoveryContext:
    """Stored transaction association plus fresh recovery metadata."""

    transaction_id: TransactionId
    document_id: DocumentId
    audit_event_id: AuditEventId
    timeline: MoveTimeline
    source_path: Path
    destination_path: Path
    forward_state: TransactionState


class RecoveryBackend(Protocol):
    """Platform boundary for restart classification and rollback."""

    def classify_endpoints(self, record: RecoveryRecord) -> EndpointDisposition:
        """Return one matching endpoint or ambiguity."""
        ...

    def rollback_no_replace(self, record: RecoveryRecord) -> None:
        """Atomically restore destination to a vacant source leaf."""
        ...

    def verify_source(self, record: RecoveryRecord) -> bool:
        """Verify the restored identity."""
        ...

    def verify_destination(self, record: RecoveryRecord) -> bool:
        """Verify the completed move identity."""
        ...


class RecoveryResult(BaseModel):
    """Committed result of restart recovery."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True, strict=True)

    transaction_id: TransactionId
    destination_path: Path


class UndoResult(BaseModel):
    """Committed or already-completed undo result."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True, strict=True)

    transaction_id: TransactionId
    restored_path: Path
