from pathlib import Path

import pytest

from app.platform.reconciliation import (
    ReconciliationMetric,
    RehearsalReport,
    object_evidence,
)
from scripts.run_phase10_rehearsal import validate_isolated_target


def test_rehearsal_guard_accepts_only_local_test_postgresql() -> None:
    assert (
        validate_isolated_target(
            "test", "postgresql+psycopg://carfast:carfast@localhost:5432/carfast_test"
        )
        == "carfast_test"
    )
    with pytest.raises(ValueError):
        validate_isolated_target(
            "production", "postgresql+psycopg://carfast:secret@localhost/carfast_test"
        )
    with pytest.raises(ValueError):
        validate_isolated_target(
            "test", "postgresql+psycopg://carfast:secret@production.example/carfast_test"
        )
    with pytest.raises(ValueError):
        validate_isolated_target("test", "postgresql+psycopg://carfast:secret@localhost/carfast")


def test_count_reconciliation_rejects_unexplained_deltas() -> None:
    exact = ReconciliationMetric("documents", 4, 4)
    expected_insert = ReconciliationMetric("reference.permissions", 10, 12, expected_delta=2)
    unexplained = ReconciliationMetric("tasks", 3, 2)
    assert exact.reconciled
    assert expected_insert.reconciled
    assert not unexplained.reconciled
    assert not RehearsalReport("synthetic", "memory", (exact, unexplained)).reconciled


def test_document_object_evidence_checks_hash_size_and_accessibility(tmp_path: Path) -> None:
    document = tmp_path / "synthetic-document.pdf"
    document.write_bytes(b"synthetic-not-a-real-customer-document")
    before = object_evidence(document)
    after = object_evidence(document)
    assert before.accessible
    assert before.size == after.size
    assert before.sha256 == after.sha256
    assert not object_evidence(tmp_path / "missing.pdf").accessible
