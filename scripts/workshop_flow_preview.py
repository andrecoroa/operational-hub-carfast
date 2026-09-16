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
    WorkshopMaterialNeed,
    WorkshopPhasedProcess,
    WorkshopPhasedProcessPhase,
)
from app.services.bootstrap import seed_initial_data  # noqa: E402
from app.services.users import create_user  # noqa: E402


PREVIEW_EMAIL = "preview.oficina@carfast.local"
PREVIEW_PASSWORD = "Preview123!"
PREVIEW_PLATE = "QA-26-OF"
PREVIEW_REPAIR_PLATE = "QA-27-OF"
PHASES = (
    ("entrada", "Entrada", "completed"),
    ("validacao", "Validação Administrativa", "completed"),
    ("diagnostico", "Diagnóstico Técnico", "in_progress"),
    ("inspecao", "Inspeção Técnica", "pending"),
    ("auditoria", "Auditoria e Validação", "pending"),
    ("reparacao", "Reparação", "pending"),
    ("fecho", "Validação e Fecho", "pending"),
)


def prepare_fixture() -> tuple[int, int]:
    """Create or refresh two deterministic processes containing no real data."""

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
                origin="v2_clean",
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
            process.origin = "v2_clean"
            process.metadata_json = {"operational_situation": "in_progress"}

        diagnostic_phase = db.scalar(
            select(WorkshopPhasedProcessPhase).where(
                WorkshopPhasedProcessPhase.process_id == process.id,
                WorkshopPhasedProcessPhase.phase_code == "diagnostico",
            )
        )
        if diagnostic_phase:
            diagnostic_phase.data_json = {
                "form_snapshot": {
                    "diagnostic_problem_detected": "Problema identificado",
                    "diagnostic_problem_title": "Intervalo de manutenção por confirmar",
                    "diagnostic_problem_origin": "Leitura eletrónica e histórico",
                    "diagnostic_problem_evidence": "Divergência sintética criada para demonstração.",
                    "diagnostic_problem_action": "Validar os seis relatórios e confirmar o plano de intervenção.",
                    "diagnostic_closed": "Por confirmar",
                    "diagnostic_priority": "Normal",
                    "diagnostic_conclusion": "Relatórios em recolha; aguarda validação técnica.",
                }
            }

        repair_vehicle = db.scalar(
            select(Vehicle).where(Vehicle.plate == PREVIEW_REPAIR_PLATE)
        )
        if not repair_vehicle:
            repair_vehicle = Vehicle(
                plate=PREVIEW_REPAIR_PLATE,
                vin="SYNTHETICWORKSHOPPREVIEW27",
                brand="CarFast",
                model="Comercial de demonstração",
                year=2025,
                lifecycle_status="active",
                operational_status="in_workshop",
                rentway_km=73180,
                active=True,
                notes="Segundo registo sintético para validação local.",
            )
            db.add(repair_vehicle)
            db.flush()

        repair_process = db.scalar(
            select(WorkshopPhasedProcess).where(
                WorkshopPhasedProcess.creation_mode == "synthetic_workshop_preview_repair"
            )
        )
        if not repair_process:
            repair_process = WorkshopPhasedProcess(
                public_reference="OF-PREVIEW-2027",
                opened_at=datetime.now(UTC),
                process_type="general",
                title="Travões e revisão — demonstração",
                creation_mode="synthetic_workshop_preview_repair",
                status="active",
                vehicle_id=repair_vehicle.id,
                plate_snapshot=repair_vehicle.plate,
                current_phase_code="reparacao",
                priority="high",
                origin="v2_clean",
                origin_detail="Ambiente sintético e isolado",
                initial_km=73180,
                initial_observation="Ruído de travagem e manutenção programada.",
                responsible_user_id=user.id,
                created_by_id=user.id,
                received_at=datetime.now(UTC),
                metadata_json={"operational_situation": "in_progress"},
            )
            db.add(repair_process)
            db.flush()
            for sort_order, (code, name, _) in enumerate(PHASES, start=1):
                status = "completed" if code != "reparacao" and sort_order < 6 else "pending"
                if code == "reparacao":
                    status = "in_progress"
                data_json = {}
                if code == "reparacao":
                    data_json = {
                        "form_snapshot": {
                            "repair_authorized_services": "Substituir pastilhas dianteiras e executar revisão programada.",
                            "repair_summary": "Viatura em bancada; desmontagem e verificação concluídas.",
                            "repair_execution_status": "A aguardar peças",
                            "repair_responsible": "Equipa Oficina Preview",
                            "repair_expected_duration": "3 h 30 min",
                            "repair_vehicle_immobilized": "Sim",
                            "repair_execution_note": "Pastilhas pedidas ao Stock; restante material disponível.",
                            "repair_fo_status": "Recebida",
                            "repair_photos_status": "Parcial",
                            "repair_post_report_status": "Pendente",
                        }
                    }
                db.add(
                    WorkshopPhasedProcessPhase(
                        process_id=repair_process.id,
                        phase_code=code,
                        name=name,
                        status=status,
                        sort_order=sort_order,
                        data_json=data_json,
                    )
                )
        else:
            repair_process.status = "active"
            repair_process.current_phase_code = "reparacao"
            repair_process.vehicle_id = repair_vehicle.id
            repair_process.responsible_user_id = user.id
            repair_process.origin = "v2_clean"
            repair_process.metadata_json = {"operational_situation": "in_progress"}

        material_need = db.scalar(
            select(WorkshopMaterialNeed).where(
                WorkshopMaterialNeed.process_id == repair_process.id,
                WorkshopMaterialNeed.material_code == "SYN-PAD-FRONT",
            )
        )
        if not material_need:
            db.add(
                WorkshopMaterialNeed(
                    process_id=repair_process.id,
                    phase_code="reparacao",
                    origin="diagnostic",
                    operation_code="replace_front_pads",
                    operation_label="Substituir pastilhas dianteiras",
                    vehicle_id=repair_vehicle.id,
                    vehicle_variant="Versão sintética",
                    technician_user_id=user.id,
                    material_code="SYN-PAD-FRONT",
                    material_description="Jogo de pastilhas dianteiras — demonstração",
                    requested_quantity="1 jogo",
                    stock_status="requested",
                    detail_json={"synthetic": True},
                )
            )
        db.commit()
        return process.id, repair_process.id


DIAGNOSTIC_PROCESS_ID, REPAIR_PROCESS_ID = prepare_fixture()


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("CARFAST_WORKSHOP_PREVIEW_PORT", "18767"))
    print(f"Workshop preview: http://127.0.0.1:{port}/login")
    print(
        "Diagnóstico: "
        f"/v2-clean/workshop/diagnostico?process_id={DIAGNOSTIC_PROCESS_ID}#relatorios"
    )
    print(
        "Reparação: "
        f"/v2-clean/workshop/reparacao?process_id={REPAIR_PROCESS_ID}"
    )
    print(f"Utilizador: {PREVIEW_EMAIL} / {PREVIEW_PASSWORD}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
