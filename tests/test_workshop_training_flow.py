from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.models import Base
from app.models.audit import AuditLog
from app.models.tasks import Task
from app.models.vehicles import Vehicle, VehicleOperationalStatusEvent
from app.models.workshop import WorkshopProcess, WorkshopProcessNote
from app.services.bootstrap import seed_initial_data
from app.services.users import create_user
import app.web.router as web_router


def test_complete_workshop_training_flow():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    web_router.SessionLocal = SessionLocal

    with SessionLocal() as db:
        seed_initial_data(db)
        create_user(
            db,
            name="Formacao Oficina",
            email="formacao@example.com",
            password="Secret123!",
            role_codes=["admin"],
            organizational_unit_codes=["carfast"],
        )
        vehicle = Vehicle(
            plate="BZ81SC",
            vin="ZFA5FBAT0SJ079652",
            brand="FIAT",
            model="600 Hibrido",
            lifecycle_status="active",
            operational_status="free",
        )
        db.add(vehicle)
        db.commit()
        vehicle_id = vehicle.id

    client = TestClient(app)
    login = client.post(
        "/login",
        data={"email": "formacao@example.com", "password": "Secret123!"},
        follow_redirects=False,
    )
    assert login.status_code == 303

    created = client.post(
        "/workshop",
        data={
            "vehicle_id": vehicle_id,
            "title": "Ruido na travagem",
            "opening_type": "appointment",
            "priority": "high",
            "km_entry": "3673",
            "expected_exit_on": "2026-05-13",
            "note": "Cliente reporta ruido anormal na travagem.",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303

    with SessionLocal() as db:
        process = db.scalar(select(WorkshopProcess).where(WorkshopProcess.vehicle_id == vehicle_id))
        assert process is not None
        process_id = process.id
        assert process.opening_type == "appointment"
        assert process.status == "opening"
        assert process.km_entry == 3673

    reception = client.post(
        f"/workshop/{process_id}/flow",
        data={
            "status": "reception",
            "decision": "",
            "decision_note": "Viatura recebida e ruido confirmado em teste curto.",
        },
        follow_redirects=False,
    )
    assert reception.status_code == 303

    diagnosis_note = client.post(
        f"/workshop/{process_id}/notes",
        data={"note": "Diagnostico: desgaste irregular em pastilhas dianteiras."},
        follow_redirects=False,
    )
    assert diagnosis_note.status_code == 303

    decision = client.post(
        f"/workshop/{process_id}/flow",
        data={
            "status": "waiting_parts",
            "decision": "order_parts",
            "decision_note": "Encomendar discos e pastilhas dianteiras.",
        },
        follow_redirects=False,
    )
    assert decision.status_code == 303

    execution_note = client.post(
        f"/workshop/{process_id}/notes",
        data={"note": "Material recebido. Intervencao concluida e teste de estrada OK."},
        follow_redirects=False,
    )
    assert execution_note.status_code == 303

    closed = client.post(
        f"/workshop/{process_id}/flow",
        data={
            "status": "closed",
            "decision": "order_parts",
            "decision_note": "Processo fechado apos validacao.",
        },
        follow_redirects=False,
    )
    assert closed.status_code == 303

    vehicle_note = client.post(
        f"/fleet/{vehicle_id}/events",
        data={"note": "Processo de oficina concluido. Viatura apta para operacao."},
        follow_redirects=False,
    )
    assert vehicle_note.status_code == 303

    task = client.post(
        f"/fleet/{vehicle_id}/tasks",
        data={
            "title": "Confirmar arquivo da intervencao",
            "priority": "normal",
            "description": "Validar que a documentacao final ficou registada.",
        },
        follow_redirects=False,
    )
    assert task.status_code == 303

    with SessionLocal() as db:
        process = db.get(WorkshopProcess, process_id)
        assert process.status == "closed"
        assert process.closed_at is not None
        assert process.decision == "order_parts"
        assert process.decision_note == "Processo fechado apos validacao."
        assert db.scalar(
            select(func.count()).select_from(WorkshopProcessNote).where(
                WorkshopProcessNote.process_id == process_id
            )
        ) >= 4
        assert db.scalar(
            select(func.count()).select_from(VehicleOperationalStatusEvent).where(
                VehicleOperationalStatusEvent.vehicle_id == vehicle_id
            )
        ) == 1
        assert db.scalar(
            select(func.count()).select_from(Task).where(
                Task.entity_type == "vehicle",
                Task.entity_id == str(vehicle_id),
            )
        ) == 1
        assert db.scalar(select(func.count()).select_from(AuditLog)) >= 1

    assert client.get("/workshop").status_code == 200
    assert client.get(f"/workshop/{process_id}").status_code == 200
    assert client.get(f"/fleet/{vehicle_id}").status_code == 200
