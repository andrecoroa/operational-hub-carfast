from collections.abc import Generator
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.main import app
from app.models import Base
from app.services.bootstrap import seed_initial_data


@contextmanager
def build_test_db() -> Generator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with TestingSessionLocal() as db:
        seed_initial_data(db)

    def override_get_db():
        with TestingSessionLocal() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestingSessionLocal()
    finally:
        app.dependency_overrides.clear()


def test_foundation_endpoints_return_seed_data():
    with build_test_db():
        client = TestClient(app)

        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        units = client.get("/organization/units")
        assert units.status_code == 401

        roles = client.get("/admin/roles")
        assert roles.status_code == 401

        catalogs = client.get("/settings/catalogs")
        assert catalogs.status_code == 401

        inventory = client.get("/api/stock/inventory-sessions/1")
        assert inventory.status_code == 401


def test_admin_write_endpoints_require_authentication():
    with build_test_db():
        client = TestClient(app)

        team_response = client.post(
            "/organization/teams",
            json={
                "code": "fleet_followup",
                "name": "Follow-up Frota",
                "organizational_unit_id": 1,
                "active": True,
            },
        )
        assert team_response.status_code == 401

        value_response = client.post(
            "/settings/catalogs/task_priority/values",
            json={
                "code": "critical",
                "label": "Critica",
                "active": True,
                "sort_order": 99,
                "is_system": False,
            },
        )
        assert value_response.status_code == 401
