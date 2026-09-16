from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_alert_builder_requires_authentication():
    client = TestClient(app)
    response = client.get("/alerts", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=%2Falerts"


def test_clean_navigation_opens_operational_notifications():
    root = Path(__file__).resolve().parents[1]
    sidebar = (root / "app" / "templates" / "_sidebar.html").read_text(encoding="utf-8")
    topbar = (root / "app" / "templates" / "_visual_topbar.html").read_text(encoding="utf-8")

    assert 'href="/v2-clean/tasks/notifications"' in sidebar
    assert 'href="/v2-clean/tasks/notifications"' in topbar
