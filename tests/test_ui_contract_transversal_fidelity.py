from pathlib import Path
import os


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_global_geometry_is_encoded_once_in_the_contract_asset():
    css = _read("app/static/css/ui-contract-v1.css")
    required = (
        "grid-template-columns: 208px minmax(0,1fr)",
        "height: 36px; min-height: 36px",
        "grid-template-columns: 16px minmax(0,1fr)",
        "height: 52px; min-height: 52px",
        "height: 34px; padding-block: 4px",
        "height: 44px; padding-block: 5px",
        "grid-template-columns: 260px minmax(0,1fr) 300px",
        "grid-template-columns: 250px minmax(0,1fr)",
        "grid-template-columns: minmax(0,1fr) 350px",
        "grid-template-columns: 250px minmax(0,1fr) 350px",
        "grid-template-columns: 280px minmax(0,1fr)",
    )
    for contract in required:
        assert contract in css, contract


def test_process_email_documents_and_admin_use_real_workbench_markup():
    process = _read("app/templates/clean_process_center.html")
    email = _read("app/templates/clean_email_inbox.html")
    documents = _read("app/templates/clean_documentation_triage.html")
    admin = _read("app/templates/clean_admin.html")

    assert "process-command-catalog" in process
    assert "process-command-queue" in process
    assert "process-command-summary" in process
    assert "ui-email-triage-workbench" in email
    assert 'id="email-preview-panel"' in email
    assert "visual-document-queue" in documents
    assert "visual-document-preview" in documents
    assert "visual-document-review" in documents
    assert "admin-contract-master" in admin
    assert "admin-contract-detail" in admin
    email_js = _read("app/static/js/email.js")
    assert "const usePanel = Boolean(previewPanel);" in email_js
    assert 'matchMedia("(min-width: 1025px)")' not in email_js


def test_partner_navigation_is_domain_only_and_admin_navigation_is_separate():
    partners = _read("app/templates/_supplier_context_nav.html")
    admin = _read("app/templates/_admin_context_nav.html")
    for label in ("Parceiros", "Tipos e serviços", "Contratos", "Configuração"):
        assert label in partners
    for forbidden in ("Utilizadores", "Perfis e permissões", ">Categorias<", ">Email<"):
        assert forbidden not in partners
    for label in ("Utilizadores", "Perfis e permissões", "Categorias", "Email"):
        assert label in admin


def test_inventory_covers_dynamic_overlays_adapters_and_blocked_legacy_surfaces():
    import json
    from app.main import app
    from starlette.routing import Match

    artifact = json.loads(_read("docs/architecture/HTML_SURFACE_INVENTORY.json"))
    assert artifact["baseline_surface_count"] == 136
    assert artifact["surface_count"] >= 136
    classes = {row["classification"] for row in artifact["surfaces"]}
    assert {"canonical", "detail", "overlay", "portal", "adapter", "legacy_blocked"} <= classes

    live = {
        (route.path, getattr(getattr(route, "endpoint", None), "__name__", ""))
        for route in app.routes
    }
    resolved = 0
    for surface in artifact["surfaces"]:
        route_key = (surface["path"], surface["handler"])
        source = ROOT / surface["source"]
        assert source.is_file(), surface
        source_text = source.read_text(encoding="utf-8")
        if surface["classification"] == "legacy_blocked":
            # Historical workshop endpoints remain callable for zero-loss
            # compatibility, but are explicitly classified and excluded from the
            # canonical visual adapter set.  Prove their implementation still
            # exists rather than treating a JSON row as coverage.
            assert f"def {surface['handler']}(" in source_text or f"async def {surface['handler']}(" in source_text
        else:
            assert route_key in live, ("inventoried surface is not executable", surface)
            sample_path = surface["path"]
            for parameter in ("document_id", "vehicle_id", "process_id", "task_id", "supplier_id", "message_id", "user_id", "role_id", "id"):
                sample_path = sample_path.replace("{" + parameter + "}", "1")
            scope = {"type": "http", "method": "GET", "path": sample_path, "root_path": ""}
            matches = [route for route in app.routes if route.matches(scope)[0] is Match.FULL]
            assert any(getattr(getattr(route, "endpoint", None), "__name__", "") == surface["handler"] for route in matches), (
                "nominal route smoke failed", surface, sample_path
            )
            resolved += 1
    assert resolved == sum(1 for row in artifact["surfaces"] if row["classification"] != "legacy_blocked")


def test_all_nonlegacy_surfaces_execute_nominal_http_smoke(authenticated_client, db_session, monkeypatch):
    """Execute every inventoried HTML handler; missing fixture IDs may 404, never 5xx."""
    import json
    import re
    from app.core.config import settings
    from app.web import email as email_web
    from sqlalchemy.orm import sessionmaker

    monkeypatch.setattr(settings, "visual_foundation_enabled", True)
    monkeypatch.setattr(
        email_web,
        "SessionLocal",
        sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False),
    )
    artifact = json.loads(_read("docs/architecture/HTML_SURFACE_INVENTORY.json"))
    results = []
    for surface in artifact["surfaces"]:
        if surface["classification"] == "legacy_blocked":
            continue
        sample_path = re.sub(r"\{[^}]+\}", "1", surface["path"])
        response = authenticated_client.get(sample_path, follow_redirects=False)
        results.append((surface["path"], response.status_code))
        assert response.status_code < 500, (surface, sample_path, response.status_code, response.text[:240])
        if (
            sample_path.startswith("/v2-clean")
            and response.status_code == 200
            and "text/html" in response.headers.get("content-type", "")
        ):
            assert (
                "ui-contract-v1" in response.text
                or "ui-contract-v1.css" in response.text
                or surface["classification"] in {"portal", "adapter"}
            ), surface
    assert len(results) == 125


def test_tasks_keep_operational_context_visible_at_dense_desktop_height():
    css = _read("app/static/css/ui-contract-v1.css")
    assert ".clean-task-table td > small {\n    display: inline;" in css
    assert ".clean-task-table .clean-task-relation-list {\n    display: inline-flex;" in css
    assert ".clean-task-table .clean-task-relation-list { display: none; }" not in css


def test_document_review_tabs_are_legible_and_have_an_active_state():
    css = _read("app/static/css/ui-contract-v1.css")
    assert ".visual-document-review-tabs {" in css
    assert ".visual-document-review-tabs a {" in css
    assert '.visual-document-review-tabs a[aria-current="page"]' in css


def test_representative_contract_pages_render_with_the_canonical_shell(authenticated_client, db_session, monkeypatch, tmp_path):
    from datetime import date, timedelta
    from app.core.config import settings
    from app.services.email_postmark import ingest_inbound
    from app.web import email as email_web
    from app.models import Document, DocumentWorkflowState, EmailMessage, Role, Task, User, UserRole
    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    monkeypatch.setattr(settings, "visual_foundation_enabled", True)
    document_root = tmp_path / "document-archive"
    document_root.mkdir()
    preview_file = document_root / "synthetic-contract-preview.pdf"
    preview_file.write_bytes(
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF\n"
    )
    monkeypatch.setattr(settings, "document_archive_root", str(document_root))
    capture_only = os.getenv("CARFAST_UI_CONTRACT_CAPTURE_ONLY")
    admin_user = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    operator_role = db_session.scalar(select(Role).where(Role.code == "operator"))
    assert admin_user and operator_role
    grant = UserRole(user_id=admin_user.id, role_id=operator_role.id)
    if capture_only in (None, "processes"):
        db_session.add(grant)
    for index in range(6):
        db_session.add(
            Task(
                title=f"Tarefa operacional sintética {index + 1}",
                task_type="operational_task",
                category="Operação",
                subcategory="Validação",
                status="new",
                priority="high" if index < 2 else "normal",
                due_on=date.today() + timedelta(days=index),
                assigned_to_id=admin_user.id,
                created_by_id=admin_user.id,
            )
        )
    document_ids = []
    for index in range(6):
        document = Document(
            title=f"Documento sintético {index + 1}",
            document_type="unknown_document",
            classification="triage",
            source="document_inbox",
            entry_channel="document_inbox",
            original_name="synthetic-contract-preview.pdf",
            file_name="synthetic-contract-preview.pdf",
            file_type="pdf",
            file_size=preview_file.stat().st_size,
            storage_provider="local",
            storage_path=str(preview_file),
            status="pending_triage",
        )
        db_session.add(document)
        db_session.flush()
        document_ids.append(document.id)
        db_session.add(
            DocumentWorkflowState(
                document_id=document.id,
                ingestion_status="completed",
                association_status="unassociated",
                extraction_status="extracted",
                validation_status="pending",
                destination_status="triage",
                suggested_invoice_nature="operacional",
                suggestion_confidence=0.88 + index / 100,
            )
        )
    db_session.commit()
    monkeypatch.setattr(
        email_web,
        "SessionLocal",
        sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False),
    )
    email_thread, _created = ingest_inbound(
        db_session,
        {
            "MessageID": "ui-contract-email-1",
            "From": "synthetic.sender@example.invalid",
            "FromName": "Origem sintética",
            "To": "hub@carfast.pt",
            "Subject": "Pedido sintético para classificação",
            "TextBody": "Conteúdo exclusivamente sintético para evidência visual.",
            "HtmlBody": "<p>Conteúdo exclusivamente sintético para evidência visual.</p>",
        },
    )
    email_message = db_session.scalar(
        select(EmailMessage).where(EmailMessage.thread_id == email_thread.id)
    )
    assert email_message
    pages = {
        "dashboard": ("/v2-clean", "visual-dashboard-heading"),
        "tasks": ("/v2-clean/tasks", "visual-service-desk"),
        "processes": ("/v2-clean/processes", "process-command-layout"),
        "email": (f"/v2-clean/email?selected={email_thread.id}", "ui-email-triage-workbench"),
        "documents": (f"/v2-clean/documentation/triage?selected={document_ids[0]}", "visual-document-grid"),
        "admin": ("/v2-clean/admin/roles", "clean-admin-role-workspace"),
        "partners": ("/v2-clean/suppliers", "partner-context-nav"),
    }
    capture_dir = os.getenv("CARFAST_UI_CONTRACT_CAPTURE_DIR")
    for name, (path, marker) in pages.items():
        if capture_only and name != capture_only:
            continue
        if capture_dir:
            print(f"capture:{path}", flush=True)
        response = authenticated_client.get(path)
        assert response.status_code == 200, path
        assert 'id="visual-sidebar"' in response.text
        assert marker in response.text, path
        if capture_dir:
            target = Path(capture_dir)
            target.mkdir(parents=True, exist_ok=True)
            (target / f"{name}.html").write_text(response.text, encoding="utf-8")
            if name == "email":
                preview = authenticated_client.get(f"/v2-clean/email/{email_thread.id}/preview")
                assert preview.status_code == 200
                (target / "email-preview.html").write_text(preview.text, encoding="utf-8")
                body = authenticated_client.get(f"/v2-clean/email/messages/{email_message.id}/body")
                assert body.status_code == 200
                (target / "email-body.html").write_text(body.text, encoding="utf-8")
            if name == "documents":
                preview = authenticated_client.get(f"/v2-clean/documents/{document_ids[0]}/file?inline=1")
                assert preview.status_code == 200
                (target / "document-preview.pdf").write_bytes(preview.content)
        if name == "processes" and capture_only in (None, "processes"):
            db_session.delete(grant)
            db_session.commit()
