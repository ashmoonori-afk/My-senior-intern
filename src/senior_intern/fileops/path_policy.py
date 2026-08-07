# Copyright (c) 2026 My Senior Intern contributors

"""Fail-closed filesystem path policy."""

from enum import StrEnum
from pathlib import Path
from typing import ClassVar, Protocol, Self

from pydantic import BaseModel, ConfigDict, model_validator

_PATH_ROLE_COUNT = 3


class PathRole(StrEnum):
    """Expected role for a classified path."""

    SOURCE_ROOT = "source_root"
    SOURCE_FILE = "source_file"
    DESTINATION_DIRECTORY = "destination_directory"


class ObjectKind(StrEnum):
    """Physical object kind returned by a platform probe."""

    FILE = "file"
    DIRECTORY = "directory"
    OTHER = "other"


class PolicyDenial(StrEnum):
    """One stable reason automatic movement is prohibited."""

    INVALID_PATH = "invalid_path"
    NOT_FOUND = "not_found"
    WRONG_TYPE = "wrong_type"
    LINK = "link"
    ESCAPES_ROOT = "escapes_root"
    MOUNT_INDIRECTION = "mount_indirection"
    UNSUPPORTED_FILESYSTEM = "unsupported_filesystem"
    NONLOCAL_VOLUME = "nonlocal_volume"
    NETWORK_LOCATION = "network_location"
    CLOUD_LOCATION = "cloud_location"
    PLACEHOLDER = "placeholder"
    UNSTABLE_IDENTITY = "unstable_identity"
    DIFFERENT_VOLUME = "different_volume"
    REQUIRED_CAPABILITY_MISSING = "required_capability_missing"
    API_UNAVAILABLE = "api_unavailable"
    API_ERROR = "api_error"


class PathProbeError(Exception):
    """Expected platform-classification failure."""


class PathFacts(BaseModel):
    """Complete platform facts for one path."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True, strict=True)

    path: Path
    role: PathRole
    exists: bool
    kind: ObjectKind
    filesystem_type: str
    volume_id: str
    object_id: str
    is_local: bool
    is_network: bool
    is_link: bool
    no_follow_chain: bool
    within_source_root: bool
    is_cloud: bool
    is_placeholder: bool
    crosses_mount: bool
    identity_stable: bool
    supports_no_replace: bool
    classification_complete: bool


class PathProbe(Protocol):
    """Platform-specific, read-only path classification boundary."""

    def inspect(self, path: Path, role: PathRole) -> PathFacts:
        """Return complete facts or raise ``PathProbeError``."""
        ...


class PathPolicyRequest(BaseModel):
    """The three paths required by one proposed move."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True, strict=True)

    source_root: Path
    source_file: Path
    destination_directory: Path


class SafePathTicket(BaseModel):
    """Immutable facts that a future executor must revalidate."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True, strict=True)

    source_root: PathFacts
    source_file: PathFacts
    destination_directory: PathFacts


class PathPolicyDecision(BaseModel):
    """Allowed ticket or one fail-closed denial."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True, strict=True)

    allowed: bool
    denial: PolicyDenial | None
    ticket: SafePathTicket | None

    @model_validator(mode="after")
    def require_consistent_state(self) -> Self:
        """Require exactly one allowed-ticket or denied-reason state."""
        allowed_state = self.denial is None and self.ticket is not None
        denied_state = self.denial is not None and self.ticket is None
        if (self.allowed and not allowed_state) or (not self.allowed and not denied_state):
            msg = "decision must contain exactly one allowed ticket or denied reason"
            raise ValueError(msg)
        return self


def evaluate_path_policy(
    request: PathPolicyRequest,
    *,
    probe: PathProbe,
) -> PathPolicyDecision:
    """Classify a proposed move without touching document contents."""
    denial = _validate_lexical_containment(request)
    requested = (
        (request.source_root, PathRole.SOURCE_ROOT),
        (request.source_file, PathRole.SOURCE_FILE),
        (request.destination_directory, PathRole.DESTINATION_DIRECTORY),
    )
    facts: tuple[PathFacts, ...] = ()
    if denial is None:
        try:
            facts = tuple(probe.inspect(path, role) for path, role in requested)
        except PathProbeError:
            denial = PolicyDenial.API_ERROR

    if denial is None:
        denial = _first_fact_denial(facts, requested)

    ticket: SafePathTicket | None = None
    if denial is None:
        ticket, denial = _build_ticket(facts)

    if denial is not None:
        return _deny(denial)
    if ticket is None:
        return _deny(PolicyDenial.API_ERROR)
    return PathPolicyDecision(allowed=True, denial=None, ticket=ticket)


def _validate_lexical_containment(
    request: PathPolicyRequest,
) -> PolicyDenial | None:
    paths = (
        request.source_root,
        request.source_file,
        request.destination_directory,
    )
    if any(not path.is_absolute() or "\0" in str(path) for path in paths):
        return PolicyDenial.INVALID_PATH
    if any(".." in path.parts for path in paths):
        return PolicyDenial.INVALID_PATH
    try:
        relative_source = request.source_file.relative_to(request.source_root)
    except ValueError:
        return PolicyDenial.ESCAPES_ROOT
    if not relative_source.parts:
        return PolicyDenial.WRONG_TYPE
    return None


def _unsafe_fact_denial(fact: PathFacts) -> PolicyDenial | None:
    checks = (
        (not fact.exists, PolicyDenial.NOT_FOUND),
        (not fact.classification_complete, PolicyDenial.API_UNAVAILABLE),
        (fact.is_link, PolicyDenial.LINK),
        (not fact.no_follow_chain, PolicyDenial.LINK),
        (fact.crosses_mount, PolicyDenial.MOUNT_INDIRECTION),
        (
            fact.filesystem_type.casefold() not in {"ntfs", "refs", "apfs", "hfs"},
            PolicyDenial.UNSUPPORTED_FILESYSTEM,
        ),
        (not fact.is_local, PolicyDenial.NONLOCAL_VOLUME),
        (fact.is_network, PolicyDenial.NETWORK_LOCATION),
        (fact.is_cloud, PolicyDenial.CLOUD_LOCATION),
        (fact.is_placeholder, PolicyDenial.PLACEHOLDER),
        (
            not fact.identity_stable or not fact.object_id or not fact.volume_id,
            PolicyDenial.UNSTABLE_IDENTITY,
        ),
        (
            not fact.supports_no_replace,
            PolicyDenial.REQUIRED_CAPABILITY_MISSING,
        ),
    )
    for failed, denial in checks:
        if failed:
            return denial
    return None


def _first_fact_denial(
    facts: tuple[PathFacts, ...],
    requested: tuple[tuple[Path, PathRole], ...],
) -> PolicyDenial | None:
    if len(facts) != len(requested):
        return PolicyDenial.API_ERROR
    for fact, (path, role) in zip(facts, requested, strict=True):
        if fact.path != path or fact.role is not role:
            return PolicyDenial.API_ERROR
        denial = _unsafe_fact_denial(fact)
        if denial is not None:
            return denial
    return None


def _build_ticket(
    facts: tuple[PathFacts, ...],
) -> tuple[SafePathTicket | None, PolicyDenial | None]:
    if len(facts) != _PATH_ROLE_COUNT:
        return None, PolicyDenial.API_ERROR
    source_root, source_file, destination = facts
    if not source_file.within_source_root:
        return None, PolicyDenial.ESCAPES_ROOT
    expected_kinds = (
        (source_root, ObjectKind.DIRECTORY),
        (source_file, ObjectKind.FILE),
        (destination, ObjectKind.DIRECTORY),
    )
    if any(fact.kind is not expected for fact, expected in expected_kinds):
        return None, PolicyDenial.WRONG_TYPE
    volume_ids = {
        source_root.volume_id,
        source_file.volume_id,
        destination.volume_id,
    }
    if len(volume_ids) != 1:
        return None, PolicyDenial.DIFFERENT_VOLUME
    return (
        SafePathTicket(
            source_root=source_root,
            source_file=source_file,
            destination_directory=destination,
        ),
        None,
    )


def _deny(denial: PolicyDenial) -> PathPolicyDecision:
    return PathPolicyDecision(allowed=False, denial=denial, ticket=None)
