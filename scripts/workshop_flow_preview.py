"""Run the workshop flow against an isolated synthetic SQLite fixture."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path


PREVIEW_ROOT = Path(
    os.environ.get("CARFAST_WORKSHOP_PREVIEW_ROOT", ".workshop-flow-preview")
).resolve()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
PREVIEW_ROOT.mkdir(parents=True, exist_ok=True)
(PREVIEW_ROOT / "documents").mkdir(parents=True, exist_ok=True)
os.environ.setdefault(
    "DATABASE_URL", f"sqlite+pysqlite:///{(PREVIEW_ROOT / 'fixture.db').as_posix()}"
)
os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("APP_SECRET_KEY", "synthetic-workshop-preview-only")
os.environ.setdefault("DOCUMENT_ARCHIVE_ROOT", str(PREVIEW_ROOT / "documents"))
os.environ.setdefault("VISUAL_FOUNDATION_ENABLED", "true")
os.environ.setdefault("EMAIL_INBOUND_ENABLED", "false")
os.environ.setdefault("EMAIL_OUTBOUND_ENABLED", "false")

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, User, Vehicle  # noqa: E402
from app.models.workshop_phased import (  # noqa: E402
    WorkshopPhasedProcess,
    WorkshopPhasedProcessPhase,
)
from app.services.bootstrap import seed_initial_data  # noqa: E402
from app.services.users import create_user  # noqa: E402


PREVIEW_EMAIL = "preview.oficina@carfast.local"
PREVIEW_PASSWORD = "Preview123!"
PREVIEW_PLATE = "QA-26-OF"
PHASES = (
    ("entrada", "Entrada", "completed"),
    ("validacao", "Validação Administrativa", "completed"),
    ("diagnostico", "Diagnóstico Técnico", "in_progress"),
    ("inspecao", "Inspeção Técnica", "pending"),
    ("auditoria", "Auditoria e Validação", "pending"),
    ("reparacao", "Reparação", "pending"),
    ("fecho", "Validação e Fecho", "pending"),
)


def prepare_fixture() -> int:
    """Create or refresh one deterministic process containing no real data."""

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_initial_data(db)
        user = db.scalar(select(User).where(User.email == PREVIEW_EMAIL))
        if not user:
            user = create_user(
                db,
                name="Responsável Oficina Preview",
                email=PREVIEW_EMAIL,
                password=PREVIEW_PASSWORD,
                role_codes=["admin"],
                organizational_unit_codes=["carfast"],
            )
            db.flush()

        vehicle = db.scalar(select(Vehicle).where(Vehicle.plate == PREVIEW_PLATE))
        if not vehicle:
            vehicle = Vehicle(
                plate=PREVIEW_PLATE,
                vin="SYNTHETICWORKSHOPPREVIEW26",
                brand="CarFast",
                model="Viatura de demonstração",
                year=2026,
                lifecycle_status="active",
                operational_status="in_workshop",
                rentway_km=48210,
                active=True,
                notes="Registo exclusivamente sintético para validação local.",
            )
            db.add(vehicle)
            db.flush()

        process = db.scalar(
            select(WorkshopPhasedProcess).where(
                WorkshopPhasedProcess.creation_mode == "synthetic_workshop_preview"
            )
        )
        if not process:
            process = WorkshopPhasedProcess(
                public_reference="OF-PREVIEW-2026",
                opened_at=datetime.now(UTC),
                process_type="general",
                title="Revisão programada — demonstração",
                creation_mode="synthetic_workshop_preview",
                status="active",
                vehicle_id=vehicle.id,
                plate_snapshot=vehicle.plate,
                current_phase_code="diagnostico",
                priority="normal",
                origin="local_preview",
                origin_detail="Ambiente sintético e isolado",
                initial_km=48210,
                initial_observation="Confirmar manutenção e diagnóstico eletrónico.",
                responsible_user_id=user.id,
                created_by_id=user.id,
                received_at=datetime.now(UTC),
                metadata_json={"operational_situation": "in_progress"},
            )
            db.add(process)
            db.flush()
            for sort_order, (code, name, status) in enumerate(PHASES, start=1):
                db.add(
                    WorkshopPhasedProcessPhase(
                        process_id=process.id,
                        phase_code=code,
                        name=name,
                        status=status,
                        sort_order=sort_order,
                        data_json={},
                    )
                )
        else:
            process.status = "active"
            process.current_phase_code = "diagnostico"
            process.vehicle_id = vehicle.id
            process.responsible_user_id = user.id
            process.metadata_json = {"operational_situation": "in_progress"}
        db.commit()
        return process.id


PROCESS_ID = prepare_fixture()


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("CARFAST_WORKSHOP_PREVIEW_PORT", "18767"))
    print(f"Workshop preview: http://127.0.0.1:{port}/login")
    print(f"Processo: /v2-clean/workshop/diagnostico?process_id={PROCESS_ID}#relatorios")
    print(f"Utilizador: {PREVIEW_EMAIL} / {PREVIEW_PASSWORD}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
