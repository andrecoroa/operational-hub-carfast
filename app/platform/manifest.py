"""Versioned, immutable module manifest contracts.

Manifests describe contributions only. They never import routers, models or domain
services, which keeps registry discovery read-only and makes Core independently
importable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ModuleState(StrEnum):
    AVAILABLE = "available"
    ACTIVE = "active"
    DISABLED = "disabled"
    RETIRING = "retiring"


@dataclass(frozen=True, slots=True)
class Contribution:
    code: str
    permission: str | None = None
    capability: str | None = None


@dataclass(frozen=True, slots=True)
class ModuleManifest:
    code: str
    version: str
    capabilities: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    navigation: tuple[Contribution, ...] = ()
    administration: tuple[Contribution, ...] = ()
    settings: tuple[Contribution, ...] = ()
    jobs: tuple[Contribution, ...] = ()

    def validate(self) -> None:
        if not self.code or not self.version:
            raise ValueError("Manifest code and version are required")
        if self.code in self.dependencies:
            raise ValueError(f"Module {self.code!r} cannot depend on itself")
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError(f"Module {self.code!r} contains duplicate capabilities")
        known = set(self.capabilities)
        for group in (self.navigation, self.administration, self.settings, self.jobs):
            codes = [item.code for item in group]
            if len(set(codes)) != len(codes):
                raise ValueError(f"Module {self.code!r} contains duplicate contributions")
            for item in group:
                if item.capability and item.capability not in known:
                    raise ValueError(
                        f"Contribution {item.code!r} uses unknown capability {item.capability!r}"
                    )
