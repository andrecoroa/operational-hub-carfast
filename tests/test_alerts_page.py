from fastapi.testclient import TestClient

from app.main import app


def test_alert_builder_requires_authentication():
    client = TestClient(app)
    response = client.get("/alerts", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_alerts_redirects_to_operational_notifications(authenticated_client):
    response = authenticated_client.get("/alerts", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/v2-clean/tasks/notifications"
