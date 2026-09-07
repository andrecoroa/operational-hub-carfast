from app.services.invoice_service_classifier import (
    TAXONOMY_VERSION,
    classify_invoice_service_text,
    legacy_service_matrix,
)


def test_washer_fluid_never_becomes_glass_service() -> None:
    result = classify_invoice_service_text("LÍQUIDO DE LAVA-VIDROS CONCENTRADO")

    assert "FLUID.WASHER" in result.taxonomy_codes
    assert "GLASS.REPLACE" not in result.taxonomy_codes
    assert result.legacy_projection["other"] == []


def test_real_glass_replacement_remains_detectable() -> None:
    result = classify_invoice_service_text("Substituição do vidro para-brisas partido")

    assert "GLASS.REPLACE" in result.taxonomy_codes
    assert result.legacy_projection["other"] == ["glass"]


def test_generic_brake_text_does_not_suggest_pads() -> None:
    result = classify_invoice_service_text("Controlo do circuito de travagem e fluido de travões")

    assert "BRAKE.FLUID" in result.taxonomy_codes
    assert "BRAKE.PAD" not in result.taxonomy_codes
    assert result.legacy_projection["pads"] == []


def test_explicit_pads_and_discs_are_separate_events() -> None:
    result = classify_invoice_service_text("Substituir pastilhas e discos de travão dianteiros")

    assert {"BRAKE.PAD", "BRAKE.DISC"}.issubset(result.taxonomy_codes)


def test_telecharge_is_not_projected_as_maintenance() -> None:
    result = classify_invoice_service_text("Efetuar telecarregamento do calculador do motor")

    assert result.taxonomy_codes == ["DIAG.DOWNLOAD"]
    assert result.legacy_projection["maintenance"] == []
    assert legacy_service_matrix("Telecarregamento")["maintenance"] == "-"


def test_maintenance_word_alone_does_not_create_plan() -> None:
    result = classify_invoice_service_text("AdBlue manutenção")

    assert "FLUID.ADBLUE" in result.taxonomy_codes
    assert "MAINT.PLAN" not in result.taxonomy_codes


def test_oil_change_requires_filter_before_interim_event() -> None:
    incomplete = classify_invoice_service_text("Degradação do óleo do motor")
    complete = classify_invoice_service_text("Substituir óleo do motor e filtro de óleo")

    assert "MAINT.OIL_INTERIM" not in incomplete.taxonomy_codes
    assert "degradation_without_oil_and_filter" in incomplete.blocked_reasons
    assert "MAINT.OIL_INTERIM" in complete.taxonomy_codes
    assert complete.legacy_projection["maintenance"] == ["degradation"]


def test_plan_bundle_and_real_invoice_example_are_classified_without_glass() -> None:
    result = classify_invoice_service_text(
        "Óleo motor; filtro de óleo; filtro habitáculo; filtro de ar; "
        "filtro combustível; fluido de travões; líquido refrigerante; "
        "AdBlue; lâmpada; líquido de lava-vidros"
    )

    assert result.taxonomy_version == TAXONOMY_VERSION
    assert {
        "MAINT.PLAN",
        "FILTER.CABIN",
        "FILTER.AIR",
        "FILTER.FUEL",
        "BRAKE.FLUID",
        "FLUID.COOLANT",
        "FLUID.ADBLUE",
        "ELECTRIC.LIGHTING",
        "FLUID.WASHER",
    }.issubset(result.taxonomy_codes)
    assert "GLASS.REPLACE" not in result.taxonomy_codes


def test_tyre_operations_are_not_collapsed_into_replacement() -> None:
    repair = classify_invoice_service_text("Reparação de furo no pneu")
    balance = classify_invoice_service_text("Equilibragem de rodas")
    align = classify_invoice_service_text("Alinhamento da geometria das rodas")

    assert "TYRE.REPAIR" in repair.taxonomy_codes
    assert "TYRE.REPLACE" not in repair.taxonomy_codes
    assert "TYRE.BALANCE" in balance.taxonomy_codes
    assert "TYRE.ALIGN" in align.taxonomy_codes


def test_standalone_puncture_is_still_a_tyre_repair() -> None:
    result = classify_invoice_service_text("Reparação de furo")

    assert "TYRE.REPAIR" in result.taxonomy_codes
    assert result.legacy_projection["tyres"] == ["puncture"]


def test_claim_is_a_motive_not_a_service() -> None:
    result = classify_invoice_service_text("Reparação na sequência de sinistro")

    assert result.motives == ["claim"]
    assert result.legacy_projection["other"] == []
