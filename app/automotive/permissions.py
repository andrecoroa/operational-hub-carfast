from app.platform.policy import DecisionReason, PolicyDecision

AUTOMOTIVE_PERMISSION_LEGACY_MAP: dict[str, frozenset[str]] = {
    "automotive.vehicles.read": frozenset({"vehicles.read", "vehicles.write", "admin.manage"}),
    "automotive.vehicles.write": frozenset({"vehicles.write", "admin.manage"}),
    "automotive.fleet.read": frozenset({"vehicles.read", "vehicles.write", "admin.manage"}),
    "automotive.fleet.write": frozenset({"vehicles.write", "admin.manage"}),
    "automotive.workshop.read": frozenset({"workshop.read", "workshop.write", "admin.manage"}),
    "automotive.workshop.write": frozenset({"workshop.write", "admin.manage"}),
    "automotive.sales.read": frozenset(
        {"vehicles.read", "vehicles.write", "fleet.commerce.manage", "admin.manage"}
    ),
    "automotive.sales.write": frozenset(
        {"vehicles.write", "fleet.commerce.manage", "admin.manage"}
    ),
    "automotive.configure": frozenset({"workshop.write", "vehicles.write", "admin.manage"}),
}


def decide_automotive_permission(permission: str, legacy_codes: set[str]) -> PolicyDecision:
    allowed = bool(AUTOMOTIVE_PERMISSION_LEGACY_MAP.get(permission, frozenset()) & legacy_codes)
    return PolicyDecision(
        allowed=allowed,
        permission=permission,
        reason=DecisionReason.GRANTED_BY_LEGACY if allowed else DecisionReason.DEFAULT_DENY,
    )
