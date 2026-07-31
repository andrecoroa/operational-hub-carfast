from pathlib import Path
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


def test_financial_plan_cost_always_uses_rentway_value():
    snapshot = SimpleNamespace(
        data_json={
            "valor_aquisicao": "20.000,00",
            "data_compra": "01/01/2026",
        }
    )

    result = current_cost_from_snapshot(snapshot)

    assert result["initial_cost"] == 20000.0
    assert result["current_cost"] is not None
    assert result["current_cost"] < result["initial_cost"]


def test_financial_panel_uses_requested_four_column_order():
    template = (
        Path(__file__).parents[1] / "app" / "templates" / "clean_fleet_detail.html"
    ).read_text(encoding="utf-8")
    panel = template.split('id="clean-substep-financeiro"', 1)[1].split(
        'id="clean-substep-historico"', 1
    )[0]
    labels = [
        "Entidade financeira",
        "N.º contrato",
        "Início",
        "Fim",
        "Prestação / renda",
        "Valor residual com IVA",
        "Valor em dívida",
        "Data do valor",
        "Custo inicial sem IVA",
        "Mês amortização",
        "Custo atual sem IVA",
    ]

    positions = [panel.index(label) for label in labels]

    assert positions == sorted(positions)
    assert "clean-detail-facts clean-finance-facts" in panel
    assert "clean-finance-current-cost" in panel
