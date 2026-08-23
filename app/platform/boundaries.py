"""Canonical read-only catalogue and policy boundary for the modular transition.

Importing this module does not register routers, mutate configuration or enable the
manifest composer. Legacy runtime behaviour remains selected by default.
"""

from __future__ import annotations

from collections.abc import Callable

from app.automotive.manifest import AUTOMOTIVE_MANIFEST
from app.automotive.permissions import decide_automotive_permission
from app.documents.manifest import DOCUMENTS_MANIFEST
from app.documents.permissions import decide_document_permission
from app.partners.manifest import PARTNERS_MANIFEST
from app.partners.permissions import decide_partner_permission
from app.platform.policy import DecisionReason, PolicyDecision, decide_legacy_permission
from app.platform.registry import ManifestRegistry
from app.service_desk.manifest import SERVICE_DESK_MANIFEST
from app.service_desk.permissions import decide_service_desk_permission
from app.stock_domain.manifest import STOCK_MANIFEST
from app.stock_domain.permissions import decide_stock_permission

CANONICAL_MANIFESTS = (
    PARTNERS_MANIFEST,
    DOCUMENTS_MANIFEST,
    SERVICE_DESK_MANIFEST,
    STOCK_MANIFEST,
    AUTOMOTIVE_MANIFEST,
)

CANONICAL_REGISTRY = ManifestRegistry(CANONICAL_MANIFESTS)

PermissionDecider = Callable[[str, set[str]], PolicyDecision]


def _decide_partner(permission: str, legacy_codes: set[str]) -> PolicyDecision:
    decision = decide_partner_permission(permission, legacy_codes)
    return PolicyDecision(
        allowed=decision.allowed,
        permission=permission,
        reason=(
            DecisionReason.GRANTED_BY_LEGACY if decision.allowed else DecisionReason.DEFAULT_DENY
        ),
    )


PERMISSION_DECIDERS: dict[str, PermissionDecider] = {
    "partners": _decide_partner,
    "documents": decide_document_permission,
    "service_desk": decide_service_desk_permission,
    "stock": decide_stock_permission,
    "automotive": decide_automotive_permission,
}


def decide_canonical_permission(permission: str, legacy_codes: set[str]) -> PolicyDecision:
    """Evaluate one canonical permission through its exact legacy adapter.

    Unknown canonical namespaces and unknown capabilities default-deny. Existing
    legacy permissions retain their current membership semantics.
    """

    namespace = permission.partition(".")[0]
    decider = PERMISSION_DECIDERS.get(namespace)
    if decider is not None:
        return decider(permission, legacy_codes)
    return decide_legacy_permission(permission, legacy_codes)
