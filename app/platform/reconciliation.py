"""Deterministic reconciliation primitives for isolated migration rehearsals."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ReconciliationMetric:
    code: str
    before: int
    after: int
    expected_delta: int = 0

    @property
    def actual_delta(self) -> int:
        return self.after - self.before

    @property
    def reconciled(self) -> bool:
        return self.actual_delta == self.expected_delta


@dataclass(frozen=True, slots=True)
class ObjectEvidence:
    path: str
    size: int
    sha256: str
    accessible: bool


@dataclass(frozen=True, slots=True)
class RehearsalReport:
    mode: str
    database: str
    metrics: tuple[ReconciliationMetric, ...]
    objects: tuple[ObjectEvidence, ...] = ()

    @property
    def reconciled(self) -> bool:
        return all(metric.reconciled for metric in self.metrics) and all(
            item.accessible for item in self.objects
        )

    def payload(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "database": self.database,
            "reconciled": self.reconciled,
            "metrics": [
                {
                    **asdict(metric),
                    "actual_delta": metric.actual_delta,
                    "reconciled": metric.reconciled,
                }
                for metric in self.metrics
            ],
            "objects": [asdict(item) for item in self.objects],
        }


def object_evidence(path: Path) -> ObjectEvidence:
    try:
        content = path.read_bytes()
    except OSError:
        return ObjectEvidence(str(path), 0, "", False)
    return ObjectEvidence(str(path), len(content), hashlib.sha256(content).hexdigest(), True)
