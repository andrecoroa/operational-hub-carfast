"""Compatibility-first platform composition primitives."""

from app.platform.composer import CompositionResult, compose
from app.platform.manifest import ModuleManifest, ModuleState
from app.platform.policy import PolicyDecision, decide_legacy_permission
from app.platform.registry import ManifestRegistry

__all__ = [
    "CompositionResult",
    "ManifestRegistry",
    "ModuleManifest",
    "ModuleState",
    "PolicyDecision",
    "compose",
    "decide_legacy_permission",
]
