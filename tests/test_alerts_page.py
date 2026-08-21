from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_alert_builder_requires_authentication():
    client = TestClient(app)
    response = client.get("/alerts", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=%2Falerts"


def test_alert_builder_template_contains_rule_designer():
    template = (
        Path(__file__).resolve().parents[1] / "app" / "templates" / "alerts.html"
    ).read_text(encoding="utf-8")

    assert "Alertas personalizados" in template
    assert "Escolha a fonte de dados" in template
    assert "Comparação entre campos" in template
    assert 'data-action="add-rule"' in template
