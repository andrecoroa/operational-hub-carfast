"""Feature-gated contribution composer with legacy selected by default."""

from __future__ import annotations

from dataclasses import dataclass

from app.platform.manifest import Contribution, ModuleState
from app.platform.registry import ManifestRegistry


@dataclass(frozen=True, slots=True)
class CompositionResult:
    navigation: tuple[Contribution, ...]
    administration: tuple[Contribution, ...]
    settings: tuple[Contribution, ...]
    jobs: tuple[Contribution, ...]
    source: str


def compose(
    *,
    legacy: CompositionResult,
    registry: ManifestRegistry,
    module_states: dict[str, ModuleState],
    permission_codes: set[str],
    enabled: bool = False,
) -> CompositionResult:
    if not enabled:
        return legacy

    buckets: dict[str, list[Contribution]] = {
        "navigation": [],
        "administration": [],
        "settings": [],
        "jobs": [],
    }
    for manifest in registry:
        if module_states.get(manifest.code, ModuleState.AVAILABLE) is not ModuleState.ACTIVE:
            continue
        for name in buckets:
            for contribution in getattr(manifest, name):
                if contribution.permission and contribution.permission not in permission_codes:
                    continue
                buckets[name].append(contribution)
    return CompositionResult(
        navigation=tuple(buckets["navigation"]),
        administration=tuple(buckets["administration"]),
        settings=tuple(buckets["settings"]),
        jobs=tuple(buckets["jobs"]),
        source="manifest",
    )
