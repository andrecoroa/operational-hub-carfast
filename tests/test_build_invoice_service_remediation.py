from scripts.build_invoice_service_remediation import build_import_row


def test_validation_artifact_matches_import_contract_and_forces_pending():
    row = build_import_row(
        {
            "document_id": "10",
            "vehicle_id_associated": "7",
            "document_date_extracted": "2026-01-02",
            "km_source": "12345",
        },
        {
            "stable_key": "batch:10:S01:BRAKE.PAD:front",
            "service_code": "BRAKE.PAD",
            "subcategory": "",
            "axle": "front",
            "axle_source": "description_explicit",
            "axle_evidence": "FRT",
            "source_line_ids": "10:1",
            "service_text": "Pastilhas frente",
            "parts": "Pastilhas frente",
            "labor": "",
            "amount": "42.50",
            "confidence": "0.90",
            "confidence_reason": "descrição explícita",
            "document_projection": "services_classified",
        },
        "https://example.invalid/document/10",
    )

    assert row["service_text"] == "Pastilhas frente"
    assert str(row["amount"]) == "42.50"
    assert row["service_date"] == "2026-01-02"
    assert row["status"] == "pending_validation"
    assert "source_descriptions" not in row
    assert "service_amount" not in row
