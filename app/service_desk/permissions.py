from app.platform.policy import DecisionReason, PolicyDecision

SERVICE_DESK_PERMISSION_LEGACY_MAP: dict[str, frozenset[str]] = {
    "service_desk.tasks.read": frozenset({"tasks.read", "tasks.write", "admin.manage"}),
    "service_desk.tasks.create": frozenset({"tasks.write", "admin.manage"}),
    "service_desk.tasks.update": frozenset({"tasks.write", "admin.manage"}),
    "service_desk.processes.read": frozenset({"processes.read", "tasks.read", "admin.manage"}),
    "service_desk.processes.update": frozenset({"processes.write", "admin.manage"}),
    "service_desk.email.read": frozenset({"email.read", "email.manage", "admin.manage"}),
    "service_desk.email.reply": frozenset({"email.reply", "email.manage", "admin.manage"}),
    "service_desk.email.manage": frozenset({"email.manage", "admin.manage"}),
    "service_desk.configure": frozenset({"admin.manage"}),
}


def decide_service_desk_permission(permission: str, legacy_codes: set[str]) -> PolicyDecision:
    allowed = bool(SERVICE_DESK_PERMISSION_LEGACY_MAP.get(permission, frozenset()) & legacy_codes)
    return PolicyDecision(
        allowed=allowed,
        permission=permission,
        reason=DecisionReason.GRANTED_BY_LEGACY if allowed else DecisionReason.DEFAULT_DENY,
    )
