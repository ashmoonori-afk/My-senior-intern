# Copyright (c) 2026 My Senior Intern contributors

"""Immutable domain models shared by rules and analysis."""

from enum import StrEnum
from typing import Annotated, ClassVar, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError

from senior_intern.core.ids import (
    CategoryId,
    DocumentId,
    EvidenceId,
    parse_category_id,
    parse_document_id,
    parse_evidence_id,
)


class TransactionState(StrEnum):
    """Durable move transaction lifecycle."""

    PLANNED = "planned"
    VALIDATED = "validated"
    MOVING = "moving"
    MOVED = "moved"
    VERIFIED = "verified"
    COMMITTED = "committed"
    ROLLBACK_REQUIRED = "rollback_required"
    FAILED = "failed"


class ClassificationProposal(BaseModel):
    """Untrusted LLM classification data before policy evaluation."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True, strict=True)

    document_id: DocumentId
    proposed_category_id: CategoryId
    evidence_ids: tuple[EvidenceId, ...]
    confidence: Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
    uncertainty: Annotated[str, Field(max_length=500)]
    requires_review: bool

    @field_validator("document_id", mode="before")
    @classmethod
    def validate_document_id(cls, value: object) -> DocumentId:
        """Parse the opaque document ID at the provider boundary."""
        if not isinstance(value, str):
            code = "document_id_type"
            message = "document_id must be text"
            raise PydanticCustomError(code, message)
        return parse_document_id(value)

    @field_validator("proposed_category_id", mode="before")
    @classmethod
    def validate_category_id(cls, value: object) -> CategoryId:
        """Parse the opaque category ID at the provider boundary."""
        if not isinstance(value, str):
            code = "proposed_category_id_type"
            message = "proposed_category_id must be text"
            raise PydanticCustomError(code, message)
        return parse_category_id(value)

    @field_validator("evidence_ids", mode="before")
    @classmethod
    def validate_evidence_ids(cls, value: object) -> tuple[EvidenceId, ...]:
        """Parse every opaque evidence ID at the provider boundary."""
        if not isinstance(value, (list, tuple)):
            code = "evidence_ids_type"
            message = "evidence_ids must be a list"
            raise PydanticCustomError(code, message)
        items = cast("list[object] | tuple[object, ...]", value)
        parsed: list[EvidenceId] = []
        for item in items:
            if not isinstance(item, str):
                code = "evidence_id_type"
                message = "every evidence_id must be text"
                raise PydanticCustomError(code, message)
            parsed.append(parse_evidence_id(item))
        return tuple(parsed)
