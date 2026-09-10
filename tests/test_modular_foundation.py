from __future__ import annotations

import json
import subprocess
import sys

from app.platform.composer import CompositionResult, compose
from app.platform.manifest import Contribution, ModuleManifest, ModuleState
from app.platform.policy import DecisionReason, decide_legacy_permission
from app.platform.registry import ManifestRegistry
from scripts.capture_architecture_baseline import BASELINE_PATH, build_snapshot


def technical_manifest() -> ModuleManifest:
    return ModuleManifest(
        code="technical_probe",
        version="1",
        capabilities=("diagnostics",),
        dependencies=("core",),
        navigation=(
            Contribution(
                "technical_probe.status",
                permission="technical_probe.diagnostics.read",
                capability="diagnostics",
            ),
        ),
        administration=(Contribution("technical_probe.configuration"),),
        settings=(Contribution("technical_probe.enabled"),),
        jobs=(Contribution("technical_probe.health_check"),),
    )


def test_registry_validates_fictitious_technical_manifest() -> None:
    registry = ManifestRegistry([technical_manifest()])
    assert registry.codes() == ("technical_probe",)


def test_composer_keeps_legacy_selected_by_default() -> None:
    legacy = CompositionResult((), (), (), (), source="legacy")
    result = compose(
        legacy=legacy,
        registry=ManifestRegistry([technical_manifest()]),
        module_states={"technical_probe": ModuleState.ACTIVE},
        permission_codes={"technical_probe.diagnostics.read"},
    )
    assert result is legacy


def test_manifest_composer_is_state_and_permission_gated() -> None:
    legacy = CompositionResult((), (), (), (), source="legacy")
    registry = ManifestRegistry([technical_manifest()])
    disabled = compose(
        legacy=legacy,
        registry=registry,
        module_states={"technical_probe": ModuleState.DISABLED},
        permission_codes={"technical_probe.diagnostics.read"},
        enabled=True,
    )
    active = compose(
        legacy=legacy,
        registry=registry,
        module_states={"technical_probe": ModuleState.ACTIVE},
        permission_codes={"technical_probe.diagnostics.read"},
        enabled=True,
    )
    assert disabled.navigation == ()
    assert [item.code for item in active.navigation] == ["technical_probe.status"]
    assert active.source == "manifest"


def test_policy_adapter_exactly_matches_legacy_set_membership() -> None:
    allowed = decide_legacy_permission("tasks.read", {"tasks.read"})
    denied = decide_legacy_permission("tasks.write", {"tasks.read"})
    assert allowed.allowed is True and allowed.reason is DecisionReason.GRANTED_BY_LEGACY
    assert denied.allowed is False and denied.reason is DecisionReason.DEFAULT_DENY


def test_additive_catalogue_models_are_registered() -> None:
    from app.models import Base

    assert {
        "module_definitions",
        "module_capabilities",
        "module_dependencies",
        "installation_modules",
    } <= set(Base.metadata.tables)


def test_core_platform_does_not_import_fictitious_or_real_modules() -> None:
    code = (
        "import sys; import app.platform; "
        "blocked=('app.modules.technical_probe','app.models.tasks','app.models.stock'); "
        "assert not any(name in sys.modules for name in blocked)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_frozen_architecture_baseline_matches() -> None:
    expected = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    assert build_snapshot() == expected
