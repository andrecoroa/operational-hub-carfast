from __future__ import annotations

import json

import pytest

from app.platform.anonymized_stream import (
    EphemeralSynthesizer,
    UnsafePayload,
    stream_jsonl,
    transform_row,
    validate_payload,
)
from scripts.export_anonymized_dataset import batched_rows

KEY = b"fixture-only-key-material-32-bytes!!"


def test_stable_synthetic_values_and_fk_preservation() -> None:
    synth = EphemeralSynthesizer(KEY)
    first = transform_row(
        "users",
        {"id": 1, "active": True, "email": "a@real.pt", "name": "A", "password_hash": "x"},
        synth,
    )
    second = transform_row(
        "users",
        {"id": 1, "active": True, "email": "a@real.pt", "name": "A", "password_hash": "y"},
        synth,
    )
    assert first == second
    assert first["id"] == 1
    assert first["email"].endswith("@invalid.example")
    assert "password_hash" not in first


def test_free_text_ocr_and_document_locations_are_never_exported() -> None:
    output = transform_row(
        "documents",
        {
            "id": 5,
            "status": "received",
            "document_type": "invoice",
            "classification": "supplier",
            "vehicle_id": None,
            "task_id": 9,
            "workshop_process_id": None,
            "incident_id": None,
            "title": "secret",
            "source_sender": "real@example.pt",
            "source_subject": "subject",
            "original_name": "secret.pdf",
            "file_name": "secret.pdf",
            "file_size": 10,
            "storage_path": "/secret",
            "storage_key": "secret",
            "external_url": None,
            "folder_path": "/folder",
            "file_hash": "real",
            "plate": None,
            "customer_name": None,
            "supplier_name": None,
        },
        EphemeralSynthesizer(KEY),
    )
    assert "file_name" not in output and "storage_path" not in output
    assert output["fixture_object_count"] == 1
    assert output["fixture_bytes"] > 0
    assert len(output["fixture_sha256"]) == 64
    assert "ocr_text" not in output and "extracted_text" not in output


def test_unknown_table_or_field_fails_closed() -> None:
    synth = EphemeralSynthesizer(KEY)
    with pytest.raises(UnsafePayload):
        transform_row("unknown", {"id": 1}, synth)
    with pytest.raises(UnsafePayload):
        transform_row("users", {"id": 1, "unexpected": "x"}, synth)


@pytest.mark.parametrize("value", ["real@example.pt", "501234567", "912345678", "AA-11-BB"])
def test_recognizable_values_are_rejected(value: str) -> None:
    with pytest.raises(UnsafePayload):
        validate_payload("probe", {"safe": value})


def test_unclassified_free_text_is_rejected() -> None:
    with pytest.raises(UnsafePayload):
        validate_payload("probe", {"safe": "this is unrestricted prose"})


def test_formal_synthetic_token_is_not_rejected_by_numeric_heuristics() -> None:
    validate_payload("probe", {"safe": "Company-123456789abc"})
    validate_payload("probe", {"safe": "user-123456789abc@invalid.example"})


def test_stream_is_incremental_jsonl() -> None:
    records = (
        (
            "users",
            {
                "id": i,
                "active": True,
                "email": f"u{i}@real.pt",
                "name": f"U{i}",
                "password_hash": "x",
            },
        )
        for i in range(3)
    )
    chunks = stream_jsonl(records, EphemeralSynthesizer(KEY))
    first = json.loads(next(chunks))
    assert first["data"]["id"] == 0
    assert [json.loads(chunk)["data"]["id"] for chunk in chunks] == [1, 2]


def test_source_cursor_fetches_in_bounded_batches() -> None:
    class Cursor:
        batches = [[{"id": 1}], [{"id": 2}], []]

        def fetchmany(self, size: int):
            assert size == 250
            return self.batches.pop(0)

    assert list(batched_rows(Cursor(), 250)) == [{"id": 1}, {"id": 2}]
