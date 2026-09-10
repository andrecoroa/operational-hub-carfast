from __future__ import annotations

from dataclasses import dataclass

from app.platform.policy import DecisionReason

PARTNER_PERMISSION_LEGACY_MAP: dict[str, frozenset[str]] = {
    "partners.records.read": frozenset(
        {"suppliers.read", "suppliers.write", "stock.read", "stock.manage", "admin.manage"}
    ),
    "partners.records.create": frozenset({"suppliers.write", "admin.manage"}),
    "partners.records.update": frozenset({"suppliers.write", "admin.manage"}),
    "partners.records.configure": frozenset({"suppliers.configuration.manage", "admin.manage"}),
}


@dataclass(frozen=True, slots=True)
class PartnerPolicyDecision:
    allowed: bool
    canonical_permission: str
    matched_legacy_permission: str | None
    reason: DecisionReason


def decide_partner_permission(
    canonical_permission: str, effective_legacy_codes: set[str]
) -> PartnerPolicyDecision:
    mapped = PARTNER_PERMISSION_LEGACY_MAP.get(canonical_permission, frozenset())
    matched = next((code for code in sorted(mapped) if code in effective_legacy_codes), None)
    return PartnerPolicyDecision(
        allowed=matched is not None,
        canonical_permission=canonical_permission,
        matched_legacy_permission=matched,
        reason=(DecisionReason.GRANTED_BY_LEGACY if matched else DecisionReason.DEFAULT_DENY),
    )
