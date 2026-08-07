# Copyright (c) 2026 My Senior Intern contributors

"""Orchestration for one atomic no-replace move."""

import sqlite3
from pathlib import Path
from typing import ClassVar, Protocol

from pydantic import BaseModel, ConfigDict

from senior_intern.core.ids import DocumentId, TransactionId
from senior_intern.core.models import TransactionState
from senior_intern.fileops.move_store import (
    record_plan as _record_plan,
)
from senior_intern.fileops.move_store import (
    transition as _transition,
)
from senior_intern.fileops.move_types import (
    MoveRequest,
    TransitionOutcome,
)
from senior_intern.fileops.path_policy import SafePathTicket

_WINDOWS_FORBIDDEN_CHARS = frozenset('<>:"/\\|?*')
_WINDOWS_CONTROL_CHAR_LIMIT = 32
_WINDOWS_RESERVED_BASES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


class MoveBackendError(RuntimeError):
    """A platform backend safely refused or failed one operation."""

    code: str

    def __init__(self, code: str) -> None:
        """Create one typed backend refusal."""
        if not code:
            message = "move backend error code must not be empty"
            raise ValueError(message)
        self.code = code
        super().__init__(code)


class AtomicMoveBackend(Protocol):
    """Platform boundary that must provide a single no-replace rename."""

    def revalidate_and_rename_no_replace(
        self,
        ticket: SafePathTicket,
        destination_name: str,
    ) -> None:
        """Revalidate held identities and perform one no-replace rename."""
        ...

    def verify_destination(
        self,
        ticket: SafePathTicket,
        destination_name: str,
    ) -> bool:
        """Verify the post-rename object without reading document contents."""
        ...


class MoveResult(BaseModel):
    """Committed result of one verified move."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True, strict=True)

    transaction_id: TransactionId
    document_id: DocumentId
    source_path: Path
    destination_path: Path


def execute_atomic_move(
    connection: sqlite3.Connection,
    request: MoveRequest,
    *,
    backend: AtomicMoveBackend,
) -> MoveResult:
    """Run one durable move without copy, delete, overwrite, or fallback."""
    _validate_destination_name(request.destination_name)
    source_path = request.ticket.source_file.path
    destination_path = request.ticket.destination_directory.path / request.destination_name
    _record_plan(connection, request, destination_path)

    _transition(connection, request, TransactionState.VALIDATED)
    _transition(connection, request, TransactionState.MOVING)

    try:
        backend.revalidate_and_rename_no_replace(
            request.ticket,
            request.destination_name,
        )
    except MoveBackendError as error:
        _record_failure(connection, request, error)
        raise
    _transition(connection, request, TransactionState.MOVED)

    try:
        verified = backend.verify_destination(
            request.ticket,
            request.destination_name,
        )
    except MoveBackendError as error:
        _record_rollback_required(connection, request, error)
        raise
    if not verified:
        error = MoveBackendError("verification_failed")
        _record_rollback_required(connection, request, error)
        raise error

    _transition(connection, request, TransactionState.VERIFIED)
    _transition(
        connection,
        request,
        TransactionState.COMMITTED,
        TransitionOutcome(destination_path=destination_path),
    )
    return MoveResult(
        transaction_id=request.transaction_id,
        document_id=request.document_id,
        source_path=source_path,
        destination_path=destination_path,
    )


def _validate_destination_name(destination_name: str) -> None:
    reserved_base = destination_name.split(".", maxsplit=1)[0].upper()
    invalid = (
        not destination_name
        or destination_name in {".", ".."}
        or destination_name[-1:] in {".", " "}
        or any(character in _WINDOWS_FORBIDDEN_CHARS for character in destination_name)
        or any(ord(character) < _WINDOWS_CONTROL_CHAR_LIMIT for character in destination_name)
        or reserved_base in _WINDOWS_RESERVED_BASES
        or Path(destination_name).name != destination_name
    )
    if invalid:
        message = "destination_name must be one plain leaf component"
        raise ValueError(message)


def _record_failure(
    connection: sqlite3.Connection,
    request: MoveRequest,
    error: MoveBackendError,
) -> None:
    _transition(
        connection,
        request,
        TransactionState.FAILED,
        TransitionOutcome(
            detail={"error_code": error.code},
            error_code=error.code,
        ),
    )


def _record_rollback_required(
    connection: sqlite3.Connection,
    request: MoveRequest,
    error: MoveBackendError,
) -> None:
    _transition(
        connection,
        request,
        TransactionState.ROLLBACK_REQUIRED,
        TransitionOutcome(
            detail={"error_code": error.code},
            error_code=error.code,
        ),
    )
