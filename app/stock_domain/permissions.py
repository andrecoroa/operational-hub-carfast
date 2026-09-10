from app.platform.policy import DecisionReason, PolicyDecision

STOCK_PERMISSION_LEGACY_MAP: dict[str, frozenset[str]] = {
    "stock.articles.read": frozenset(
        {"stock.read", "stock.operate", "stock.manage", "admin.manage"}
    ),
    "stock.ledger.read": frozenset({"stock.read", "stock.operate", "stock.manage", "admin.manage"}),
    "stock.ledger.write": frozenset({"stock.operate", "stock.manage", "admin.manage"}),
    "stock.purchasing.read": frozenset(
        {"stock.read", "stock.orders.manage", "stock.manage", "admin.manage"}
    ),
    "stock.purchasing.write": frozenset({"stock.orders.manage", "stock.manage", "admin.manage"}),
    "stock.inventory.read": frozenset(
        {
            "stock.read",
            "stock.inventory.count",
            "stock.inventory.confirm",
            "stock.manage",
            "admin.manage",
        }
    ),
    "stock.inventory.write": frozenset(
        {"stock.inventory.count", "stock.inventory.confirm", "stock.manage", "admin.manage"}
    ),
    "stock.configure": frozenset({"stock.manage", "admin.manage"}),
}


def decide_stock_permission(permission: str, legacy_codes: set[str]) -> PolicyDecision:
    allowed = bool(STOCK_PERMISSION_LEGACY_MAP.get(permission, frozenset()) & legacy_codes)
    return PolicyDecision(
        allowed=allowed,
        permission=permission,
        reason=DecisionReason.GRANTED_BY_LEGACY if allowed else DecisionReason.DEFAULT_DENY,
    )
