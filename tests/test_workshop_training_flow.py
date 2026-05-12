from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.models import Base
from app.models.audit import AuditLog
from app.models.admin import User
from app.models.incidents import Incident, IncidentEvent, IncidentEvidence
from app.models.organization import Team
from app.models.pilot import PilotFeedback
from app.models.tasks import Task
from app.models.vehicles import Vehicle, VehicleOperationalStatusEvent
from app.models.workshop import WorkshopProcess, WorkshopProcessEvidence, WorkshopProcessNote
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
            rentway_unit_nr="120",
            lifecycle_status="active",
            operational_status="free",
        )
        newer_vehicle = Vehicle(
            plate="AA11AA",
            vin="TESTUNIT200",
            brand="FIAT",
            model="500",
            rentway_unit_nr="200",
            lifecycle_status="active",
            operational_status="free",
        )
        older_vehicle = Vehicle(
            plate="BB22BB",
            vin="TESTUNIT030",
            brand="FIAT",
            model="Panda",
            rentway_unit_nr="030",
            lifecycle_status="active",
            operational_status="free",
        )
        sold_vehicle = Vehicle(
            plate="CC33CC",
            vin="TESTUNIT250",
            brand="FIAT",
            model="Tipo",
            rentway_unit_nr="250",
            lifecycle_status="sold",
            operational_status="sold",
            active=False,
        )
        db.add(vehicle)
        db.add(newer_vehicle)
        db.add(older_vehicle)
        db.add(sold_vehicle)
        db.commit()
        vehicle_id = vehicle.id

    client = TestClient(app)
    login = client.post(
        "/login",
        data={"email": "formacao@example.com", "password": "Secret123!"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert client.get("/task-board/new").status_code == 200

    created = client.post(
        "/workshop",
        data={
            "vehicle_id": vehicle_id,
            "title": "",
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
        assert process.title == "Cliente reporta ruido anormal na travagem."
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

    evidence = client.post(
        f"/workshop/{process_id}/evidences",
        data={
            "phase": "diagnosis",
            "evidence_type": "photo",
            "anomaly_category": "wear",
            "status": "registered",
            "description": "",
            "external_url": "https://example.com/sharepoint/oficina/bz81sc/pastilhas.jpg",
            "storage_provider": "sharepoint",
        },
        follow_redirects=False,
    )
    assert evidence.status_code == 303

    incident_response = client.post(
        f"/workshop/{process_id}/incidents",
        data={
            "title": "",
            "description": "Pastilha com desgaste anormal e ruído em travagem.",
            "incident_type": "technical",
            "category": "wear",
            "severity": "high",
            "evidence_type": "audio",
            "evidence_description": "Nota de voz do operador a explicar o ruído ouvido no teste.",
            "evidence_url": "https://example.com/sharepoint/oficina/bz81sc/audio-ruido.m4a",
            "storage_provider": "sharepoint",
        },
        follow_redirects=False,
    )
    assert incident_response.status_code == 303

    help_request = client.post(
        "/pilot-feedback",
        data={
            "kind": "question",
            "source_area": "workshop",
            "entity_type": "workshop_process",
            "entity_id": str(process_id),
            "subject": "Duvida no diagnostico",
            "body": "Nao sei se devo colocar em aguardar analise ou aguardar material.",
            "return_url": f"/workshop/{process_id}",
        },
        follow_redirects=False,
    )
    assert help_request.status_code == 303

    experience_report = client.post(
        "/pilot-feedback",
        data={
            "kind": "experience",
            "source_area": "workshop",
            "entity_type": "workshop_process",
            "entity_id": str(process_id),
            "subject": "",
            "body": "O registo de evidencia foi simples, mas falta ver o historico fechado.",
            "return_url": f"/workshop/{process_id}",
        },
        follow_redirects=False,
    )
    assert experience_report.status_code == 303

    created_user = client.post(
        "/admin/users",
        data={
            "name": "Paulo Azevedo",
            "email": "paulo.azevedo@example.com",
            "password": "Temp12345!",
            "role_code": "operator",
        },
        follow_redirects=False,
    )
    assert created_user.status_code == 303

    with SessionLocal() as db:
        paulo = db.scalar(select(User).where(User.email == "paulo.azevedo@example.com"))
        assert paulo is not None
        assert paulo.name == "Paulo Azevedo"
        paulo_id = paulo.id
        workshop_team = db.scalar(select(Team).where(Team.code == "workshop"))
        operations_team = db.scalar(select(Team).where(Team.code == "operations"))
        assert workshop_team is not None
        assert operations_team is not None
        workshop_team_id = workshop_team.id
        operations_team_id = operations_team.id

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

    task_board_task = client.post(
        "/task-board",
        data={
            "title": "Contactar oficina externa",
            "task_type": "task",
            "source": "manual",
            "category": "workshop",
            "subcategory": "Oficina externa",
            "priority": "high",
            "assigned_to_id": str(paulo_id),
            "team_id": str(workshop_team_id),
            "due_on": "2026-05-14",
            "customer_name": "Cliente Teste",
            "customer_email": "cliente@example.com",
            "plate": "BZ81SC",
            "reservation_number": "RES123",
            "contract_number": "CONT456",
            "station": "Aeroporto Porto",
            "department": "Oficina",
            "description": "Confirmar disponibilidade para avaliacao.",
        },
        follow_redirects=False,
    )
    assert task_board_task.status_code == 303

    with SessionLocal() as db:
        managed_task = db.scalar(select(Task).where(Task.title == "Contactar oficina externa"))
        assert managed_task is not None
        managed_task_id = managed_task.id

    task_update = client.post(
        f"/task-board/{managed_task_id}/update",
        data={
            "status": "in_treatment",
            "priority": "high",
            "task_type": "task",
            "category": "workshop",
            "subcategory": "Oficina externa",
            "assigned_to_id": str(paulo_id),
            "team_id": str(workshop_team_id),
            "due_on": "2026-05-15",
            "station": "Aeroporto Porto",
            "department": "Oficina",
        },
        follow_redirects=False,
    )
    assert task_update.status_code == 303

    unassigned_overdue = client.post(
        "/task-board",
        data={
            "title": "Validar caução pendente",
            "task_type": "request",
            "source": "email",
            "category": "finance",
            "priority": "high",
            "team_id": str(operations_team_id),
            "due_on": "2026-05-01",
            "customer_name": "Cliente Backlog",
            "station": "Aeroporto Porto",
            "department": "Faturação",
            "description": "Tarefa vencida sem responsável para testar filtros.",
        },
        follow_redirects=False,
    )
    assert unassigned_overdue.status_code == 303

    with SessionLocal() as db:
        archived_task = db.scalar(select(Task).where(Task.title == "Validar caução pendente"))
        assert archived_task is not None
        archived_task_id = archived_task.id

    archive_update = client.post(
        f"/task-board/{archived_task_id}/update",
        data={
            "status": "no_action_needed",
            "priority": "high",
            "task_type": "request",
            "category": "finance",
            "subcategory": "",
            "assigned_to_id": "",
            "team_id": str(operations_team_id),
            "due_on": "2026-05-01",
            "station": "Aeroporto Porto",
            "department": "Faturação",
        },
        follow_redirects=False,
    )
    assert archive_update.status_code == 303

    task_center = client.get("/task-board")
    assert task_center.status_code == 200
    assert "Criar tarefa" in task_center.text
    assert "Abrir gestão" in task_center.text
    assert client.get("/task-board/manage?view=unassigned").status_code == 200
    assert client.get("/task-board/manage?view=overdue").status_code == 200
    assert client.get("/task-board/manage?category=workshop&assigned_to_id=" + str(paulo_id)).status_code == 200
    assert client.get("/task-board/manage?q=BZ81SC").status_code == 200
    default_task_board = client.get("/task-board/manage")
    assert "Validar caução pendente" not in default_task_board.text
    archived_search = client.get("/task-board/manage?view=archived&q=Validar+caução")
    assert archived_search.status_code == 200
    assert "Validar caução pendente" in archived_search.text
    no_action_filter = client.get("/task-board/manage?status=no_action_needed")
    assert no_action_filter.status_code == 200
    assert "Validar caução pendente" in no_action_filter.text
    assert client.get("/task-board/manage?feedback_saved=1").status_code == 200
    assert client.get(f"/task-board/{managed_task_id}?feedback_saved=1").status_code == 200

    task_feedback = client.post(
        "/pilot-feedback",
        data={
            "kind": "experience",
            "source_area": "tasks",
            "entity_type": "task",
            "entity_id": str(managed_task_id),
            "subject": "Teste de tarefas",
            "body": "Os filtros ajudam, mas quero validar a linguagem com a equipa.",
            "return_url": f"/task-board/{managed_task_id}",
        },
        follow_redirects=False,
    )
    assert task_feedback.status_code == 303

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
        ) >= 5
        assert db.scalar(
            select(func.count()).select_from(WorkshopProcessEvidence).where(
                WorkshopProcessEvidence.process_id == process_id,
                WorkshopProcessEvidence.vehicle_id == vehicle_id,
                WorkshopProcessEvidence.anomaly_category == "wear",
                WorkshopProcessEvidence.description == "Evidência registada sem descrição.",
            )
        ) == 1
        incident = db.scalar(select(Incident).where(Incident.workshop_process_id == process_id))
        assert incident is not None
        assert incident.title == "Pastilha com desgaste anormal e ruído em travagem."
        assert incident.vehicle_id == vehicle_id
        assert incident.plate == "BZ81SC"
        assert incident.category == "wear"
        assert incident.severity == "high"
        assert db.scalar(
            select(func.count()).select_from(IncidentEvidence).where(
                IncidentEvidence.incident_id == incident.id,
                IncidentEvidence.evidence_type == "audio",
                IncidentEvidence.external_url == "https://example.com/sharepoint/oficina/bz81sc/audio-ruido.m4a",
            )
        ) == 1
        assert db.scalar(
            select(func.count()).select_from(IncidentEvent).where(IncidentEvent.incident_id == incident.id)
        ) >= 2
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
        managed_task = db.get(Task, managed_task_id)
        assert managed_task.status == "in_treatment"
        assert managed_task.task_type == "task"
        assert managed_task.source == "manual"
        assert managed_task.category == "workshop"
        assert managed_task.subcategory == "Oficina externa"
        assert managed_task.customer_name == "Cliente Teste"
        assert managed_task.customer_email == "cliente@example.com"
        assert managed_task.plate == "BZ81SC"
        assert managed_task.reservation_number == "RES123"
        assert managed_task.contract_number == "CONT456"
        assert managed_task.station == "Aeroporto Porto"
        assert managed_task.department == "Oficina"
        assert managed_task.priority == "high"
        assert managed_task.assigned_to_id == paulo_id
        assert managed_task.team_id == workshop_team_id
        assert managed_task.due_on.isoformat() == "2026-05-15"
        assert db.scalar(
            select(func.count()).select_from(PilotFeedback).where(
                PilotFeedback.entity_type == "workshop_process",
                PilotFeedback.entity_id == str(process_id),
            )
        ) == 2
        assert db.scalar(
            select(func.count()).select_from(PilotFeedback).where(
                PilotFeedback.source_area == "tasks",
                PilotFeedback.entity_type == "task",
                PilotFeedback.entity_id == str(managed_task_id),
            )
        ) == 1
        assert db.scalar(select(func.count()).select_from(AuditLog)) >= 1

    assert client.get("/workshop").status_code == 200
    workshop_page = client.get("/workshop")
    assert workshop_page.status_code == 200
    assert "Unit 200" in workshop_page.text
    assert "Unit 120" in workshop_page.text
    workshop_detail_page = client.get(f"/workshop/{process_id}")
    assert workshop_detail_page.status_code == 200
    assert "Incidentes do processo" in workshop_detail_page.text
    assert "Áudio/nota de voz" in workshop_detail_page.text
    assert client.get(f"/fleet/{vehicle_id}").status_code == 200
    fleet_page = client.get("/fleet")
    assert fleet_page.status_code == 200
    fleet_html = fleet_page.text
    assert fleet_html.index("200") < fleet_html.index("120") < fleet_html.index("030")
    assert "250" not in fleet_html
    sold_fleet_page = client.get("/fleet?scope=sold")
    assert sold_fleet_page.status_code == 200
    assert "250" in sold_fleet_page.text
    all_fleet_page = client.get("/fleet?scope=all")
    assert all_fleet_page.status_code == 200
    assert "250" in all_fleet_page.text
    assert all_fleet_page.text.index("250") < all_fleet_page.text.index("200")
    assert client.get("/pilot-feedback/new?kind=question&source_area=workshop").status_code == 200
    assert client.get(
        f"/pilot-feedback/new?kind=question&source_area=tasks&entity_type=task&entity_id={managed_task_id}"
    ).status_code == 200
    assert client.get("/admin").status_code == 200
