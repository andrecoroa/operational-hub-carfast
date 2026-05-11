from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.main import app
from app.models import Base
from app.services.bootstrap import seed_initial_data


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
        assert units.status_code == 200
        unit_codes = {item["code"] for item in units.json()}
        assert {"carfast", "fleet", "workshop"}.issubset(unit_codes)

        roles = client.get("/admin/roles")
        assert roles.status_code == 200
        role_codes = {item["code"] for item in roles.json()}
        assert {"admin", "manager", "operator", "viewer"}.issubset(role_codes)

        catalogs = client.get("/settings/catalogs")
        assert catalogs.status_code == 200
        catalog_codes = {item["code"] for item in catalogs.json()}
        assert "vehicle_lifecycle_status" in catalog_codes


def test_can_create_team_and_catalog_value():
    with build_test_db():
        client = TestClient(app)

        units = client.get("/organization/units").json()
        fleet_id = next(item["id"] for item in units if item["code"] == "fleet")

        team_response = client.post(
            "/organization/teams",
            json={
                "code": "fleet_followup",
                "name": "Follow-up Frota",
                "organizational_unit_id": fleet_id,
                "active": True,
            },
        )
        assert team_response.status_code == 201
        assert team_response.json()["code"] == "fleet_followup"

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
        assert value_response.status_code == 201
        assert value_response.json()["code"] == "critical"

