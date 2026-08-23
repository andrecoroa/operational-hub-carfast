from __future__ import annotations

import json

import pytest

from app.platform.anonymized_stream import (
    FIELD_MAP,
    EphemeralSynthesizer,
    UnsafePayload,
    stream_jsonl,
    transform_row,
    validate_payload,
)
from scripts.export_anonymized_dataset import SOURCE_SCHEMA_CONTRACT, batched_rows, schema_preflight

KEY = b"fixture-only-key-material-32-bytes!!"


def test_stable_synthetic_values_without_raw_ids() -> None:
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
    assert first["id"].startswith("R-user-") and first["id"] != "1"
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


@pytest.mark.parametrize(
    "field,value",
    [
        ("email", "real@example.pt"),
        ("name", "501234567"),
        ("name", "912345678"),
        ("name", "AA-11-BB"),
    ],
)
def test_recognizable_values_are_rejected_on_allowlisted_fields(field: str, value: str) -> None:
    payload = {"id": "R-user-0123456789abcdef", "active": True, field: value}
    with pytest.raises(UnsafePayload, match="non-synthetic value"):
        validate_payload("users", payload)


def test_unclassified_free_text_is_rejected() -> None:
    with pytest.raises(UnsafePayload, match="non-synthetic value"):
        validate_payload(
            "users",
            {"id": "R-user-0123456789abcdef", "active": True, "name": "this is unrestricted prose"},
        )


def test_formal_synthetic_token_is_not_rejected_by_numeric_heuristics() -> None:
    validate_payload(
        "users",
        {
            "id": "R-user-0123456789abcdef",
            "active": True,
            "name": "Person-123456789abc",
            "email": "user-123456789abc@invalid.example",
        },
    )


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
    assert first["schema"] == 2 and first["pilot"] == "eight-table"
    assert first["data"]["id"].startswith("R-user-")
    assert all(json.loads(chunk)["data"]["id"].startswith("R-user-") for chunk in chunks)


def test_references_share_namespace_and_preserve_relationships() -> None:
    synth = EphemeralSynthesizer(KEY)
    user = transform_row(
        "users", {"id": 7, "active": True, "email": None, "name": None, "password_hash": "x"}, synth
    )
    task = transform_row(
        "tasks",
        {
            "id": 9,
            "status": "open",
            "assigned_to_id": 7,
            "parent_task_id": None,
            "team_id": None,
            "created_by_id": 7,
            "title": None,
            "description": None,
            "customer_name": None,
            "customer_contact": None,
            "customer_email": None,
            "customer_phone": None,
            "plate": None,
        },
        synth,
    )
    audit = transform_row(
        "audit_log",
        {
            "id": 11,
            "user_id": 7,
            "action": "task.updated",
            "entity_type": "task",
            "entity_id": "9",
            "detail": None,
            "before_json": None,
            "after_json": None,
        },
        synth,
    )
    assert task["assigned_to_id"] == user["id"] == task["created_by_id"]
    assert audit["user_id"] == user["id"]
    assert audit["entity_id"] == task["id"]
    assert task["id"] != "9" and audit["entity_id"] != "9"


@pytest.mark.parametrize("field,value", [("status", "hacked"), ("status", "OPEN NOW")])
def test_noncanonical_values_fail_closed(field: str, value: str) -> None:
    with pytest.raises(UnsafePayload):
        validate_payload("tasks", {"id": "R-task-0123456789abcdef", field: value})


def test_document_fixture_exists_only_for_logical_object() -> None:
    base = {
        field: None
        for field in __import__("app.platform.anonymized_stream", fromlist=["FIELD_MAP"]).FIELD_MAP[
            "documents"
        ]
    }
    base.update(id=1, status="received")
    without_object = transform_row("documents", base, EphemeralSynthesizer(KEY))
    assert without_object["fixture_object_count"] == 0 and without_object["fixture_sha256"] is None


def test_source_cursor_fetches_in_bounded_batches() -> None:
    class Cursor:
        batches = [[{"id": 1}], [{"id": 2}], []]

        def fetchmany(self, size: int):
            assert size == 250
            return self.batches.pop(0)

    assert list(batched_rows(Cursor(), 250)) == [{"id": 1}, {"id": 2}]


def test_schema_preflight_aborts_on_drift_without_row_reads() -> None:
    class Result:
        def __init__(self, table: str):
            self.table = table

        def fetchall(self):
            return [
                (
                    field,
                    "integer"
                    if self.table == "users" and field == "email"
                    else next(iter(column.types)),
                    "YES" if column.nullable else "NO",
                )
                for field, column in SOURCE_SCHEMA_CONTRACT[self.table].items()
            ]

    class Connection:
        calls = 0

        def execute(self, query: str, params: tuple[str]):
            assert "information_schema.columns" in query and params
            self.calls += 1
            return Result(params[0])

    connection = Connection()
    with pytest.raises(RuntimeError, match="type/nullability drift"):
        schema_preflight(connection)
    assert connection.calls == 1


def test_versioned_schema_contract_covers_every_selected_column() -> None:
    assert {table: set(columns) for table, columns in SOURCE_SCHEMA_CONTRACT.items()} == {
        table: set(columns) for table, columns in FIELD_MAP.items()
    }
    assert SOURCE_SCHEMA_CONTRACT["audit_log"]["entity_id"].types == {
        "character varying",
        "character",
        "text",
    }
    assert SOURCE_SCHEMA_CONTRACT["stock_suppliers"]["tax_id"].types == {
        "character varying",
        "character",
        "text",
    }


@pytest.mark.parametrize("value", ["customer.joao", "phase_912345678", "invoice.maria"])
def test_open_ended_technical_tokens_are_never_exported_raw(value: str) -> None:
    synth = EphemeralSynthesizer(KEY)
    process = transform_row(
        "management_processes",
        {
            "id": 1,
            "status": "open",
            "process_type_id": 2,
            "phase": value,
            "priority": "normal",
            "internal_reference": None,
            "plate": None,
            "customer_name": None,
            "driver_name": None,
            "title": None,
            "pending_detail": None,
            "raw_summary_json": None,
        },
        synth,
    )
    audit = transform_row(
        "audit_log",
        {
            "id": 2,
            "user_id": None,
            "action": value,
            "entity_type": None,
            "entity_id": None,
            "detail": None,
            "before_json": None,
            "after_json": None,
        },
        synth,
    )
    assert process["phase"].startswith("Category-") and process["phase"] != value
    assert audit["action"].startswith("Category-") and audit["action"] != value
    assert FIELD_MAP["documents"]["document_type"].action == "synthetic"
    assert FIELD_MAP["documents"]["classification"].action == "synthetic"


def test_broken_pipe_propagates_and_does_not_continue() -> None:
    class BrokenOutput:
        def write(self, _: bytes) -> None:
            raise BrokenPipeError

    chunks = stream_jsonl(
        [("users", {"id": 1, "active": True, "email": None, "name": None, "password_hash": "x"})],
        EphemeralSynthesizer(KEY),
    )
    with pytest.raises(BrokenPipeError):
        BrokenOutput().write(next(chunks))
