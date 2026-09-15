from datetime import date, datetime, UTC
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.models.admin import User
from app.models.documents import Document, DocumentLink
from app.models.management_center import (
    ManagementHistory,
    ManagementProcess,
    ManagementProcessAssociation,
    ManagementProcessType,
    SupplierAuditCase,
    SupplierAuditEmailDraft,
    SupplierAuditParty,
)
from app.models.vehicles import Vehicle
from app.models.stock import StockSupplier
from app.services.authorization import get_user_permission_codes
from app.web.router import templates

supplier_audit_router = APIRouter(include_in_schema=False)

TYPE_CODE = "supplier_audit"
PROBLEM_MODELS = {
    "premature_maintenance": ("Manutenção prematura", ["plano", "quilometragem anterior", "quilometragem atual", "data anterior", "motivo técnico", "autorização", "fatura/OR"]),
    "delayed_repair": ("Reparação demorada", ["data de entrada", "diagnóstico", "aprovação", "peças", "data de conclusão", "imobilização"]),
    "brake_frequency": ("Frequência de calços/discos", ["eixo", "datas", "quilometragens", "medições", "oficinas", "peças e valores"]),
    "ecu_bsi_divergence": ("Divergência manutenção real / ECU-BSI", ["histórico real", "leitura ECU/BSI", "reset", "datas", "quilometragens", "documentos"]),
    "warranty_refusal": ("Garantia recusada", ["condições da garantia", "avaria", "diagnóstico", "fundamento da recusa", "manutenção exigida", "documentos"]),
}
STATUSES = ("analysis", "waiting_information", "ready_decision", "claiming", "resolved", "closed")
GRADES = ("suspicion", "probable", "confirmed", "inconclusive", "unfounded")
CONCLUSIONS = ("substantiated", "partially_substantiated", "unfounded", "inconclusive")
DRAFT_STATUSES = ("preparing", "ready_review", "waiting_authorization", "authorized", "sent", "answered")
LABELS = {
    "analysis": "Em análise", "waiting_information": "A aguardar informação", "ready_decision": "Pronto para decisão", "claiming": "Em reclamação", "resolved": "Resolvido", "closed": "Fechado",
    "suspicion": "Desconfiança", "probable": "Provável", "confirmed": "Confirmado", "inconclusive": "Inconclusivo", "unfounded": "Sem fundamento",
    "substantiated": "Fundamentado", "partially_substantiated": "Parcialmente fundamentado",
    "preparing": "Em preparação", "ready_review": "Pronta para revisão", "waiting_authorization": "A aguardar autorização", "authorized": "Autorizada", "sent": "Enviada (registo manual)", "answered": "Respondida",
    "not_requested": "Não pedido", "waiting": "A aguardar",
}


def _user(request: Request, db):
    user_id = request.session.get("user_id")
    return db.get(User, int(user_id)) if user_id else None


def _can(request: Request, db, write=False):
    user = _user(request, db)
    permissions = get_user_permission_codes(db, user) if user else set()
    accepted = {"management_center.write", "tasks.management.create", "tasks.management.update"} if write else {"management_center.read", "management_center.write", "tasks.management.read", "tasks.management.update"}
    return user, bool(permissions & accepted)


def _type(db):
    process_type = db.scalar(select(ManagementProcessType).where(ManagementProcessType.code == TYPE_CODE))
    if not process_type:
        process_type = ManagementProcessType(code=TYPE_CODE, name="Auditoria a fornecedores", description="Verificação de suspeitas sem atribuição automática de responsabilidade.", active=True)
        db.add(process_type)
        db.flush()
    return process_type


def _audit(db, audit_id):
    return db.get(SupplierAuditCase, audit_id)


def _history(db, audit, user, action, detail):
    db.add(ManagementHistory(process_id=audit.process_id, user_id=user.id if user else None, action=action, entity_type="supplier_audit", entity_id=str(audit.id), detail=detail))


@supplier_audit_router.get("/v2-clean/processes/supplier-audits", response_class=HTMLResponse)
def supplier_audit_list(request: Request, vehicle_id: int | None = None):
    with SessionLocal() as db:
        user, allowed = _can(request, db)
        if not allowed:
            return RedirectResponse("/v2-clean?error=forbidden", status_code=303)
        rows = list(db.execute(select(SupplierAuditCase, ManagementProcess, Vehicle).join(ManagementProcess, ManagementProcess.id == SupplierAuditCase.process_id).outerjoin(Vehicle, Vehicle.id == SupplierAuditCase.vehicle_id).order_by(SupplierAuditCase.id.desc())))
        vehicle = db.get(Vehicle, vehicle_id) if vehicle_id else None
        vehicles = list(db.scalars(select(Vehicle).where(Vehicle.active.is_(True)).order_by(Vehicle.plate).limit(1000)))
        return templates.TemplateResponse(request, "supplier_audit_list.html", {"rows": rows, "vehicle": vehicle, "vehicles": vehicles, "problem_models": PROBLEM_MODELS, "labels": LABELS, "can_write": _can(request, db, True)[1]})


@supplier_audit_router.post("/v2-clean/processes/supplier-audits")
def supplier_audit_create(request: Request, title: str = Form(...), vehicle_id: int = Form(...), problem_type: str = Form(...), suspicion_description: str = Form(...), priority: str = Form("normal"), detected_on: str = Form(""), immediate_risk: str = Form(""), potential_value: str = Form("")):
    with SessionLocal() as db:
        user, allowed = _can(request, db, True)
        vehicle = db.get(Vehicle, vehicle_id)
        if not allowed or not vehicle or problem_type not in PROBLEM_MODELS or not title.strip() or not suspicion_description.strip():
            return RedirectResponse("/v2-clean/processes/supplier-audits?error=invalid", status_code=303)
        process_type = _type(db)
        year = date.today().year
        sequence = (db.scalar(select(func.count(ManagementProcess.id)).where(ManagementProcess.internal_reference.like(f"AF-{year}-%"))) or 0) + 1
        reference = f"AF-{year}-{sequence:04d}"
        process = ManagementProcess(process_type_id=process_type.id, internal_reference=reference, title=title.strip()[:240], status="analysis", phase="registration", priority=priority if priority in {"low", "normal", "high", "urgent", "critical"} else "normal", plate=vehicle.plate, opened_on=date.today())
        db.add(process); db.flush()
        try: value = Decimal(potential_value.replace(",", ".")) if potential_value.strip() else None
        except InvalidOperation: value = None
        audit = SupplierAuditCase(process_id=process.id, vehicle_id=vehicle.id, problem_type=problem_type, suspicion_description=suspicion_description.strip(), detected_on=date.fromisoformat(detected_on) if detected_on else None, immediate_risk=immediate_risk.strip() or None, potential_value=value, owner_id=user.id, verification_data_json={}, missing_elements_json=PROBLEM_MODELS[problem_type][1])
        db.add(audit); db.flush()
        db.add(ManagementProcessAssociation(process_id=process.id, entity_type="vehicle", entity_id=vehicle.id, association_role="subject", created_by_id=user.id))
        _history(db, audit, user, "supplier_audit_created", "Suspeita registada; não foi atribuída responsabilidade.")
        db.commit()
        return RedirectResponse(f"/v2-clean/processes/supplier-audits/{audit.id}", status_code=303)


@supplier_audit_router.get("/v2-clean/processes/supplier-audits/{audit_id}", response_class=HTMLResponse)
def supplier_audit_detail(request: Request, audit_id: int):
    with SessionLocal() as db:
        user, allowed = _can(request, db)
        audit = _audit(db, audit_id)
        if not allowed or not audit: return RedirectResponse("/v2-clean?error=forbidden", status_code=303)
        process = db.get(ManagementProcess, audit.process_id); vehicle = db.get(Vehicle, audit.vehicle_id) if audit.vehicle_id else None
        parties = list(db.scalars(select(SupplierAuditParty).where(SupplierAuditParty.audit_id == audit.id).order_by(SupplierAuditParty.id)))
        drafts = list(db.scalars(select(SupplierAuditEmailDraft).where(SupplierAuditEmailDraft.audit_id == audit.id).order_by(SupplierAuditEmailDraft.id.desc())))
        history = list(db.scalars(select(ManagementHistory).where(ManagementHistory.process_id == process.id).order_by(ManagementHistory.changed_at.desc())))
        links = list(db.execute(select(DocumentLink, Document).join(Document, Document.id == DocumentLink.document_id).where(DocumentLink.entity_type == "supplier_audit", DocumentLink.entity_id == str(audit.id))))
        docs = list(db.scalars(select(Document).where(Document.vehicle_id == audit.vehicle_id).order_by(Document.id.desc()).limit(50))) if audit.vehicle_id else []
        suppliers = list(db.scalars(select(StockSupplier).where(StockSupplier.active.is_(True)).order_by(StockSupplier.name)))
        return templates.TemplateResponse(request, "supplier_audit_detail.html", {"audit": audit, "process": process, "vehicle": vehicle, "parties": parties, "drafts": drafts, "history": history, "links": links, "documents": docs, "suppliers": suppliers, "labels": LABELS, "model": PROBLEM_MODELS[audit.problem_type], "can_write": _can(request, db, True)[1], "statuses": STATUSES, "grades": GRADES, "conclusions": CONCLUSIONS, "draft_statuses": DRAFT_STATUSES})


@supplier_audit_router.post("/v2-clean/processes/supplier-audits/{audit_id}/verification")
def supplier_audit_verification(request: Request, audit_id: int, assessment_grade: str = Form(...), status: str = Form(...), verification_data: str = Form(""), missing_elements: str = Form("")):
    with SessionLocal() as db:
        user, allowed = _can(request, db, True); audit = _audit(db, audit_id)
        if not allowed or not audit or assessment_grade not in GRADES or status not in STATUSES: return RedirectResponse(f"/v2-clean/processes/supplier-audits/{audit_id}?error=invalid", status_code=303)
        process = db.get(ManagementProcess, audit.process_id); audit.assessment_grade = assessment_grade; process.status = status; process.phase = "verification"
        audit.verification_data_json = {"notes": verification_data.strip()} if verification_data.strip() else {}
        audit.missing_elements_json = [x.strip() for x in missing_elements.splitlines() if x.strip()]
        _history(db, audit, user, "supplier_audit_verified", "Verificação atualizada sem conclusão automática de responsabilidade."); db.commit()
    return RedirectResponse(f"/v2-clean/processes/supplier-audits/{audit_id}#verification", status_code=303)


@supplier_audit_router.post("/v2-clean/processes/supplier-audits/{audit_id}/parties")
def supplier_audit_party(request: Request, audit_id: int, entity_name: str = Form(""), supplier_id: int | None = Form(None), role: str = Form(...), related_intervention: str = Form(""), request_text: str = Form(""), due_on: str = Form(""), response_status: str = Form("not_requested"), position_summary: str = Form("")):
    with SessionLocal() as db:
        user, allowed = _can(request, db, True); audit = _audit(db, audit_id)
        supplier = db.get(StockSupplier, supplier_id) if supplier_id else None
        party_name = supplier.name if supplier else entity_name.strip()
        if not allowed or not audit or not party_name: return RedirectResponse(f"/v2-clean/processes/supplier-audits/{audit_id}?error=invalid", status_code=303)
        party = SupplierAuditParty(audit_id=audit.id, supplier_id=supplier.id if supplier else None, entity_name=party_name, role=role.strip(), related_intervention=related_intervention.strip() or None, request_text=request_text.strip() or None, due_on=date.fromisoformat(due_on) if due_on else None, response_status=response_status, position_summary=position_summary.strip() or None)
        db.add(party); db.flush(); _history(db, audit, user, "supplier_audit_party_added", f"Interveniente associado: {party.entity_name}."); db.commit()
    return RedirectResponse(f"/v2-clean/processes/supplier-audits/{audit_id}#contacts", status_code=303)


@supplier_audit_router.post("/v2-clean/processes/supplier-audits/{audit_id}/documents")
def supplier_audit_document(request: Request, audit_id: int, document_id: int = Form(...), category: str = Form("evidence")):
    with SessionLocal() as db:
        user, allowed = _can(request, db, True); audit = _audit(db, audit_id); document = db.get(Document, document_id)
        same_vehicle = audit and document and (
            document.vehicle_id == audit.vehicle_id
            or (document.vehicle_id is None and document.plate and document.plate == db.get(ManagementProcess, audit.process_id).plate)
        )
        if not allowed or not audit or not document or not same_vehicle: return RedirectResponse(f"/v2-clean/processes/supplier-audits/{audit_id}?error=invalid", status_code=303)
        existing = db.scalar(select(DocumentLink).where(DocumentLink.document_id == document.id, DocumentLink.entity_type == "supplier_audit", DocumentLink.entity_id == str(audit.id)))
        if not existing: db.add(DocumentLink(document_id=document.id, entity_type="supplier_audit", entity_id=str(audit.id), category=category[:120])); _history(db, audit, user, "supplier_audit_document_linked", f"Documento {document.id} associado sem duplicar ficheiro.")
        db.commit()
    return RedirectResponse(f"/v2-clean/processes/supplier-audits/{audit_id}#documents", status_code=303)


@supplier_audit_router.post("/v2-clean/processes/supplier-audits/{audit_id}/drafts")
def supplier_audit_draft(request: Request, audit_id: int, revision_of_id: int | None = Form(None), party_id: int | None = Form(None), recipient: str = Form(""), subject: str = Form(...), body: str = Form(...), concrete_request: str = Form(""), due_on: str = Form(""), references: str = Form(""), status: str = Form("preparing")):
    with SessionLocal() as db:
        user, allowed = _can(request, db, True); audit = _audit(db, audit_id)
        previous = db.get(SupplierAuditEmailDraft, revision_of_id) if revision_of_id else None
        party = db.get(SupplierAuditParty, party_id) if party_id else None
        if not allowed or not audit or status not in DRAFT_STATUSES or (previous and previous.audit_id != audit.id) or (party and party.audit_id != audit.id): return RedirectResponse(f"/v2-clean/processes/supplier-audits/{audit_id}?error=invalid", status_code=303)
        draft = SupplierAuditEmailDraft(audit_id=audit.id, revision_of_id=previous.id if previous else None, version=(previous.version + 1) if previous else 1, party_id=party_id or (previous.party_id if previous else None), recipient=recipient.strip() or None, subject=subject.strip(), body=body.strip(), concrete_request=concrete_request.strip() or None, due_on=date.fromisoformat(due_on) if due_on else None, references_json=[item.strip() for item in references.splitlines() if item.strip()], status=status, created_by_id=user.id)
        db.add(draft); db.flush(); _history(db, audit, user, "supplier_audit_email_draft_created", f"Rascunho v{draft.version} registado; nenhum email foi enviado."); db.commit()
    return RedirectResponse(f"/v2-clean/processes/supplier-audits/{audit_id}#contacts", status_code=303)


@supplier_audit_router.post("/v2-clean/processes/supplier-audits/{audit_id}/conclusion")
def supplier_audit_conclusion(request: Request, audit_id: int, conclusion: str = Form(...), cause: str = Form(""), probable_responsibility: str = Form(""), impact: str = Form(""), requested_outcome: str = Form(""), final_result: str = Form("")):
    with SessionLocal() as db:
        user, allowed = _can(request, db, True); audit = _audit(db, audit_id)
        if not allowed or not audit or conclusion not in CONCLUSIONS: return RedirectResponse(f"/v2-clean/processes/supplier-audits/{audit_id}?error=invalid", status_code=303)
        audit.conclusion = conclusion; audit.cause = cause.strip() or None; audit.probable_responsibility = probable_responsibility.strip() or None; audit.impact = impact.strip() or None; audit.requested_outcome = requested_outcome.strip() or None; audit.final_result = final_result.strip() or None
        process = db.get(ManagementProcess, audit.process_id); process.phase = "conclusion"; process.status = "closed"; process.closed_at = datetime.now(UTC)
        _history(db, audit, user, "supplier_audit_concluded", f"Conclusão humana registada: {conclusion}."); db.commit()
    return RedirectResponse(f"/v2-clean/processes/supplier-audits/{audit_id}#conclusion", status_code=303)
