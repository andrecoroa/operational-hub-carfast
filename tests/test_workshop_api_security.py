from pathlib import Path

import pytest
from fastapi import HTTPException

import app.api.routes.workshop as workshop_api


def test_workshop_api_rejects_anonymous_read_and_write(client):
    read_response = client.get("/api/workshop/process-config")
    write_response = client.post("/api/workshop/processes/999/services", json={})

    assert read_response.status_code == 401
    assert write_response.status_code == 401


def test_workshop_api_accepts_authenticated_clean_session(authenticated_client):
    response = authenticated_client.get("/api/workshop/process-config")

    assert response.status_code == 200


def test_workshop_api_separates_read_and_write_permissions(
    authenticated_client,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.api.auth.user_has_permission",
        lambda _db, _user, permission: permission == "workshop.read",
    )

    read_response = authenticated_client.get("/api/workshop/process-config")
    write_response = authenticated_client.post(
        "/api/workshop/processes/999/services",
        json={},
    )

    assert read_response.status_code == 200
    assert write_response.status_code == 403


def test_workshop_api_rejects_invalid_bearer_token(client):
    response = client.get(
        "/api/workshop/process-config",
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired token."


def test_workshop_report_source_must_be_inside_document_archive(
    tmp_path: Path,
    monkeypatch,
):
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    report = archive_root / "report.pdf"
    report.write_bytes(b"%PDF-1.4")
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(
        workshop_api.settings,
        "document_archive_root",
        str(archive_root),
    )

    assert workshop_api._authorized_report_source(str(report)) == str(report.resolve())
    with pytest.raises(HTTPException) as external_error:
        workshop_api._authorized_report_source("http://127.0.0.1/internal.pdf")
    with pytest.raises(HTTPException) as outside_error:
        workshop_api._authorized_report_source(str(outside))

    assert external_error.value.status_code == 422
    assert outside_error.value.status_code == 422


def test_workshop_report_upload_enforces_size_limit(
    authenticated_client,
    monkeypatch,
):
    monkeypatch.setattr(workshop_api, "_get_process_or_404", lambda _db, _id: object())
    monkeypatch.setattr(workshop_api, "MAX_TECHNICAL_REPORT_UPLOAD_BYTES", 8)
    report_code = next(iter(workshop_api.REPORT_CODES))

    response = authenticated_client.post(
        (
            "/api/workshop/processes/1/technical-reports/extract-upload"
            f"?report_code={report_code}"
        ),
        files={"file": ("report.pdf", b"123456789", "application/pdf")},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "O relatório excede o limite de 25 MB."
