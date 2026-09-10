from app.platform.policy import DecisionReason, PolicyDecision

DOCUMENT_PERMISSION_LEGACY_MAP: dict[str, frozenset[str]] = {
    "documents.records.read": frozenset({"documents.read", "documents.write", "admin.manage"}),
    "documents.records.create": frozenset({"documents.write", "admin.manage"}),
    "documents.records.update": frozenset({"documents.write", "admin.manage"}),
    "documents.records.link": frozenset({"documents.write", "admin.manage"}),
    "documents.records.configure": frozenset({"admin.manage"}),
    "documents.retention.configure": frozenset({"admin.manage"}),
}


def decide_document_permission(
    canonical_permission: str, effective_legacy_codes: set[str]
) -> PolicyDecision:
    mapped = DOCUMENT_PERMISSION_LEGACY_MAP.get(canonical_permission, frozenset())
    allowed = bool(mapped.intersection(effective_legacy_codes))
    return PolicyDecision(
        allowed=allowed,
        permission=canonical_permission,
        reason=(DecisionReason.GRANTED_BY_LEGACY if allowed else DecisionReason.DEFAULT_DENY),
    )
