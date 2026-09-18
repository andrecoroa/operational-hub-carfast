from sqlalchemy import select

from app.models.documents import Document, DocumentLink
from app.models.management_center import (
    ManagementHistory,
    ManagementProcess,
    ManagementProcessAssociation,
    SupplierAuditCase,
    SupplierAuditEmailDraft,
    SupplierAuditParty,
)
from app.models.stock import StockSupplier
from app.models.tasks import Task, TaskComment, TaskDocument, TaskHistory
from app.models.vehicles import Vehicle


def _vehicle(db_session):
    vehicle = Vehicle(plate="ZZ-00-ZZ", vin="VF7TESTSUPPLIERAUDIT", active=True)
    db_session.add(vehicle)
    db_session.commit()
    db_session.refresh(vehicle)
    return vehicle


def _supplier(db_session):
    supplier = StockSupplier(name="Fornecedor de teste", active=True)
    db_session.add(supplier)
    db_session.commit()
    db_session.refresh(supplier)
    return supplier


def _task(db_session, title, *, invoice_number=None, plate=None):
    task = Task(
        title=title,
        task_type="management",
        status="new",
        priority="normal",
        invoice_number=invoice_number,
        plate=plate,
        assignment_mode="manual",
        assignment_state="waiting_assignment",
    )
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)
    return task


def test_supplier_audit_lifecycle_reuses_process_vehicle_documents_and_history(
    authenticated_client, db_session
):
    vehicle = _vehicle(db_session)
    supplier = _supplier(db_session)
    response = authenticated_client.post(
        "/v2-clean/processes/supplier-audits",
        data={
            "title": "Manutenção possivelmente prematura",
            "supplier_id": supplier.id,
            "vehicle_id": vehicle.id,
            "problem_type": "premature_maintenance",
            "suspicion_description": "Intervalo observado inferior ao plano, por verificar.",
            "priority": "high",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    audit = db_session.scalar(select(SupplierAuditCase))
    process = db_session.get(ManagementProcess, audit.process_id)
    assert process.internal_reference.startswith("AF-")
    assert audit.assessment_grade == "suspicion"
    assert "fatura/OR" in audit.missing_elements_json
    assert db_session.scalar(
        select(SupplierAuditParty).where(
            SupplierAuditParty.audit_id == audit.id, SupplierAuditParty.supplier_id == supplier.id
        )
    )

    authenticated_client.post(
        f"/v2-clean/processes/supplier-audits/{audit.id}/verification",
        data={
            "assessment_grade": "probable",
            "status": "waiting_information",
            "verification_data": "Plano confirmado; motivo ainda desconhecido.",
            "missing_elements": "motivo técnico\nautorização",
        },
    )
    db_session.expire_all()
    assert db_session.get(SupplierAuditCase, audit.id).assessment_grade == "probable"
    assert db_session.get(ManagementProcess, process.id).status == "waiting_information"

    authenticated_client.post(
        f"/v2-clean/processes/supplier-audits/{audit.id}/parties",
        data={
            "entity_name": "Oficina de teste",
            "role": "oficina",
            "request_text": "Enviar OR",
            "response_status": "waiting",
        },
    )
    assert db_session.scalar(
        select(SupplierAuditParty).where(SupplierAuditParty.audit_id == audit.id)
    )

    document = Document(
        original_name="fatura-teste.pdf",
        file_name="fatura-teste.pdf",
        storage_path="tests/fatura-teste.pdf",
        vehicle_id=vehicle.id,
    )
    db_session.add(document)
    db_session.commit()
    authenticated_client.post(
        f"/v2-clean/processes/supplier-audits/{audit.id}/documents",
        data={"document_id": document.id, "category": "invoice"},
    )
    assert db_session.scalar(
        select(DocumentLink).where(
            DocumentLink.entity_type == "supplier_audit", DocumentLink.entity_id == str(audit.id)
        )
    )
    assert db_session.get(Document, document.id)
    assert db_session.scalars(
        select(ManagementHistory).where(ManagementHistory.process_id == process.id)
    ).all()


def test_email_is_only_versioned_draft_and_conclusion_is_human(authenticated_client, db_session):
    vehicle = _vehicle(db_session)
    supplier = _supplier(db_session)
    authenticated_client.post(
        "/v2-clean/processes/supplier-audits",
        data={
            "title": "Garantia por analisar",
            "supplier_id": supplier.id,
            "vehicle_id": vehicle.id,
            "problem_type": "warranty_refusal",
            "suspicion_description": "Recusa ainda sem fundamento documental.",
        },
    )
    audit = db_session.scalar(select(SupplierAuditCase))
    response = authenticated_client.post(
        f"/v2-clean/processes/supplier-audits/{audit.id}/drafts",
        data={
            "recipient": "fornecedor@example.test",
            "subject": "Pedido de elementos",
            "body": "Solicitamos documentação.",
            "status": "authorized",
        },
        follow_redirects=False,
    )
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
        select(SupplierAuditEmailDraft).where(SupplierAuditEmailDraft.revision_of_id == draft.id)
    )
    assert revision.version == 2

    authenticated_client.post(
        f"/v2-clean/processes/supplier-audits/{audit.id}/conclusion",
        data={
            "conclusion": "inconclusive",
            "cause": "Documentos em falta",
            "final_result": "Sem reclamação nesta fase",
        },
    )
    db_session.expire_all()
    audit = db_session.get(SupplierAuditCase, audit.id)
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


def test_plate_input_links_existing_vehicle_and_rejects_unknown_plate(
    authenticated_client, db_session
):
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
    assert "Matrícula indicada <strong>ZZ-00-ZZ</strong>" in detail.text

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
    assert response.text.count('class="supplier-audit-action"') >= 4
    assert "openAuditPhaseFromHash" in response.text


def test_supplier_is_required_and_vehicle_is_optional(authenticated_client, db_session):
    supplier = _supplier(db_session)
    response = authenticated_client.post(
        "/v2-clean/processes/supplier-audits",
        data={
            "title": "Erro de faturação",
            "supplier_id": supplier.id,
            "problem_type": "billing_error",
            "suspicion_description": "Valor por confirmar.",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    audit = db_session.scalar(select(SupplierAuditCase))
    assert audit.vehicle_id is None
    assert db_session.scalar(
        select(SupplierAuditParty).where(
            SupplierAuditParty.audit_id == audit.id, SupplierAuditParty.supplier_id == supplier.id
        )
    )
    listing = authenticated_client.get(
        f"/v2-clean/processes/supplier-audits?supplier_id={supplier.id}"
    )
    assert listing.status_code == 200
    assert "Erro de faturação" in listing.text


def test_unknown_literal_plate_can_be_kept_and_vehicle_linked_later(
    authenticated_client, db_session
):
    vehicle = _vehicle(db_session)
    response = authenticated_client.post(
        "/v2-clean/processes/supplier-audits",
        data={
            "title": "Matrícula divergente na fatura",
            "problem_type": "invoice_plate_mismatch",
            "plate": "AA-99-AA",
            "plate_unmatched": "true",
            "document_reference": "DOC-123",
            "suspicion_description": "Matrícula do documento por confirmar.",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    audit = db_session.scalar(select(SupplierAuditCase))
    process = db_session.get(ManagementProcess, audit.process_id)
    assert audit.vehicle_id is None and audit.plate_unmatched is True
    assert process.plate == "AA-99-AA" and process.document_reference == "DOC-123"
    detail = authenticated_client.get(f"/v2-clean/processes/supplier-audits/{audit.id}")
    assert "AA-99-AA" in detail.text and "Por identificar" in detail.text

    linked = authenticated_client.post(
        f"/v2-clean/processes/supplier-audits/{audit.id}/vehicle",
        data={"plate": vehicle.plate},
        follow_redirects=False,
    )
    assert linked.status_code == 303
    db_session.expire_all()
    assert db_session.get(SupplierAuditCase, audit.id).vehicle_id == vehicle.id
    assert db_session.get(ManagementProcess, process.id).plate == "AA-99-AA"
    assert db_session.scalar(
        select(ManagementHistory).where(
            ManagementHistory.process_id == process.id,
            ManagementHistory.action == "supplier_audit_vehicle_linked",
        )
    )


def test_historical_vehicle_is_searchable_and_cannot_be_marked_missing(
    authenticated_client, db_session
):
    vehicle = _vehicle(db_session)
    vehicle.active = False
    db_session.commit()
    page = authenticated_client.get("/v2-clean/processes/supplier-audits")
    assert f'<option value="{vehicle.plate}">' in page.text
    payload = {
        "title": "Documento por verificar",
        "plate": vehicle.plate,
        "problem_type": "invoice_plate_mismatch",
        "suspicion_description": "Conferir a identificação.",
    }
    blocked = authenticated_client.post(
        "/v2-clean/processes/supplier-audits",
        data={**payload, "plate_unmatched": "true"},
        follow_redirects=False,
    )
    assert blocked.headers["location"].endswith("?error=plate_exists")
    assert db_session.query(SupplierAuditCase).count() == 0
    created = authenticated_client.post(
        "/v2-clean/processes/supplier-audits", data=payload, follow_redirects=False
    )
    assert created.status_code == 303
    assert db_session.scalar(select(SupplierAuditCase)).vehicle_id == vehicle.id


def test_multiple_suppliers_have_independent_evidence_response_and_conclusion(
    authenticated_client, db_session
):
    first = _supplier(db_session)
    second = StockSupplier(name="Segundo fornecedor", active=True)
    db_session.add(second)
    db_session.commit()
    authenticated_client.post(
        "/v2-clean/processes/supplier-audits",
        data={
            "title": "Requisição divergente",
            "supplier_id": first.id,
            "problem_type": "document_request_divergence",
            "suspicion_description": "Comparar documento e pedido.",
        },
    )
    audit = db_session.scalar(select(SupplierAuditCase))
    authenticated_client.post(
        f"/v2-clean/processes/supplier-audits/{audit.id}/parties",
        data={
            "supplier_id": second.id,
            "role": "oficina",
            "response_status": "waiting",
        },
    )
    parties = list(db_session.scalars(select(SupplierAuditParty).order_by(SupplierAuditParty.id)))
    assert len(parties) == 2
    authenticated_client.post(
        f"/v2-clean/processes/supplier-audits/{audit.id}/parties/{parties[1].id}",
        data={
            "role": "oficina",
            "response_status": "answered",
            "position_summary": "Confirmou intervenção",
            "evidence_notes": "OR recebida",
            "conclusion": "Sem responsabilidade comprovada",
        },
    )
    db_session.expire_all()
    assert db_session.get(SupplierAuditParty, parties[0].id).conclusion is None
    assert db_session.get(SupplierAuditParty, parties[1].id).evidence_notes == "OR recebida"
    listing = authenticated_client.get("/v2-clean/processes/supplier-audits")
    assert listing.text.count(f'href="/v2-clean/processes/supplier-audits/{audit.id}"') == 1
    filtered = authenticated_client.get(
        f"/v2-clean/processes/supplier-audits?supplier_id={second.id}"
    )
    assert "Requisição divergente" in filtered.text


def test_repeated_tasks_for_same_document_reuse_one_audit_and_remain_open(
    authenticated_client, db_session
):
    first = _task(db_session, "Verificar fatura", invoice_number="020_18654", plate="AA-99-AA")
    second = _task(
        db_session, "Confirmar a mesma fatura", invoice_number="020_18654", plate="AA-99-AA"
    )
    data = {
        "title": "Fatura a verificar",
        "problem_type": "invoice_plate_mismatch",
        "plate": "AA-99-AA",
        "plate_unmatched": "true",
        "document_reference": "020_18654",
        "suspicion_description": "Dados por confirmar.",
    }
    created = authenticated_client.post(
        "/v2-clean/processes/supplier-audits",
        data={**data, "task_id": first.id},
        follow_redirects=False,
    )
    audit = db_session.scalar(select(SupplierAuditCase))
    assert created.headers["location"].endswith(f"/{audit.id}")
    repeated = authenticated_client.post(
        "/v2-clean/processes/supplier-audits",
        data={**data, "task_id": second.id},
        follow_redirects=False,
    )
    assert repeated.headers["location"].endswith(f"/{audit.id}#registration")
    assert db_session.query(SupplierAuditCase).count() == 1
    associations = list(
        db_session.scalars(
            select(ManagementProcessAssociation).where(
                ManagementProcessAssociation.process_id == audit.process_id,
                ManagementProcessAssociation.entity_type == "task",
            )
        )
    )
    assert {item.entity_id for item in associations} == {first.id, second.id}
    assert db_session.get(Task, first.id).status == "new"
    assert db_session.get(Task, second.id).status == "new"
    detail = authenticated_client.get(f"/v2-clean/tasks/{second.id}/detail")
    assert f"/v2-clean/processes/supplier-audits/{audit.id}" in detail.text
    audit_page = authenticated_client.get(f"/v2-clean/processes/supplier-audits/{audit.id}")
    assert f"CF-{first.id:05d}" in audit_page.text and f"CF-{second.id:05d}" in audit_page.text
    assert db_session.scalar(
        select(ManagementHistory).where(
            ManagementHistory.process_id == audit.process_id,
            ManagementHistory.action == "supplier_audit_task_linked",
        )
    )


def test_source_document_deduplicates_tasks_and_unauthenticated_cannot_link(
    client, authenticated_client, db_session
):
    first = _task(db_session, "Primeira tarefa")
    second = _task(db_session, "Segunda tarefa")
    document = Document(
        original_name="test-invoice.pdf",
        file_name="test-invoice.pdf",
        storage_path="tests/test-invoice.pdf",
        task_id=first.id,
    )
    db_session.add(document)
    db_session.commit()
    db_session.add(TaskDocument(task_id=second.id, document_id=document.id))
    db_session.commit()
    data = {
        "title": "Documento divergente",
        "problem_type": "document_request_divergence",
        "suspicion_description": "Dados ainda não confirmados.",
    }
    authenticated_client.post(
        "/v2-clean/processes/supplier-audits", data={**data, "task_id": first.id}
    )
    audit = db_session.scalar(select(SupplierAuditCase))
    authenticated_client.post(
        "/v2-clean/processes/supplier-audits", data={**data, "task_id": second.id}
    )
    assert db_session.query(SupplierAuditCase).count() == 1
    assert (
        db_session.query(DocumentLink)
        .filter_by(entity_type="supplier_audit", entity_id=str(audit.id))
        .count()
        == 1
    )
    client.cookies.clear()
    denied = client.post(
        f"/v2-clean/processes/supplier-audits/{audit.id}/tasks",
        data={"task_id": 999},
        follow_redirects=False,
    )
    assert denied.status_code == 303
    assert (
        db_session.query(ManagementProcessAssociation)
        .filter_by(process_id=audit.process_id, entity_type="task")
        .count()
        == 2
    )


def test_duplicate_files_with_same_hash_reuse_audit(authenticated_client, db_session):
    first = _task(db_session, "Analisar primeira cópia")
    second = _task(db_session, "Analisar segunda cópia")
    db_session.add_all(
        [
            Document(
                original_name="invoice-1.pdf",
                file_name="invoice-1.pdf",
                storage_path="tests/invoice-1.pdf",
                task_id=first.id,
                file_hash="same-test-hash",
            ),
            Document(
                original_name="invoice-2.pdf",
                file_name="invoice-2.pdf",
                storage_path="tests/invoice-2.pdf",
                task_id=second.id,
                file_hash="same-test-hash",
            ),
        ]
    )
    db_session.commit()
    data = {
        "title": "Documento a verificar",
        "problem_type": "document_request_divergence",
        "suspicion_description": "Confrontar as cópias.",
    }
    authenticated_client.post(
        "/v2-clean/processes/supplier-audits", data={**data, "task_id": first.id}
    )
    authenticated_client.post(
        "/v2-clean/processes/supplier-audits", data={**data, "task_id": second.id}
    )
    assert db_session.query(SupplierAuditCase).count() == 1


def test_task_closure_requires_link_and_reason_and_keeps_both_histories(
    authenticated_client, db_session
):
    linked_task = _task(db_session, "Analisar documento")
    other_task = _task(db_session, "Outra tarefa")
    authenticated_client.post(
        "/v2-clean/processes/supplier-audits",
        data={
            "title": "Documento a verificar",
            "task_id": linked_task.id,
            "problem_type": "document_request_divergence",
            "suspicion_description": "Conferir documentos.",
        },
    )
    audit = db_session.scalar(select(SupplierAuditCase))
    base = f"/v2-clean/processes/supplier-audits/{audit.id}/tasks"
    unlinked = authenticated_client.post(
        f"{base}/{other_task.id}/close",
        data={"reason": "Tarefa resolvida pelo processo."},
        follow_redirects=False,
    )
    assert unlinked.status_code == 303
    too_short = authenticated_client.post(
        f"{base}/{linked_task.id}/close", data={"reason": ""}, follow_redirects=False
    )
    assert too_short.status_code == 303
    assert db_session.get(Task, linked_task.id).status == "new"
    closed = authenticated_client.post(
        f"{base}/{linked_task.id}/close",
        data={"reason": "Documento associado e análise prossegue na auditoria."},
        follow_redirects=False,
    )
    assert closed.status_code == 303
    db_session.expire_all()
    assert db_session.get(Task, linked_task.id).status == "closed"
    assert db_session.get(Task, other_task.id).status == "new"
    comment = db_session.scalar(select(TaskComment).where(TaskComment.task_id == linked_task.id))
    assert "Documento associado" in comment.comment
    assert db_session.scalar(
        select(TaskHistory).where(
            TaskHistory.task_id == linked_task.id,
            TaskHistory.field_name == "supplier_audit_closure_reason",
        )
    )
    assert db_session.scalar(
        select(ManagementHistory).where(
            ManagementHistory.process_id == audit.process_id,
            ManagementHistory.action == "supplier_audit_task_closed",
        )
    )
