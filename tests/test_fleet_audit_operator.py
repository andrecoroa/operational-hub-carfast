import json
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.services import fleet_audit_operator


def test_operator_remains_disabled_without_configuration(monkeypatch):
    monkeypatch.setattr(settings, "fleet_audit_operator_enabled", False)
    with pytest.raises(RuntimeError, match="não configurado"):
        fleet_audit_operator.generate_audit_review({"case": {"id": 1}}, "Analisa")


def test_operator_uses_only_supplied_case_and_never_stores_response(monkeypatch):
    monkeypatch.setattr(settings, "fleet_audit_operator_enabled", True)
    monkeypatch.setattr(settings, "fleet_audit_operator_model", "model-for-test")
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    calls = {}
    output = {key: ([] if value["type"] == "array" else "teste")
              for key, value in fleet_audit_operator.SCHEMA["properties"].items()}

    class FakeResponses:
        def create(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(status="completed", output_text=json.dumps(output))

    monkeypatch.setattr(fleet_audit_operator, "OpenAI", lambda **kwargs: SimpleNamespace(
        responses=FakeResponses()))
    result = fleet_audit_operator.generate_audit_review(
        {"case": {"id": 7, "suspicion": "Por verificar"}}, "Preparar pergunta"
    )
    assert result == output
    assert calls["store"] is False
    assert calls["model"] == "model-for-test"
    assert json.loads(calls["input"])["case"]["case"]["id"] == 7
    assert "tools" not in calls
