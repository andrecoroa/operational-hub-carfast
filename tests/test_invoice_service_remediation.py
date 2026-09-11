from decimal import Decimal

from app.services.invoice_service_remediation import (
    build_article_axle_lookup,
    build_document_service_proposals,
    classify_invoice_line,
)


def line(number: int, description: str, amount: str, role: str = "LINE.UNKNOWN"):
    return {
        "source_line_id": f"10:{number}",
        "line_number": str(number),
        "description": description,
        "line_total": amount,
        "line_role": role,
    }


def document(total: str = "123,00"):
    return {"run_id": "test", "document_id": "10", "total_extracted": total}


def test_oil_and_oil_filter_is_interim_not_revision():
    result = build_document_service_proposals(
        document("61,50"),
        [line(1, "Mudança de óleo motor", "40,00", "LINE.LABOR"), line(2, "Filtro de óleo", "10,00")],
    )
    assert [item["service_code"] for item in result["services"]] == ["MAINT.OIL_INTERIM"]


def test_revision_requires_an_additional_periodic_filter():
    result = build_document_service_proposals(
        document(),
        [
            line(1, "Óleo motor", "40,00"),
            line(2, "Filtro de óleo", "10,00"),
            line(3, "Filtro de ar", "12,00"),
        ],
    )
    codes = [item["service_code"] for item in result["services"]]
    assert "MAINT.PLAN" in codes


def test_front_and_rear_brakes_are_separate_events():
    result = build_document_service_proposals(
        document(),
        [line(1, "Calços FRT", "50,00"), line(2, "Calços trás", "40,00")],
    )
    assert [(item["service_code"], item["axle"]) for item in result["services"]] == [
        ("BRAKE.PAD", "front"),
        ("BRAKE.PAD", "rear"),
    ]


def test_tra_means_brake_and_never_rear_without_context():
    classified = classify_invoice_line(line(1, "J.PASTILHAS TRA", "90,00"))
    assert classified.service_code == "BRAKE.PAD"
    assert classified.axle == ""
    result = build_document_service_proposals(document(), [line(1, "J.PASTILHAS TRA", "90,00")])
    assert result["services"][0]["axle"] == ""
    assert result["services"][0]["axle_source"] == "unknown"


def test_validated_supplier_article_map_is_second_priority():
    lookup = build_article_axle_lookup(
        {
            "schema": "carfast.invoice-article-axle-map.v1",
            "mappings": [
                {
                    "supplier_key": "NIF:123",
                    "article_reference": "PAD-42",
                    "axle": "rear",
                    "evidence": "catálogo confirmado 2026-09-10",
                }
            ],
        }
    )
    result = build_document_service_proposals(
        {"run_id": "test", "document_id": "10", "total_extracted": "90", "supplier_group": "NIF:123"},
        [{**line(1, "J.PASTILHAS TRA", "90,00"), "reference": "PAD-42"}],
        article_axle_map=lookup,
    )
    service = result["services"][0]
    assert service["axle"] == "rear"
    assert service["axle_source"] == "validated_article_map"
    assert "catálogo confirmado" in service["axle_evidence"]


def test_explicit_description_overrides_validated_article_map():
    lookup = build_article_axle_lookup(
        {
            "schema": "carfast.invoice-article-axle-map.v1",
            "mappings": [{"supplier_key": "NIF:123", "article_reference": "PAD-42", "axle": "rear"}],
        }
    )
    result = build_document_service_proposals(
        {"run_id": "test", "document_id": "10", "total_extracted": "90", "supplier_group": "NIF:123"},
        [{**line(1, "CALÇOS FRT", "90,00"), "reference": "PAD-42"}],
        article_axle_map=lookup,
    )
    service = result["services"][0]
    assert service["axle"] == "front"
    assert service["axle_source"] == "description_explicit"


def test_unspecified_brake_part_inherits_single_explicit_invoice_context():
    result = build_document_service_proposals(
        document(),
        [line(1, "SUBSTITUICAO DISCO TRAVAO AF", "40,00"), line(2, "J.PASTILHAS TRA", "80,00")],
    )
    pad = next(item for item in result["services"] if item["service_code"] == "BRAKE.PAD")
    assert pad["axle"] == "front"
    assert pad["axle_source"] == "context_consistent"
    assert "eixo front inferido" in pad["confidence_reason"]


def test_brake_plate_with_de_supplies_explicit_context():
    result = build_document_service_proposals(
        document(),
        [line(1, "SUBSTITUICAO PLACAS DE TRAVAO AF", "33,08"), line(2, "J.PASTILHAS TRA", "144,14")],
    )
    pads = [item for item in result["services"] if item["service_code"] == "BRAKE.PAD"]
    assert len(pads) == 1
    assert pads[0]["axle"] == "front"


def test_unspecified_brake_part_stays_unresolved_with_competing_axles():
    result = build_document_service_proposals(
        document(),
        [
            line(1, "CALÇOS FRT", "40,00"),
            line(2, "CALÇOS TRÁS", "40,00"),
            line(3, "J.PASTILHAS TRA", "80,00"),
        ],
    )
    assert any(item["service_code"] == "BRAKE.PAD" and item["axle"] == "" for item in result["services"])


def test_parts_and_generic_labor_are_grouped_without_amount_duplication():
    result = build_document_service_proposals(
        document("79,95"),
        [line(1, "Calços travão FRT", "53,98"), line(2, "Mão de obra", "11,02", "LINE.LABOR")],
    )
    service = result["services"][0]
    assert Decimal(service["amount"]) == Decimal("65.00")
    assert service["source_line_ids"] == "10:1|10:2"
    assert service["parts"] == "Calços travão FRT"
    assert service["labor"] == "Mão de obra"
    assert result["reconciliation"]["service_plus_excluded_minus_source_lines"] == "0.00"


def test_tyre_and_balance_share_one_service_with_traceability():
    result = build_document_service_proposals(
        document(),
        [line(1, "215/70R15 BESTDRIVE", "172,49"), line(2, "Equilibragem jante", "13,01")],
    )
    assert len(result["services"]) == 1
    assert result["services"][0]["service_code"] == "TYRE.REPLACE"
    assert result["services"][0]["subcategory"] == "TYRE.BALANCE"
    assert result["services"][0]["source_line_ids"] == "10:1|10:2"


def test_lighting_lines_form_a_service():
    classified = classify_invoice_line(line(1, "Lâmpada 12V P21W", "2,11"))
    assert classified.service_code == "ELECTRIC.LIGHTING"


def test_common_part_patterns_cover_tyre_oil_disc_battery_and_brake_sensor():
    assert classify_invoice_line(line(1, "215/60R17 HANKOOK K125 96H", "191,40")).service_code == "TYRE.REPLACE"
    assert classify_invoice_line(line(2, "OLEO TOTAL INEO XTRA FIRST 0W20 LT", "184,80")).service_code == "FLUID.ENGINE_OIL"
    disc = classify_invoice_line(line(3, "JOGO DISCOS TR", "88,00"))
    assert (disc.service_code, disc.axle) == ("BRAKE.DISC", "rear")
    assert classify_invoice_line(line(4, "BATERIA", "247,13")).service_code == "ELECTRIC.BATTERY"
    assert classify_invoice_line(line(5, "AVISADOR DE TRAVAO", "11,32")).service_code == "BRAKE.SENSOR"


def test_document_projection_requires_all_relevant_lines_classified():
    result = build_document_service_proposals(
        document(),
        [line(1, "Calços travão FRT", "53,98"), line(2, "peça desconhecida", "10,00")],
    )
    assert result["document_projection"] == "services_review_required"
    assert result["unassigned_lines"][0]["source_line_id"] == "10:2"


def test_acceptance_document_688_splits_maintenance_diagnostic_and_brakes():
    result = build_document_service_proposals(
        {"run_id": "acceptance", "document_id": "688", "total_extracted": "469,04"},
        [
            line(1, "MUDANCA DE OLEO E FILTRO MOTOR OPERACAO DE SERVICO", "21,38"),
            line(2, "PROCURA DE PANE DIAGNÓSTICO - 4 NO VEICULO", "17,10"),
            line(3, "SIGOU - Ecolub 1L", "0,26"),
            line(4, "JUNTA BUJAO OLE", "1,08"),
            line(5, "FILTRO OLEO", "16,26"),
            line(6, "SUBSTITUICAO DISCO TRAVAO AF (2)", "38,48"),
            line(7, "J.PASTILHAS TRA", "143,42"),
        ],
    )
    assert {(item["service_code"], item["axle"]) for item in result["services"]} == {
        ("MAINT.OIL_INTERIM", ""),
        ("DIAG.GENERAL", ""),
        ("BRAKE.DISC", "front"),
        ("BRAKE.PAD", "front"),
    }


def test_acceptance_document_756_keeps_front_disc_and_both_pad_axles():
    result = build_document_service_proposals(
        {"run_id": "acceptance", "document_id": "756", "total_extracted": "531,40"},
        [
            line(1, "215/70R15 BESTDRIVE VAN SUMMER 109/107S", "172,49"),
            line(2, "EQUILIBRAGEM JANTE ESPECIAL", "11,38"),
            line(3, "CALÇOS FRT", "78,23"),
            line(4, "DISCOS FRT", "73,11"),
            line(5, "CALÇOS TRÁS", "58,81"),
            line(6, "LAMPADA H7", "8,00"),
            line(7, "LAMPADA 12V5W", "2,50"),
            line(8, "MÃO DE OBRA", "24,39", "LINE.LABOR"),
        ],
    )
    assert {(item["service_code"], item["axle"]) for item in result["services"]} == {
        ("TYRE.REPLACE", ""),
        ("BRAKE.PAD", "front"),
        ("BRAKE.DISC", "front"),
        ("BRAKE.PAD", "rear"),
        ("ELECTRIC.LIGHTING", ""),
    }


def test_acceptance_documents_816_and_1122_attach_labor_to_nearest_service():
    result_816 = build_document_service_proposals(
        {"run_id": "acceptance", "document_id": "816", "total_extracted": "315,56"},
        [
            line(1, "215/70R15 BESTDRIVE VAN SUMMER 109/107S", "172,49"),
            line(2, "EQUILIBRAGEM JANTE ESPECIAL", "13,01"),
            line(3, "CALÇOS TRAVAO FRT", "53,98"),
            line(4, "MÃO DE OBRA", "14,23", "LINE.LABOR"),
        ],
    )
    brake_816 = next(item for item in result_816["services"] if item["service_code"] == "BRAKE.PAD")
    assert brake_816["axle"] == "front"
    assert Decimal(brake_816["amount"]) == Decimal("68.21")

    result_1122 = build_document_service_proposals(
        {"run_id": "acceptance", "document_id": "1122", "total_extracted": "198,62"},
        [
            line(1, "SUBSTITUICAO LUZ AT", "11,38"),
            line(2, "SUBSTITUICAO 2 LÂMPADAS DE ILUMINAÇÃO", "13,65"),
            line(3, "LAMPADA 12V-P21/5W", "5,48"),
            line(4, "LAMPADA 12V-P21W", "2,11"),
            line(5, "SUBSTITUICAO PLACAS TRAVAO AT", "20,48"),
            line(6, "ENSAIO APOS TRABALHOS", "11,38"),
            line(7, "J.PASTILHAS TRA", "97,00"),
        ],
    )
    brake_1122 = next(item for item in result_1122["services"] if item["service_code"] == "BRAKE.PAD")
    assert brake_1122["axle"] == "rear"
    assert brake_1122["source_line_ids"] == "10:5|10:6|10:7"
