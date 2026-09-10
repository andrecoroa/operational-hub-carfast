"""Canonical policy-decision result and compatibility adapter.

This slice deliberately evaluates the existing permission set. It changes neither
stored grants nor effective access.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DecisionReason(StrEnum):
    GRANTED_BY_LEGACY = "granted_by_legacy"
    DEFAULT_DENY = "default_deny"


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    permission: str
    reason: DecisionReason


def decide_legacy_permission(permission: str, effective_legacy_codes: set[str]) -> PolicyDecision:
    allowed = permission in effective_legacy_codes
    return PolicyDecision(
        allowed=allowed,
        permission=permission,
        reason=(DecisionReason.GRANTED_BY_LEGACY if allowed else DecisionReason.DEFAULT_DENY),
    )
