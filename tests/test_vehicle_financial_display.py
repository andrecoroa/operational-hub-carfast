from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from app.web.router import (
    amount_with_standard_vat,
    current_cost_from_snapshot,
    current_value_with_financial_amortization,
    rentway_commercial_context,
)


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
    assert result["initial_cost_with_vat"] == 24600.0
    assert result["current_cost_with_vat"] is not None
    assert result["current_cost_with_vat"] < result["initial_cost_with_vat"]


def test_financial_plan_cost_always_uses_rentway_value():
    snapshot = SimpleNamespace(
        data_json={
            "valor_aquisicao": "20.000,00",
            "data_compra": "01/01/2026",
        }
    )

    result = current_cost_from_snapshot(snapshot)

    assert result["initial_cost"] == 20000.0
    assert result["initial_cost_with_vat"] == 24600.0
    assert result["current_cost"] is not None
    assert result["current_cost"] < result["initial_cost"]


def test_outstanding_capital_is_displayed_with_standard_vat():
    assert amount_with_standard_vat("1000") == 1230
    assert amount_with_standard_vat("1.234,56") == Decimal("1518.51")


def test_current_value_uses_rentway_daily_value_instead_of_bank_capital():
    result = current_value_with_financial_amortization(
        "24.600,00",
        "18.431,81",
        "9.541,84",
        "15.000,00",
    )

    assert result == Decimal("15000.00")


def test_current_value_falls_back_to_plan_dates_when_financial_amounts_are_missing():
    result = current_value_with_financial_amortization(
        "24.600,00",
        None,
        None,
        None,
        date(2026, 1, 1),
        date(2026, 7, 31),
    )

    assert result == Decimal("22823.61")


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
        "Capital em dívida com IVA",
        "Data do valor",
        "Custo inicial com IVA",
        "Mês amortização",
        "Valor atual com IVA",
    ]

    positions = [panel.index(label) for label in labels]

    assert positions == sorted(positions)
    assert "clean-detail-facts clean-finance-facts" in panel
    assert "clean-finance-current-cost" in panel
