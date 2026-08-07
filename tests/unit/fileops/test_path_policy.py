# Copyright (c) 2026 My Senior Intern contributors

"""Fail-closed common filesystem policy tests."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from senior_intern.fileops.path_policy import (
    ObjectKind,
    PathFacts,
    PathPolicyDecision,
    PathPolicyRequest,
    PathProbeError,
    PathRole,
    PolicyDenial,
    evaluate_path_policy,
)


class FakePathProbe:
    """Deterministic path-facts probe."""

    facts: dict[tuple[Path, PathRole], PathFacts]
    failure: PathProbeError | None

    def __init__(
        self,
        facts: dict[tuple[Path, PathRole], PathFacts],
        *,
        failure: PathProbeError | None = None,
    ) -> None:
        self.facts = facts
        self.failure = failure

    def inspect(self, path: Path, role: PathRole) -> PathFacts:
        """Return configured facts or one configured OS error."""
        if self.failure is not None:
            raise self.failure
        return self.facts[(path, role)]


def _safe_facts(
    path: Path,
    role: PathRole,
    *,
    volume_id: str = "volume-1",
) -> PathFacts:
    kind = ObjectKind.FILE if role is PathRole.SOURCE_FILE else ObjectKind.DIRECTORY
    return PathFacts(
        path=path,
        role=role,
        exists=True,
        kind=kind,
        filesystem_type="ntfs",
        volume_id=volume_id,
        object_id=f"object-{role.value}",
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


def _safe_request_and_facts(
    tmp_path: Path,
) -> tuple[PathPolicyRequest, dict[tuple[Path, PathRole], PathFacts]]:
    root = tmp_path / "root"
    source = root / "document.pdf"
    destination = tmp_path / "destination"
    request = PathPolicyRequest(
        source_root=root,
        source_file=source,
        destination_directory=destination,
    )
    facts = {
        (root, PathRole.SOURCE_ROOT): _safe_facts(root, PathRole.SOURCE_ROOT),
        (source, PathRole.SOURCE_FILE): _safe_facts(source, PathRole.SOURCE_FILE),
        (destination, PathRole.DESTINATION_DIRECTORY): _safe_facts(
            destination,
            PathRole.DESTINATION_DIRECTORY,
        ),
    }
    return request, facts


def test_complete_same_volume_local_facts_are_allowed(tmp_path: Path) -> None:
    """Only complete, stable, local, supported same-volume facts get a ticket."""
    request, facts = _safe_request_and_facts(tmp_path)

    decision = evaluate_path_policy(request, probe=FakePathProbe(facts))

    assert decision.allowed
    assert decision.denial is None
    assert decision.ticket is not None
    assert decision.ticket.source_file.object_id == "object-source_file"


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("exists", False, PolicyDenial.NOT_FOUND),
        ("is_link", True, PolicyDenial.LINK),
        ("no_follow_chain", False, PolicyDenial.LINK),
        ("within_source_root", False, PolicyDenial.ESCAPES_ROOT),
        ("crosses_mount", True, PolicyDenial.MOUNT_INDIRECTION),
        ("filesystem_type", "exfat", PolicyDenial.UNSUPPORTED_FILESYSTEM),
        ("is_local", False, PolicyDenial.NONLOCAL_VOLUME),
        ("is_network", True, PolicyDenial.NETWORK_LOCATION),
        ("is_cloud", True, PolicyDenial.CLOUD_LOCATION),
        ("is_placeholder", True, PolicyDenial.PLACEHOLDER),
        ("identity_stable", False, PolicyDenial.UNSTABLE_IDENTITY),
        (
            "supports_no_replace",
            False,
            PolicyDenial.REQUIRED_CAPABILITY_MISSING,
        ),
        ("classification_complete", False, PolicyDenial.API_UNAVAILABLE),
    ],
)
def test_each_unsafe_platform_fact_denies(
    tmp_path: Path,
    field: str,
    value: object,
    expected: PolicyDenial,
) -> None:
    """Every unsafe or unknown fact fails closed with one stable reason."""
    request, facts = _safe_request_and_facts(tmp_path)
    key = (request.source_file, PathRole.SOURCE_FILE)
    facts[key] = facts[key].model_copy(update={field: value})

    decision = evaluate_path_policy(request, probe=FakePathProbe(facts))

    assert not decision.allowed
    assert decision.denial is expected
    assert decision.ticket is None


def test_wrong_role_kind_and_volume_mismatch_deny(tmp_path: Path) -> None:
    """Wrong object types and a destination on another volume are rejected."""
    request, facts = _safe_request_and_facts(tmp_path)
    source_key = (request.source_file, PathRole.SOURCE_FILE)
    facts[source_key] = facts[source_key].model_copy(update={"kind": ObjectKind.DIRECTORY})
    wrong_kind = evaluate_path_policy(request, probe=FakePathProbe(facts))
    assert wrong_kind.denial is PolicyDenial.WRONG_TYPE

    request, facts = _safe_request_and_facts(tmp_path)
    destination_key = (request.destination_directory, PathRole.DESTINATION_DIRECTORY)
    facts[destination_key] = facts[destination_key].model_copy(update={"volume_id": "volume-2"})
    wrong_volume = evaluate_path_policy(request, probe=FakePathProbe(facts))
    assert wrong_volume.denial is PolicyDenial.DIFFERENT_VOLUME


def test_source_must_be_lexically_inside_root_without_parent_escape(tmp_path: Path) -> None:
    """Policy never resolves or accepts a source path outside its selected root."""
    root = tmp_path / "root"
    request = PathPolicyRequest(
        source_root=root,
        source_file=tmp_path / "outside.pdf",
        destination_directory=tmp_path / "destination",
    )

    decision = evaluate_path_policy(request, probe=FakePathProbe({}))

    assert decision.denial is PolicyDenial.ESCAPES_ROOT


def test_probe_failure_is_a_closed_api_error(tmp_path: Path) -> None:
    """An OS probe error never becomes an allowed or partial ticket."""
    request, facts = _safe_request_and_facts(tmp_path)

    decision = evaluate_path_policy(
        request,
        probe=FakePathProbe(facts, failure=PathProbeError("probe failed")),
    )

    assert not decision.allowed
    assert decision.denial is PolicyDenial.API_ERROR
    assert decision.ticket is None


def test_decision_rejects_contradictory_allowed_and_denied_states(
    tmp_path: Path,
) -> None:
    """Callers cannot construct an allowed result without exactly one ticket."""
    request, facts = _safe_request_and_facts(tmp_path)
    valid = evaluate_path_policy(request, probe=FakePathProbe(facts))
    assert valid.ticket is not None

    with pytest.raises(ValidationError):
        _ = PathPolicyDecision(allowed=True, denial=None, ticket=None)
    with pytest.raises(ValidationError):
        _ = PathPolicyDecision(
            allowed=False,
            denial=PolicyDenial.LINK,
            ticket=valid.ticket,
        )
