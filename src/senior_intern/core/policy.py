# Copyright (c) 2026 My Senior Intern contributors

"""Fail-closed safety policy."""

from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict


class MoveMode(StrEnum):
    """Permitted automatic file-move mechanism."""

    SAME_FILESYSTEM_ATOMIC_RENAME = "same_filesystem_atomic_rename"


class BoundaryPolicy(StrEnum):
    """Default handling for unsafe filesystem boundaries."""

    BLOCK = "block"


class ProviderFallbackPolicy(StrEnum):
    """Whether a failed provider may be replaced automatically."""

    DISABLED = "disabled"


class SafetyPolicy(BaseModel):
    """Immutable policy consumed by every operation."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True, strict=True)

    move_mode: MoveMode
    cross_volume: BoundaryPolicy
    network_locations: BoundaryPolicy
    cloud_locations: BoundaryPolicy
    symlinks: BoundaryPolicy
    provider_fallback: ProviderFallbackPolicy
    llm_filesystem_access: bool
    llm_shell_access: bool
    llm_tool_access: bool


def default_safety_policy() -> SafetyPolicy:
    """Return the immutable product safety baseline."""
    return SafetyPolicy(
        move_mode=MoveMode.SAME_FILESYSTEM_ATOMIC_RENAME,
        cross_volume=BoundaryPolicy.BLOCK,
        network_locations=BoundaryPolicy.BLOCK,
        cloud_locations=BoundaryPolicy.BLOCK,
        symlinks=BoundaryPolicy.BLOCK,
        provider_fallback=ProviderFallbackPolicy.DISABLED,
        llm_filesystem_access=False,
        llm_shell_access=False,
        llm_tool_access=False,
    )
