"""Read-only in-memory registry for validated module manifests."""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from app.platform.manifest import ModuleManifest


class ManifestRegistry:
    def __init__(self, manifests: Iterable[ModuleManifest] = ()) -> None:
        registered: dict[str, ModuleManifest] = {}
        for manifest in manifests:
            manifest.validate()
            if manifest.code in registered:
                raise ValueError(f"Duplicate module manifest: {manifest.code}")
            registered[manifest.code] = manifest
        for manifest in registered.values():
            missing = set(manifest.dependencies) - set(registered) - {"core"}
            if missing:
                raise ValueError(
                    f"Module {manifest.code!r} has unavailable dependencies: {sorted(missing)}"
                )
        self._manifests = registered

    def __iter__(self) -> Iterator[ModuleManifest]:
        return iter(self._manifests.values())

    def get(self, code: str) -> ModuleManifest | None:
        return self._manifests.get(code)

    def codes(self) -> tuple[str, ...]:
        return tuple(self._manifests)
