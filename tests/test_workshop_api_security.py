from pathlib import Path

import pytest
from fastapi import HTTPException

import app.api.routes.workshop as workshop_api
import app.web.router as web_router
from app.models.documents import Document
from app.services import storage


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


def test_archive_file_resolution_rejects_paths_outside_configured_root(
    tmp_path: Path,
    monkeypatch,
):
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    inside = archive_root / "inside.pdf"
    inside.write_bytes(b"%PDF-1.4")
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(
        web_router.settings,
        "document_archive_root",
        str(archive_root),
    )

    assert web_router._resolved_archive_file(inside) == inside.resolve()
    assert web_router._resolved_archive_file("inside.pdf") == inside.resolve()
    assert web_router._resolved_archive_file(outside) is None
    assert web_router._resolved_archive_file("../outside.pdf") is None


def test_clean_document_file_rejects_outside_archive(
    authenticated_client,
    db_session,
    tmp_path: Path,
    monkeypatch,
):
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(
        web_router.settings,
        "document_archive_root",
        str(archive_root),
    )
    document = Document(
        title="Documento fora do arquivo",
        document_type="workshop_supplier_invoice",
        classification="workshop",
        source="v2_clean_manual",
        entry_channel="upload",
        original_name="outside.pdf",
        file_name="outside.pdf",
        storage_provider="local",
        storage_path=str(outside),
        status="received",
    )
    db_session.add(document)
    db_session.commit()

    response = authenticated_client.get(
        f"/v2-clean/documents/{document.id}/file",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith(f"/v2-clean/documents/{document.id}?file_missing=1")


def test_management_document_requires_management_permission(
    authenticated_client,
    db_session,
    tmp_path: Path,
    monkeypatch,
):
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    document_path = archive_root / "management.pdf"
    document_path.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(
        web_router.settings,
        "document_archive_root",
        str(archive_root),
    )
    monkeypatch.setattr(web_router, "can_view_management_documents", lambda _request: False)
    document = Document(
        title="Plano financeiro",
        document_type="financial_plan",
        classification="management",
        source="v2_clean_manual",
        entry_channel="upload",
        original_name=document_path.name,
        file_name=document_path.name,
        storage_provider="local",
        storage_path=str(document_path),
        confidentiality_level="management",
        status="received",
    )
    db_session.add(document)
    db_session.commit()

    response = authenticated_client.get(
        f"/v2-clean/documents/{document.id}/file",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/v2-clean?error=forbidden"


def test_import_storage_uses_configured_persistent_archive(
    tmp_path: Path,
    monkeypatch,
):
    archive_root = tmp_path / "archive"
    monkeypatch.setattr(storage.settings, "document_archive_root", str(archive_root))

    import_root = storage.persistent_import_storage_root("task bulk")

    assert import_root == (archive_root / "_imports" / "task_bulk").resolve()
    assert import_root.is_dir()
