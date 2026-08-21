import json
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.models import Base
from app.models.evolution import EvolutionRecord, EvolutionRecordHistory
from app.services.evolution_catalog_importer import import_evolution_catalog, load_catalog

CATALOG = Path(__file__).resolve().parents[1] / "data" / "evolution_catalog_2026-08-21.json"


def _database() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_catalog_has_unique_keys_and_daily_management_program() -> None:
    items = load_catalog(CATALOG)
    keys = {item.external_key for item in items}

    assert len(keys) == len(items)
    assert "daily-management.program" in keys
    daily = [item for item in items if item.external_key.startswith("daily-management.")]
    assert len(daily) == 10
    assert all(
        item.factual_state in {"proposta aprovada", "apenas mockup/estudo"}
        for item in daily
    )
    assert all(
        item.external_key == "daily-management.program"
        or item.program_key == "daily-management.program"
        for item in daily
    )
    by_key = {item.external_key: item for item in daily}
    assert by_key["daily-management.event-layer"].status == "approved"
    assert by_key["daily-management.event-layer"].priority == "high"
    assert by_key["daily-management.shift-handover"].status == "approved"
    assert by_key["daily-management.shift-handover"].priority == "normal"
    assert by_key["daily-management.ai-recommendations"].status == "deferred"
    assert by_key["daily-management.ai-recommendations"].priority == "low"


def test_import_is_dry_run_by_default_and_idempotent_when_applied() -> None:
    items = load_catalog(CATALOG)
    db = _database()
    try:
        preview = import_evolution_catalog(db, items)
        assert preview.dry_run is True
        assert preview.created == len(items)
        assert db.scalar(select(func.count()).select_from(EvolutionRecord)) == 0

        applied = import_evolution_catalog(db, items, apply=True)
        db.commit()
        assert applied.created == len(items)
        assert applied.updated == 0
        assert db.scalar(select(func.count()).select_from(EvolutionRecord)) == len(items)

        repeated = import_evolution_catalog(db, items, apply=True)
        db.commit()
        assert repeated.created == 0
        assert repeated.updated == 0
        assert repeated.ignored == len(items)
    finally:
        db.close()


def test_managed_record_updates_with_history_and_title_duplicate_is_ignored(tmp_path: Path) -> None:
    original = load_catalog(CATALOG)[0]
    payload = [
        {
            **json.loads(CATALOG.read_text(encoding="utf-8"))[0],
            "description": "Descrição atualizada pelo catálogo.",
        }
    ]
    changed_path = tmp_path / "changed.json"
    changed_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    db = _database()
    try:
        import_evolution_catalog(db, [original], apply=True)
        db.commit()
        changed = import_evolution_catalog(db, load_catalog(changed_path), apply=True)
        db.commit()
        assert changed.updated == 1
        assert db.scalar(select(func.count()).select_from(EvolutionRecordHistory)) >= 1

        db.add(
            EvolutionRecord(
                record_type="improvement",
                module="Outro módulo",
                title="Duplicado conservador",
                description="Existente",
                origin="manual",
                priority="normal",
                status="registered",
            )
        )
        db.commit()
        duplicate_payload = [
            {
                "external_key": "test.duplicate",
                "title": "Duplicado conservador",
                "description": "Não substituir.",
                "module": "Outro módulo",
                "factual_state": "proposta aprovada",
                "record_type": "future_implementation",
                "status": "approved",
                "priority": "normal",
                "sources": ["teste"],
                "dependencies": [],
                "next_step": "Rever manualmente.",
            }
        ]
        duplicate_path = tmp_path / "duplicate.json"
        duplicate_path.write_text(json.dumps(duplicate_payload), encoding="utf-8")
        report = import_evolution_catalog(db, load_catalog(duplicate_path), apply=True)
        db.commit()
        assert report.ignored == 1
        assert db.scalar(select(func.count()).select_from(EvolutionRecord)) == 2
    finally:
        db.close()
