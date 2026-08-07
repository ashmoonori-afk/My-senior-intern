# Copyright (c) 2026 My Senior Intern contributors

"""Opaque identifiers exposed across trust boundaries."""

import re
from typing import NewType

DocumentId = NewType("DocumentId", str)
CategoryId = NewType("CategoryId", str)
RuleId = NewType("RuleId", str)
FolderTemplateId = NewType("FolderTemplateId", str)
EvidenceId = NewType("EvidenceId", str)
TransactionId = NewType("TransactionId", str)
AuditEventId = NewType("AuditEventId", str)


def _parse_opaque_id(value: str, *, field: str, prefix: str) -> str:
    pattern = rf"{prefix}_[A-Za-z0-9]{{10,64}}"
    if re.fullmatch(pattern, value) is None:
        msg = f"{field} must be an opaque {prefix}_ identifier"
        raise ValueError(msg)
    return value


def parse_document_id(value: str) -> DocumentId:
    """Parse an untrusted document identifier."""
    return DocumentId(_parse_opaque_id(value, field="document_id", prefix="doc"))


def parse_category_id(value: str) -> CategoryId:
    """Parse an untrusted category identifier."""
    return CategoryId(_parse_opaque_id(value, field="category_id", prefix="cat"))


def parse_evidence_id(value: str) -> EvidenceId:
    """Parse an untrusted evidence identifier."""
    return EvidenceId(_parse_opaque_id(value, field="evidence_id", prefix="evi"))


def parse_rule_id(value: str) -> RuleId:
    """Parse an untrusted rule identifier."""
    return RuleId(_parse_opaque_id(value, field="rule_id", prefix="rul"))


def parse_folder_template_id(value: str) -> FolderTemplateId:
    """Parse an untrusted folder-template identifier."""
    return FolderTemplateId(_parse_opaque_id(value, field="folder_template_id", prefix="tpl"))


def parse_transaction_id(value: str) -> TransactionId:
    """Parse an untrusted transaction identifier."""
    return TransactionId(_parse_opaque_id(value, field="transaction_id", prefix="txn"))


def parse_audit_event_id(value: str) -> AuditEventId:
    """Parse an untrusted audit-event identifier."""
    return AuditEventId(_parse_opaque_id(value, field="audit_event_id", prefix="aud"))
