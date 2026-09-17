from sqlalchemy import select

from app.models.documents import Document, DocumentLink
from app.models.management_center import ManagementHistory, ManagementProcess, SupplierAuditCase, SupplierAuditEmailDraft, SupplierAuditParty
from app.models.vehicles import Vehicle
from app.models.stock import StockSupplier


def _vehicle(db_session):
    vehicle = Vehicle(plate="ZZ-00-ZZ", vin="VF7TESTSUPPLIERAUDIT", active=True)
    db_session.add(vehicle); db_session.commit(); db_session.refresh(vehicle)
    return vehicle


def _supplier(db_session):
    supplier = StockSupplier(name="Fornecedor de teste", active=True)
    db_session.add(supplier); db_session.commit(); db_session.refresh(supplier)
    return supplier


def test_supplier_audit_lifecycle_reuses_process_vehicle_documents_and_history(authenticated_client, db_session):
    vehicle = _vehicle(db_session)
    supplier = _supplier(db_session)
    response = authenticated_client.post("/v2-clean/processes/supplier-audits", data={"title": "Manutenção possivelmente prematura", "supplier_id": supplier.id, "vehicle_id": vehicle.id, "problem_type": "premature_maintenance", "suspicion_description": "Intervalo observado inferior ao plano, por verificar.", "priority": "high"}, follow_redirects=False)
    assert response.status_code == 303
    audit = db_session.scalar(select(SupplierAuditCase))
    process = db_session.get(ManagementProcess, audit.process_id)
    assert process.internal_reference.startswith("AF-")
    assert audit.assessment_grade == "suspicion"
    assert "fatura/OR" in audit.missing_elements_json
    assert db_session.scalar(select(SupplierAuditParty).where(SupplierAuditParty.audit_id == audit.id, SupplierAuditParty.supplier_id == supplier.id))

    authenticated_client.post(f"/v2-clean/processes/supplier-audits/{audit.id}/verification", data={"assessment_grade": "probable", "status": "waiting_information", "verification_data": "Plano confirmado; motivo ainda desconhecido.", "missing_elements": "motivo técnico\nautorização"})
    db_session.expire_all(); assert db_session.get(SupplierAuditCase, audit.id).assessment_grade == "probable"
    assert db_session.get(ManagementProcess, process.id).status == "waiting_information"

    authenticated_client.post(f"/v2-clean/processes/supplier-audits/{audit.id}/parties", data={"entity_name": "Oficina de teste", "role": "oficina", "request_text": "Enviar OR", "response_status": "waiting"})
    assert db_session.scalar(select(SupplierAuditParty).where(SupplierAuditParty.audit_id == audit.id))

    document = Document(original_name="fatura-teste.pdf", file_name="fatura-teste.pdf", storage_path="tests/fatura-teste.pdf", vehicle_id=vehicle.id)
    db_session.add(document); db_session.commit()
    authenticated_client.post(f"/v2-clean/processes/supplier-audits/{audit.id}/documents", data={"document_id": document.id, "category": "invoice"})
    assert db_session.scalar(select(DocumentLink).where(DocumentLink.entity_type == "supplier_audit", DocumentLink.entity_id == str(audit.id)))
    assert db_session.get(Document, document.id)
    assert db_session.scalars(select(ManagementHistory).where(ManagementHistory.process_id == process.id)).all()


def test_email_is_only_versioned_draft_and_conclusion_is_human(authenticated_client, db_session):
    vehicle = _vehicle(db_session)
    supplier = _supplier(db_session)
    authenticated_client.post("/v2-clean/processes/supplier-audits", data={"title": "Garantia por analisar", "supplier_id": supplier.id, "vehicle_id": vehicle.id, "problem_type": "warranty_refusal", "suspicion_description": "Recusa ainda sem fundamento documental."})
    audit = db_session.scalar(select(SupplierAuditCase))
    response = authenticated_client.post(f"/v2-clean/processes/supplier-audits/{audit.id}/drafts", data={"recipient": "fornecedor@example.test", "subject": "Pedido de elementos", "body": "Solicitamos documentação.", "status": "authorized"}, follow_redirects=False)
    assert response.status_code == 303
    draft = db_session.scalar(select(SupplierAuditEmailDraft))
    assert draft.status == "authorized" and draft.version == 1
    authenticated_client.post(
        f"/v2-clean/processes/supplier-audits/{audit.id}/drafts",
        data={
            "revision_of_id": draft.id,
            "recipient": "fornecedor@example.test",
            "subject": "Pedido de elementos revisto",
            "body": "Solicitamos a documentação em falta.",
            "status": "ready_review",
        },
    )
    revision = db_session.scalar(
        select(SupplierAuditEmailDraft).where(
            SupplierAuditEmailDraft.revision_of_id == draft.id
        )
    )
    assert revision.version == 2

    authenticated_client.post(f"/v2-clean/processes/supplier-audits/{audit.id}/conclusion", data={"conclusion": "inconclusive", "cause": "Documentos em falta", "final_result": "Sem reclamação nesta fase"})
    db_session.expire_all(); audit = db_session.get(SupplierAuditCase, audit.id)
    assert audit.conclusion == "inconclusive"
    assert db_session.get(ManagementProcess, audit.process_id).status == "closed"


def test_vehicle_entry_point_is_contextual(authenticated_client, db_session):
    vehicle = _vehicle(db_session)
    response = authenticated_client.get(f"/v2-clean/fleet/{vehicle.id}")
    assert response.status_code == 200
    assert f"/v2-clean/processes/supplier-audits?vehicle_id={vehicle.id}" in response.text
    form = authenticated_client.get(f"/v2-clean/processes/supplier-audits?vehicle_id={vehicle.id}")
    assert 'name="plate"' in form.text
    assert 'value="ZZ-00-ZZ"' in form.text


def test_plate_input_links_existing_vehicle_and_rejects_unknown_plate(authenticated_client, db_session):
    vehicle = _vehicle(db_session)
    supplier = _supplier(db_session)
    payload = {
        "title": "Reparação demorada",
        "supplier_id": supplier.id,
        "problem_type": "delayed_repair",
        "suspicion_description": "Prazo por confirmar.",
    }
    response = authenticated_client.post(
        "/v2-clean/processes/supplier-audits",
        data={**payload, "plate": "zz00zz"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    audit = db_session.scalar(select(SupplierAuditCase))
    assert audit.vehicle_id == vehicle.id
    assert db_session.get(ManagementProcess, audit.process_id).plate == "ZZ-00-ZZ"
    detail = authenticated_client.get(f"/v2-clean/processes/supplier-audits/{audit.id}")
    assert "Matrícula <strong>ZZ-00-ZZ</strong>" in detail.text

    unknown = authenticated_client.post(
        "/v2-clean/processes/supplier-audits",
        data={**payload, "plate": "AA-99-AA"},
        follow_redirects=False,
    )
    assert unknown.headers["location"].endswith("?error=plate_not_found")
    assert db_session.query(SupplierAuditCase).count() == 1


def test_detail_phases_start_collapsed_and_keep_actions_available(authenticated_client, db_session):
    vehicle = _vehicle(db_session)
    supplier = _supplier(db_session)
    authenticated_client.post(
        "/v2-clean/processes/supplier-audits",
        data={
            "title": "Reparação demorada",
            "supplier_id": supplier.id,
            "vehicle_id": vehicle.id,
            "problem_type": "delayed_repair",
            "suspicion_description": "Prazo por confirmar.",
        },
    )
    audit = db_session.scalar(select(SupplierAuditCase))
    response = authenticated_client.get(f"/v2-clean/processes/supplier-audits/{audit.id}")
    assert response.status_code == 200
    for phase in ("registration", "verification", "contacts", "conclusion"):
        assert f'id="{phase}" name="supplier-audit-phase"' in response.text
    assert 'name="supplier-audit-phase" open' not in response.text
    assert response.text.count('class="supplier-audit-action"') == 2
    assert "openAuditPhaseFromHash" in response.text


def test_supplier_is_required_and_vehicle_is_optional(authenticated_client, db_session):
    supplier = _supplier(db_session)
    response = authenticated_client.post("/v2-clean/processes/supplier-audits", data={"title": "Erro de faturação", "supplier_id": supplier.id, "problem_type": "billing_error", "suspicion_description": "Valor por confirmar."}, follow_redirects=False)
    assert response.status_code == 303
    audit = db_session.scalar(select(SupplierAuditCase))
    assert audit.vehicle_id is None
    assert db_session.scalar(select(SupplierAuditParty).where(SupplierAuditParty.audit_id == audit.id, SupplierAuditParty.supplier_id == supplier.id))
    listing = authenticated_client.get(f"/v2-clean/processes/supplier-audits?supplier_id={supplier.id}")
    assert listing.status_code == 200
    assert "Erro de faturação" in listing.text
