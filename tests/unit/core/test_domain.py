# Copyright (c) 2026 My Senior Intern contributors

"""Safety domain contract tests."""

import pytest
from pydantic import ValidationError

from senior_intern.core.ids import (
    CategoryId,
    DocumentId,
    EvidenceId,
    FolderTemplateId,
    RuleId,
    TransactionId,
    parse_category_id,
    parse_document_id,
    parse_evidence_id,
    parse_folder_template_id,
    parse_rule_id,
    parse_transaction_id,
)
from senior_intern.core.models import ClassificationProposal, TransactionState
from senior_intern.core.policy import (
    BoundaryPolicy,
    MoveMode,
    ProviderFallbackPolicy,
    default_safety_policy,
)


def test_opaque_identifiers_accept_only_their_expected_prefix() -> None:
    """Opaque IDs cannot carry paths or cross a branded ID boundary."""
    assert parse_document_id("doc_01HZX7F5K2") == DocumentId("doc_01HZX7F5K2")
    assert parse_category_id("cat_01HZX7F5K2") == CategoryId("cat_01HZX7F5K2")
    assert parse_evidence_id("evi_01HZX7F5K2") == EvidenceId("evi_01HZX7F5K2")
    assert parse_rule_id("rul_01HZX7F5K2") == RuleId("rul_01HZX7F5K2")
    assert parse_folder_template_id("tpl_01HZX7F5K2") == FolderTemplateId("tpl_01HZX7F5K2")
    assert parse_transaction_id("txn_01HZX7F5K2") == TransactionId("txn_01HZX7F5K2")

    for invalid in (
        "cat_01HZX7F5K2",
        r"C:\Users\Robin\document.docx",
        "../../document.docx",
        "doc_with spaces",
        "doc_short",
    ):
        with pytest.raises(ValueError, match="document_id"):
            _ = parse_document_id(invalid)


def test_transaction_state_contract_is_complete() -> None:
    """The durable journal exposes every user-required recovery state."""
    assert {state.value for state in TransactionState} == {
        "planned",
        "validated",
        "moving",
        "moved",
        "verified",
        "committed",
        "rollback_required",
        "failed",
    }


def test_default_safety_policy_is_fail_closed() -> None:
    """Defaults cannot silently cross a boundary or grant LLM capabilities."""
    policy = default_safety_policy()

    assert policy.move_mode is MoveMode.SAME_FILESYSTEM_ATOMIC_RENAME
    assert policy.cross_volume is BoundaryPolicy.BLOCK
    assert policy.network_locations is BoundaryPolicy.BLOCK
    assert policy.cloud_locations is BoundaryPolicy.BLOCK
    assert policy.symlinks is BoundaryPolicy.BLOCK
    assert policy.provider_fallback is ProviderFallbackPolicy.DISABLED
    assert not policy.llm_filesystem_access
    assert not policy.llm_shell_access
    assert not policy.llm_tool_access


def test_default_safety_policy_is_immutable() -> None:
    """A worker cannot alter the safety baseline after loading it."""
    policy = default_safety_policy()

    with pytest.raises(ValidationError, match="Instance is frozen"):
        policy.__setattr__("move_mode", MoveMode.SAME_FILESYSTEM_ATOMIC_RENAME)


def test_llm_proposal_rejects_paths_commands_and_unknown_fields() -> None:
    """The proposal schema is closed and cannot represent executable actions."""
    payload = {
        "document_id": "doc_01HZX7F5K2",
        "proposed_category_id": "cat_01HZX7F5K2",
        "evidence_ids": ["evi_01HZX7F5K2"],
        "confidence": 0.95,
        "uncertainty": "",
        "requires_review": False,
        "arbitrary_path": r"C:\external",
        "shell_command": "rm -rf /",
    }

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _ = ClassificationProposal.model_validate(payload)


def test_llm_proposal_enforces_branded_identifier_boundaries() -> None:
    """Provider data cannot smuggle a path through an identifier field."""
    payload = {
        "document_id": r"C:\Users\Robin\document.docx",
        "proposed_category_id": "cat_01HZX7F5K2",
        "evidence_ids": ("evi_01HZX7F5K2",),
        "confidence": 0.95,
        "uncertainty": "",
        "requires_review": True,
    }

    with pytest.raises(ValidationError, match="document_id"):
        _ = ClassificationProposal.model_validate(payload)
