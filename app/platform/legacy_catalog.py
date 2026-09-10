"""Versioned classification of compatibility surfaces still active in Phase 9."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class LegacyDisposition(StrEnum):
    CANONICAL = "canonical"
    ADAPTER = "adapter"
    HISTORICAL_READ_ONLY = "historical_read_only"
    RETIREMENT_CANDIDATE = "retirement_candidate"


@dataclass(frozen=True, slots=True)
class LegacySurface:
    code: str
    kind: str
    disposition: LegacyDisposition
    owner: str
    compatibility: str
    evidence_required: str


LEGACY_SURFACES = (
    LegacySurface(
        "partners.stock_suppliers",
        "table",
        LegacyDisposition.ADAPTER,
        "partners",
        "Physical table and foreign keys remain unchanged behind PartnersFacade.",
        "ID/link reconciliation for every consumer before any storage proposal.",
    ),
    LegacySurface(
        "documents.legacy_workflow_status",
        "column semantics",
        LegacyDisposition.ADAPTER,
        "documents",
        "Derived clean workflow values continue through legacy_workflow_values().",
        "State-by-state differential and retention/legal approval.",
    ),
    LegacySurface(
        "service_desk.email_intakes",
        "table family",
        LegacyDisposition.ADAPTER,
        "service_desk",
        "Inbound intake remains accepted while canonical email records own lifecycle.",
        "Message/attachment/hash reconciliation and zero unexplained writes.",
    ),
    LegacySurface(
        "service_desk.legacy_routes",
        "routes and templates",
        LegacyDisposition.HISTORICAL_READ_ONLY,
        "service_desk",
        "URLs remain reachable under existing authorization and experience gate.",
        "Usage telemetry, post-action parity and explicit functional approval.",
    ),
    LegacySurface(
        "automotive.workshop_processes",
        "table family",
        LegacyDisposition.ADAPTER,
        "automotive",
        "Legacy and phased Workshop processes coexist; neither is rewritten.",
        "Process/phase/responsible/date/action/history reconciliation.",
    ),
    LegacySurface(
        "automotive.legacy_routes",
        "routes and templates",
        LegacyDisposition.HISTORICAL_READ_ONLY,
        "automotive",
        "Existing Fleet, Workshop and Sales URLs remain unchanged.",
        "Usage telemetry and equivalent gated destinations.",
    ),
    LegacySurface(
        "platform.permission_aliases",
        "permission mappings",
        LegacyDisposition.ADAPTER,
        "core",
        "Canonical decisions delegate to exact legacy grant sets and default deny.",
        "Full profile differential with no effective-access delta.",
    ),
    LegacySurface(
        "platform.clean_and_legacy_navigation",
        "navigation",
        LegacyDisposition.ADAPTER,
        "core",
        "Legacy composition stays selected unless the existing gate is enabled.",
        "Route/link snapshot equality with gate off; authorized parity with gate on.",
    ),
)


def legacy_surface(code: str) -> LegacySurface | None:
    return next((surface for surface in LEGACY_SURFACES if surface.code == code), None)


def legacy_inventory_payload() -> list[dict[str, Any]]:
    return [
        {
            "code": surface.code,
            "kind": surface.kind,
            "disposition": surface.disposition.value,
            "owner": surface.owner,
            "compatibility": surface.compatibility,
            "evidence_required": surface.evidence_required,
        }
        for surface in LEGACY_SURFACES
    ]
