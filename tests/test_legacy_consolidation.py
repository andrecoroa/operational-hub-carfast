from app.core.post_action import PostAction, decide_post_action
from app.core.return_context import issue_return_context
from app.platform.boundaries import CANONICAL_REGISTRY, decide_canonical_permission
from app.platform.composer import CompositionResult, compose
from app.platform.legacy_catalog import (
    LEGACY_SURFACES,
    LegacyDisposition,
    legacy_inventory_payload,
)
from app.platform.manifest import ModuleState


def test_all_real_manifests_form_one_valid_registry() -> None:
    assert CANONICAL_REGISTRY.codes() == (
        "partners",
        "documents",
        "service_desk",
        "stock",
        "automotive",
    )
    assert CANONICAL_REGISTRY.get("automotive").dependencies == (
        "core",
        "documents",
        "partners",
        "service_desk",
    )


def test_legacy_composition_remains_selected_by_default() -> None:
    legacy = CompositionResult((), (), (), (), source="legacy")
    result = compose(
        legacy=legacy,
        registry=CANONICAL_REGISTRY,
        module_states={code: ModuleState.ACTIVE for code in CANONICAL_REGISTRY.codes()},
        permission_codes={"automotive.fleet.read"},
    )
    assert result is legacy


def test_consolidated_permissions_preserve_exact_legacy_grants() -> None:
    cases = (
        ("partners.records.read", "suppliers.read"),
        ("documents.records.read", "documents.read"),
        ("service_desk.tasks.read", "tasks.read"),
        ("stock.ledger.write", "stock.operate"),
        ("automotive.workshop.read", "workshop.read"),
    )
    for canonical, legacy in cases:
        assert decide_canonical_permission(canonical, {legacy}).allowed
        assert not decide_canonical_permission(canonical, set()).allowed
    assert not decide_canonical_permission("automotive.unknown", {"admin.manage"}).allowed


def test_post_action_contract_is_gated_and_safe() -> None:
    secret = "synthetic-secret"
    token = issue_return_context(secret, path="/v2-clean/fleet", issued_at=100)
    legacy = decide_post_action(
        PostAction.FINISH,
        current_path="/v2-clean/workshop/7",
        logical_fallback="/v2-clean/workshop",
        secret=secret,
        return_token=token,
    )
    assert legacy.destination == "/v2-clean/workshop/7"
    assert legacy.source == "legacy"
    enabled = decide_post_action(
        PostAction.FINISH,
        current_path="/v2-clean/workshop/7",
        logical_fallback="/v2-clean/workshop",
        secret=secret,
        return_token=token,
        enabled=True,
    )
    # The deliberately expired token cannot override the safe logical fallback.
    assert enabled.destination == "/v2-clean/workshop"
    cancel = decide_post_action(
        PostAction.CANCEL,
        current_path="/v2-clean/workshop/7",
        logical_fallback="/v2-clean/workshop",
        secret=secret,
        enabled=True,
    )
    assert not cancel.persist


def test_every_legacy_surface_has_owner_compatibility_and_exit_evidence() -> None:
    assert len(LEGACY_SURFACES) == len({surface.code for surface in LEGACY_SURFACES})
    assert {surface.disposition for surface in LEGACY_SURFACES} <= set(LegacyDisposition)
    assert all(
        surface.owner and surface.compatibility and surface.evidence_required
        for surface in LEGACY_SURFACES
    )
    assert legacy_inventory_payload()[0]["disposition"] == "adapter"
