from decimal import Decimal
from types import SimpleNamespace

from app.web.router import current_cost_from_snapshot, rentway_commercial_context


def test_rentway_acquisition_value_is_not_treated_as_value_with_tax():
    snapshot = SimpleNamespace(
        data_json={
            "valor_aquisicao": "20.000,00",
            "valor_com_iva": "24.600,00",
            "data_compra": "01/01/2026",
        }
    )

    context = rentway_commercial_context(snapshot)
    result = current_cost_from_snapshot(snapshot)

    assert context["acquisition_value"] == "20.000,00"
    assert context["value_with_tax"] == "24.600,00"
    assert result["initial_cost"] == 20000.0


def test_financial_plan_initial_cost_overrides_rentway_value():
    snapshot = SimpleNamespace(
        data_json={
            "valor_aquisicao": "20.000,00",
            "data_compra": "01/01/2026",
        }
    )

    result = current_cost_from_snapshot(
        snapshot,
        initial_cost_override=Decimal("18500.00"),
    )

    assert result["initial_cost"] == 18500.0
    assert result["current_cost"] is not None
    assert result["current_cost"] < result["initial_cost"]
