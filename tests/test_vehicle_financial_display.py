from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from app.web.router import (
    amount_with_standard_vat,
    current_cost_from_snapshot,
    current_value_with_financial_amortization,
    financial_contract_key,
    residual_amount_for_vehicle,
    rentway_commercial_context,
)
from app.services.vehicle_financials import canonical_vehicle_financial_values


def test_financial_contract_key_normalizes_entity_aliases():
    cgd = SimpleNamespace(
        finance_entity="CGD",
        contract_number=" 100169978 ",
    )
    caixa = SimpleNamespace(
        finance_entity="Caixa Geral de Depósitos, S.A.",
        contract_number="100169978",
    )

    assert financial_contract_key(cgd) == financial_contract_key(caixa)


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


def test_canonical_debt_applies_vat_when_plan_only_has_net_balance():
    plan = SimpleNamespace(
        outstanding_amount=Decimal("6244.26"),
        start_date=None,
        amount_reference_date=date(2026, 8, 1),
        initial_amount=None,
    )

    values = canonical_vehicle_financial_values(
        cost_context={},
        plan=plan,
        current_value_calculator=lambda *args: None,
        reference=date(2026, 8, 7),
    )

    assert values["outstanding_with_vat"] == Decimal("7680.44")


def test_canonical_debt_uses_explicit_monthly_vat_without_applying_it_twice():
    plan = SimpleNamespace(
        outstanding_amount=Decimal("6244.26"),
        start_date=None,
        amount_reference_date=date(2026, 8, 1),
        initial_amount=None,
    )
    installment = SimpleNamespace(
        period_end=date(2026, 8, 1),
        period_number=38,
        amortization_amount=Decimal("100.00"),
        outstanding_with_vat=Decimal("7679.99"),
    )

    values = canonical_vehicle_financial_values(
        cost_context={},
        plan=plan,
        installments=[installment],
        current_value_calculator=lambda *args: None,
        reference=date(2026, 8, 7),
    )

    assert values["outstanding_with_vat"] == Decimal("7679.99")


def test_canonical_debt_uses_current_month_plan_before_rental_due_date():
    plan = SimpleNamespace(
        outstanding_amount=Decimal("7000.00"),
        start_date=None,
        amount_reference_date=date(2026, 7, 31),
        initial_amount=None,
    )
    july = SimpleNamespace(
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 10),
        period_number=12,
        amortization_amount=Decimal("100.00"),
        outstanding_with_vat=Decimal("7000.00"),
    )
    august = SimpleNamespace(
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 10),
        period_number=13,
        amortization_amount=Decimal("100.00"),
        outstanding_with_vat=Decimal("6877.00"),
    )

    values = canonical_vehicle_financial_values(
        cost_context={},
        plan=plan,
        installments=[july, august],
        current_value_calculator=lambda *args: None,
        reference=date(2026, 8, 1),
    )

    assert values["outstanding_with_vat"] == Decimal("6877.00")
    assert values["debt_reference_date"] == date(2026, 8, 1)


def test_current_value_uses_rentway_amortization_instead_of_bank_capital():
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

    assert result == Decimal("22806.25")


def test_current_value_at_month_24_uses_24_of_96_months():
    result = current_value_with_financial_amortization(
        "22.127,48",
        None,
        None,
        None,
        date(2024, 8, 1),
        date(2026, 7, 31),
    )

    assert result == Decimal("16595.61")


def test_current_value_uses_displayed_month_when_plan_dates_are_missing():
    result = current_value_with_financial_amortization(
        "22.185,66",
        None,
        None,
        None,
        None,
        None,
        5,
    )

    assert result == Decimal("21030.16")


def test_legacy_cgd_contract_residual_is_allocated_by_vehicle_weight():
    first = SimpleNamespace(
        finance_entity="CGD",
        residual_amount=Decimal("10000.00"),
        initial_amount=Decimal("20000.00"),
        active=True,
        raw_json={"association": {}},
    )
    second = SimpleNamespace(
        finance_entity="CGD",
        residual_amount=Decimal("10000.00"),
        initial_amount=Decimal("30000.00"),
        active=True,
        raw_json={"association": {}},
    )

    assert residual_amount_for_vehicle(first, [first, second]) == Decimal("4000.00")
    assert residual_amount_for_vehicle(second, [first, second]) == Decimal("6000.00")


def test_cgd_vehicle_residual_from_association_is_not_reallocated():
    plan = SimpleNamespace(
        finance_entity="Caixa Geral de Depósitos, S.A.",
        residual_amount=Decimal("2324.57"),
        initial_amount=Decimal("18898.93"),
        active=True,
        raw_json={"association": {"Valor residual (€)": "2324.57"}},
    )

    assert residual_amount_for_vehicle(plan, [plan]) == Decimal("2324.57")


def test_legacy_cgd_contract_residual_is_hidden_without_allocation_basis():
    plan = SimpleNamespace(
        finance_entity="CGD",
        residual_amount=Decimal("21143.82"),
        initial_amount=Decimal("22185.66"),
        active=True,
        raw_json={"association": {}},
    )

    assert residual_amount_for_vehicle(plan, [plan]) is None


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

    stylesheet = (
        Path(__file__).parents[1] / "app" / "static" / "css" / "app.css"
    ).read_text(encoding="utf-8")
    assert ".clean-finance-facts .clean-finance-current-cost" not in stylesheet


def test_vehicle_rules_panel_includes_requested_rentway_fields():
    template = (
        Path(__file__).parents[1] / "app" / "templates" / "clean_fleet_detail.html"
    ).read_text(encoding="utf-8")
    panel = template.split('id="clean-substep-regras"', 1)[1].split(
        'id="clean-substep-manutencao"', 1
    )[0]

    for label in (
        "Cor",
        "Combustível",
        "Categoria / grupo Rentway",
        "Lugares",
        "Estado Rentway",
        "Devolução prevista",
    ):
        assert label in panel
