from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
import app.main as app_main
from app.main import app
from app.models import Base
from app.services.bootstrap import seed_initial_data
from app.services.users import create_user
import app.web.clean_admin as clean_admin
import app.web.router as web_router


TEST_ADMIN_EMAIL = "admin.tests@carfast.local"
TEST_ADMIN_PASSWORD = "Secret123!"


@pytest.fixture()
def db_session() -> Generator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    original_web_session_local = web_router.SessionLocal
    original_clean_admin_session_local = clean_admin.SessionLocal
    original_main_session_local = app_main.SessionLocal
    web_router.SessionLocal = TestingSessionLocal
    clean_admin.SessionLocal = TestingSessionLocal
    app_main.SessionLocal = TestingSessionLocal

    def override_get_db():
        with TestingSessionLocal() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db

    with TestingSessionLocal() as db:
        seed_initial_data(db)
        create_user(
            db,
            name="Admin Testes",
            email=TEST_ADMIN_EMAIL,
            password=TEST_ADMIN_PASSWORD,
            role_codes=["admin"],
            organizational_unit_codes=["carfast"],
        )
        db.commit()

    try:
        with TestingSessionLocal() as db:
            yield db
    finally:
        app.dependency_overrides.clear()
        web_router.SessionLocal = original_web_session_local
        clean_admin.SessionLocal = original_clean_admin_session_local
        app_main.SessionLocal = original_main_session_local


@pytest.fixture()
def client(db_session: Session) -> TestClient:
    return TestClient(app)


@pytest.fixture()
def authenticated_client(client: TestClient) -> TestClient:
    response = client.post(
        "/login",
        data={"email": TEST_ADMIN_EMAIL, "password": TEST_ADMIN_PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/choose-experience"
    notice = client.post("/change-notice", data={"next_url": "/"}, follow_redirects=False)
    assert notice.status_code == 303
    assert notice.headers["location"] == "/"
    return client
