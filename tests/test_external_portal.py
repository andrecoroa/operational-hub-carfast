from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.models import Base
from app.models.tasks import Task, TaskComment, TaskHistory
from app.services.bootstrap import seed_initial_data
import app.web.router as web_router


def test_external_portal_creates_simple_task():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    web_router.SessionLocal = SessionLocal
    web_router.EXTERNAL_PORTAL_RATE_LIMIT.clear()

    with SessionLocal() as db:
        seed_initial_data(db)

    client = TestClient(app)
    form = client.get("/portal/pedido")
    assert form.status_code == 200
    assert "Registar pedido" in form.text

    missing_contact = client.post(
        "/portal/pedido",
        data={
            "subject": "Pedido sem contacto",
            "message": "Mensagem com detalhe suficiente.",
            "consent": "1",
        },
        follow_redirects=False,
    )
    assert missing_contact.status_code == 303
    assert "error=required" in missing_contact.headers["location"]

    created = client.post(
        "/portal/pedido",
        data={
            "name": "Cliente Externo",
            "email": "cliente@example.com",
            "phone": "910000000",
            "category": "danos",
            "subject": "Dano reportado na entrega",
            "message": "Existe um risco visivel na porta traseira.",
            "plate": "AA 11 AA",
            "reservation_number": "RES-1",
            "contract_number": "CONT-1",
            "station": "Porto",
            "consent": "1",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    assert "sent=1" in created.headers["location"]

    with SessionLocal() as db:
        task = db.scalar(select(Task).where(Task.title == "Dano reportado na entrega"))
        assert task is not None
        assert task.task_type == "request_info"
        assert task.source == "external_portal"
        assert task.category == "danos"
        assert task.status == "new"
        assert task.customer_name == "Cliente Externo"
        assert task.customer_email == "cliente@example.com"
        assert task.customer_phone == "910000000"
        assert task.plate == "AA11AA"
        assert task.reservation_number == "RES-1"
        assert task.contract_number == "CONT-1"
        assert task.station == "Porto"
        assert task.team_id is not None
        assert task.created_by_id is None
        assert task.external_source_id.startswith("portal:")
        assert db.scalar(select(TaskHistory).where(TaskHistory.task_id == task.id)) is not None
        assert db.scalar(select(TaskComment).where(TaskComment.task_id == task.id)) is not None
