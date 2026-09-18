from datetime import UTC, date, datetime
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
from app.models.stock import StockSupplier
from app.models.tasks import Task, TaskComment, TaskDocument, TaskHistory
from app.models.vehicles import Vehicle
from app.services.authorization import get_user_permission_codes
from app.services.task_center import user_can_view_task
from app.web.router import (
    _task_hierarchy_scope_allows,
    create_task_notifications,
    mark_task_resolved,
    record_audit,
    required_photo_blockers,
    templates,
    user_can_access_task_workspace,
    workspace_for_task_type,
)

supplier_audit_router = APIRouter(include_in_schema=False)

TYPE_CODE = "supplier_audit"
PROBLEM_MODELS = {
    "document_request_divergence": (
        "Documento / requisição divergente",
        [
            "documento recebido",
            "requisição",
            "trabalho autorizado",
            "esclarecimento dos intervenientes",
        ],
    ),
    "duplicate_teleloading": (
        "Telecarregamento possivelmente duplicado",
        ["ordens de reparação", "registos de telecarregamento", "datas", "diagnósticos", "faturas"],
    ),
    "invoice_plate_mismatch": (
        "Matrícula divergente na fatura",
        [
            "fatura",
            "matrícula indicada",
            "requisição",
            "identificação da viatura",
            "esclarecimento do fornecedor",
        ],
    ),
    "billing_error": (
        "Erro de faturação",
        ["fatura", "serviço acordado", "valor faturado", "esclarecimento do fornecedor"],
    ),
    "repair_error": (
        "Erro de reparação",
        ["ordem de reparação", "diagnóstico", "trabalho executado", "resultado observado"],
    ),
    "service_not_performed": (
        "Serviço não efetuado",
        ["serviço solicitado", "ordem de reparação", "evidência da execução", "fatura"],
    ),
    "premature_maintenance": (
        "Manutenção prematura",
        [
            "plano",
            "quilometragem anterior",
            "quilometragem atual",
            "data anterior",
            "motivo técnico",
            "autorização",
            "fatura/OR",
        ],
    ),
    "delayed_repair": (
        "Reparação demorada",
        [
            "data de entrada",
            "diagnóstico",
            "aprovação",
            "peças",
            "data de conclusão",
            "imobilização",
        ],
    ),
    "brake_frequency": (
        "Frequência de calços/discos",
        ["eixo", "datas", "quilometragens", "medições", "oficinas", "peças e valores"],
    ),
    "ecu_bsi_divergence": (
        "Divergência manutenção real / ECU-BSI",
        ["histórico real", "leitura ECU/BSI", "reset", "datas", "quilometragens", "documentos"],
    ),
    "warranty_refusal": (
        "Garantia recusada",
        [
            "condições da garantia",
            "avaria",
            "diagnóstico",
            "fundamento da recusa",
            "manutenção exigida",
            "documentos",
        ],
    ),
}
STATUSES = ("analysis", "waiting_information", "ready_decision", "claiming", "resolved", "closed")
GRADES = ("suspicion", "probable", "confirmed", "inconclusive", "unfounded")
CONCLUSIONS = ("substantiated", "partially_substantiated", "unfounded", "inconclusive")
DRAFT_STATUSES = (
    "preparing",
    "ready_review",
    "waiting_authorization",
    "authorized",
    "sent",
    "answered",
)
LABELS = {
    "analysis": "Em análise",
    "waiting_information": "A aguardar informação",
    "ready_decision": "Pronto para decisão",
    "claiming": "Em reclamação",
    "resolved": "Resolvido",
    "closed": "Fechado",
    "suspicion": "Desconfiança",
    "probable": "Provável",
    "confirmed": "Confirmado",
    "inconclusive": "Inconclusivo",
    "unfounded": "Sem fundamento",
    "substantiated": "Fundamentado",
    "partially_substantiated": "Parcialmente fundamentado",
    "preparing": "Em preparação",
    "ready_review": "Pronta para revisão",
    "waiting_authorization": "A aguardar autorização",
    "authorized": "Autorizada",
    "sent": "Enviada (registo manual)",
    "answered": "Respondida",
    "not_requested": "Não pedido",
    "waiting": "A aguardar",
}


def _user(request: Request, db):
    user_id = request.session.get("user_id")
    return db.get(User, int(user_id)) if user_id else None


def _can(request: Request, db, write=False):
    user = _user(request, db)
    permissions = get_user_permission_codes(db, user) if user else set()
    accepted = (
        {"management_center.write", "tasks.management.create", "tasks.management.update"}
        if write
        else {
            "management_center.read",
            "management_center.write",
            "tasks.management.read",
            "tasks.management.update",
        }
    )
    return user, bool(permissions & accepted)


def _type(db):
    process_type = db.scalar(
        select(ManagementProcessType).where(ManagementProcessType.code == TYPE_CODE)
    )
    if not process_type:
        process_type = ManagementProcessType(
            code=TYPE_CODE,
            name="Auditoria a fornecedores",
            description="Verificação de suspeitas sem atribuição automática de responsabilidade.",
            active=True,
        )
        db.add(process_type)
        db.flush()
    return process_type


def _audit(db, audit_id):
    return db.get(SupplierAuditCase, audit_id)


def _history(db, audit, user, action, detail):
    db.add(
        ManagementHistory(
            process_id=audit.process_id,
            user_id=user.id if user else None,
            action=action,
            entity_type="supplier_audit",
            entity_id=str(audit.id),
            detail=detail,
        )
    )


def _task_visible(db, user, task):
    return bool(
        task
        and user
        and user_can_access_task_workspace(db, user, workspace_for_task_type(task.task_type))
        and user_can_view_task(db, user_id=user.id, task=task)
    )


def _task_document_ids(db, task_id):
    direct = db.scalars(select(Document.id).where(Document.task_id == task_id)).all()
    linked = db.scalars(
        select(TaskDocument.document_id).where(TaskDocument.task_id == task_id)
    ).all()
    return set(direct) | set(linked)


def _link_task(db, audit, task, user):
    existing = db.scalar(
        select(ManagementProcessAssociation).where(
            ManagementProcessAssociation.process_id == audit.process_id,
            ManagementProcessAssociation.entity_type == "task",
            ManagementProcessAssociation.entity_id == task.id,
            ManagementProcessAssociation.active.is_(True),
        )
    )
    if existing:
        return False
    db.add(
        ManagementProcessAssociation(
            process_id=audit.process_id,
            entity_type="task",
            entity_id=task.id,
            association_role="source",
            created_by_id=user.id,
        )
    )
    for document_id in _task_document_ids(db, task.id):
        linked = db.scalar(
            select(DocumentLink.id).where(
                DocumentLink.document_id == document_id,
                DocumentLink.entity_type == "supplier_audit",
                DocumentLink.entity_id == str(audit.id),
            )
        )
        if not linked:
            db.add(
                DocumentLink(
                    document_id=document_id,
                    entity_type="supplier_audit",
                    entity_id=str(audit.id),
                    category="source_task",
                )
            )
    _history(
        db,
        audit,
        user,
        "supplier_audit_task_linked",
        f"Tarefa CF-{task.id:05d} associada; permanece aberta até fecho fundamentado.",
    )
    return True


def _matching_audits(db, task):
    audit_ids = set()
    audit_ids.update(
        db.scalars(
            select(SupplierAuditCase.id)
            .join(
                ManagementProcessAssociation,
                ManagementProcessAssociation.process_id == SupplierAuditCase.process_id,
            )
            .where(
                ManagementProcessAssociation.entity_type == "task",
                ManagementProcessAssociation.entity_id == task.id,
                ManagementProcessAssociation.active.is_(True),
            )
        )
    )
    document_ids = _task_document_ids(db, task.id)
    if document_ids:
        hashes = set(
            db.scalars(
                select(Document.file_hash).where(
                    Document.id.in_(document_ids), Document.file_hash.is_not(None)
                )
            )
        )
        if hashes:
            document_ids.update(
                db.scalars(select(Document.id).where(Document.file_hash.in_(hashes)))
            )
        linked_ids = db.scalars(
            select(DocumentLink.entity_id).where(
                DocumentLink.entity_type == "supplier_audit",
                DocumentLink.document_id.in_(document_ids),
            )
        )
        audit_ids.update(int(value) for value in linked_ids if value.isdigit())
    return [db.get(SupplierAuditCase, audit_id) for audit_id in sorted(audit_ids)]


def _reference_candidates(db, reference):
    """Show an advisory match; invoice numbers alone do not prove document identity."""
    if not reference.strip():
        return []
    return list(
        db.scalars(
            select(SupplierAuditCase)
            .join(ManagementProcess, ManagementProcess.id == SupplierAuditCase.process_id)
            .where(func.upper(ManagementProcess.document_reference) == reference.strip().upper())
        )
    )


@supplier_audit_router.get("/v2-clean/processes/supplier-audits", response_class=HTMLResponse)
def supplier_audit_list(
    request: Request,
    vehicle_id: int | None = None,
    supplier_id: int | None = None,
    task_id: int | None = None,
    error: str | None = None,
):
    with SessionLocal() as db:
        user, allowed = _can(request, db)
        if not allowed:
            return RedirectResponse("/v2-clean?error=forbidden", status_code=303)
        task = db.get(Task, task_id) if task_id else None
        if task_id and not _task_visible(db, user, task):
            return RedirectResponse("/v2-clean?error=forbidden", status_code=303)
        query = (
            select(SupplierAuditCase, ManagementProcess, Vehicle)
            .join(ManagementProcess, ManagementProcess.id == SupplierAuditCase.process_id)
            .outerjoin(Vehicle, Vehicle.id == SupplierAuditCase.vehicle_id)
        )
        if supplier_id:
            query = query.where(
                SupplierAuditCase.id.in_(
                    select(SupplierAuditParty.audit_id).where(
                        SupplierAuditParty.supplier_id == supplier_id
                    )
                )
            )
        rows = list(db.execute(query.order_by(SupplierAuditCase.id.desc())))
        party_names = {}
        for party in db.scalars(select(SupplierAuditParty).order_by(SupplierAuditParty.id)):
            party_names.setdefault(party.audit_id, []).append(party.entity_name)
        vehicle = db.get(Vehicle, vehicle_id) if vehicle_id else None
        vehicles = list(db.scalars(select(Vehicle).order_by(Vehicle.plate)))
        suppliers = list(
            db.scalars(
                select(StockSupplier)
                .where(StockSupplier.active.is_(True))
                .order_by(StockSupplier.name)
            )
        )
        matching = []
        if task:
            candidates = _matching_audits(db, task) + _reference_candidates(
                db, task.invoice_number or ""
            )
            matching = list({candidate.id: candidate for candidate in candidates}.values())
        return templates.TemplateResponse(
            request,
            "supplier_audit_list.html",
            {
                "rows": rows,
                "vehicle": vehicle,
                "vehicles": vehicles,
                "suppliers": suppliers,
                "supplier_id": supplier_id,
                "task": task,
                "matching": matching,
                "party_names": party_names,
                "problem_models": PROBLEM_MODELS,
                "labels": LABELS,
                "error": error,
                "can_write": _can(request, db, True)[1],
            },
        )


@supplier_audit_router.post("/v2-clean/processes/supplier-audits")
def supplier_audit_create(
    request: Request,
    title: str = Form(...),
    supplier_id: int | None = Form(None),
    vehicle_id: int | None = Form(None),
    task_id: int | None = Form(None),
    plate: str = Form(""),
    plate_unmatched: bool = Form(False),
    document_reference: str = Form(""),
    problem_type: str = Form(...),
    suspicion_description: str = Form(...),
    priority: str = Form("normal"),
    detected_on: str = Form(""),
    immediate_risk: str = Form(""),
    potential_value: str = Form(""),
):
    with SessionLocal() as db:
        user, allowed = _can(request, db, True)
        task = db.get(Task, task_id) if task_id else None
        supplier = db.get(StockSupplier, supplier_id) if supplier_id else None
        if (
            not allowed
            or (task_id and not _task_visible(db, user, task))
            or (supplier_id and (not supplier or not supplier.active))
            or problem_type not in PROBLEM_MODELS
            or not title.strip()
            or not suspicion_description.strip()
        ):
            return RedirectResponse(
                "/v2-clean/processes/supplier-audits?error=invalid", status_code=303
            )

        reference_text = document_reference.strip()[:160] or (
            task.invoice_number.strip()[:160] if task and task.invoice_number else ""
        )
        if task:
            matches = _matching_audits(db, task)
            if len(matches) > 1:
                return RedirectResponse(
                    "/v2-clean/processes/supplier-audits?error=ambiguous_duplicate", status_code=303
                )
            if matches:
                audit = matches[0]
                _link_task(db, audit, task, user)
                if supplier and not db.scalar(
                    select(SupplierAuditParty.id).where(
                        SupplierAuditParty.audit_id == audit.id,
                        SupplierAuditParty.supplier_id == supplier.id,
                    )
                ):
                    db.add(
                        SupplierAuditParty(
                            audit_id=audit.id,
                            supplier_id=supplier.id,
                            entity_name=supplier.name,
                            role="supplier",
                        )
                    )
                    _history(
                        db,
                        audit,
                        user,
                        "supplier_audit_party_added",
                        f"Fornecedor {supplier.name} associado à tarefa CF-{task.id:05d}; "
                        "responsabilidade por apurar.",
                    )
                db.commit()
                return RedirectResponse(
                    f"/v2-clean/processes/supplier-audits/{audit.id}#registration", status_code=303
                )

        vehicle = db.get(Vehicle, vehicle_id) if vehicle_id else None
        if vehicle_id and not vehicle:
            return RedirectResponse(
                "/v2-clean/processes/supplier-audits?error=invalid", status_code=303
            )
        plate_text = plate.strip().upper()[:40] or (vehicle.plate if vehicle else "")
        plate_key = plate_text.replace("-", "").replace(" ", "")
        plate_vehicle = (
            db.scalar(
                select(Vehicle).where(
                    func.upper(func.replace(func.replace(Vehicle.plate, "-", ""), " ", ""))
                    == plate_key
                )
            )
            if plate_key
            else None
        )
        if plate_unmatched and plate_vehicle:
            return RedirectResponse(
                "/v2-clean/processes/supplier-audits?error=plate_exists", status_code=303
            )
        if plate_key and not plate_unmatched and not plate_vehicle:
            return RedirectResponse(
                "/v2-clean/processes/supplier-audits?error=plate_not_found", status_code=303
            )
        if vehicle and plate_vehicle and vehicle.id != plate_vehicle.id:
            return RedirectResponse(
                "/v2-clean/processes/supplier-audits?error=invalid", status_code=303
            )
        vehicle = plate_vehicle or vehicle

        process_type = _type(db)
        year = date.today().year
        sequence = (
            db.scalar(
                select(func.count(ManagementProcess.id)).where(
                    ManagementProcess.internal_reference.like(f"AF-{year}-%")
                )
            )
            or 0
        ) + 1
        reference = f"AF-{year}-{sequence:04d}"
        process = ManagementProcess(
            process_type_id=process_type.id,
            internal_reference=reference,
            title=title.strip()[:240],
            status="analysis",
            phase="registration",
            priority=priority
            if priority in {"low", "normal", "high", "urgent", "critical"}
            else "normal",
            plate=(vehicle.plate if vehicle else plate_text) or None,
            document_reference=reference_text or None,
            opened_on=date.today(),
        )
        db.add(process)
        db.flush()
        try:
            value = Decimal(potential_value.replace(",", ".")) if potential_value.strip() else None
        except InvalidOperation:
            value = None
        audit = SupplierAuditCase(
            process_id=process.id,
            vehicle_id=vehicle.id if vehicle else None,
            plate_unmatched=plate_unmatched,
            problem_type=problem_type,
            suspicion_description=suspicion_description.strip(),
            detected_on=date.fromisoformat(detected_on) if detected_on else None,
            immediate_risk=immediate_risk.strip() or None,
            potential_value=value,
            owner_id=user.id,
            verification_data_json={},
            missing_elements_json=PROBLEM_MODELS[problem_type][1],
        )
        db.add(audit)
        db.flush()
        if supplier:
            db.add(
                SupplierAuditParty(
                    audit_id=audit.id,
                    supplier_id=supplier.id,
                    entity_name=supplier.name,
                    role="supplier",
                    response_status="not_requested",
                )
            )
        if vehicle:
            db.add(
                ManagementProcessAssociation(
                    process_id=process.id,
                    entity_type="vehicle",
                    entity_id=vehicle.id,
                    association_role="subject",
                    created_by_id=user.id,
                )
            )
        if task:
            _link_task(db, audit, task, user)
        _history(
            db,
            audit,
            user,
            "supplier_audit_created",
            "Suspeita registada; não foi atribuída responsabilidade.",
        )
        db.commit()
        return RedirectResponse(f"/v2-clean/processes/supplier-audits/{audit.id}", status_code=303)


@supplier_audit_router.get(
    "/v2-clean/processes/supplier-audits/{audit_id}", response_class=HTMLResponse
)
def supplier_audit_detail(request: Request, audit_id: int):
    with SessionLocal() as db:
        user, allowed = _can(request, db)
        audit = _audit(db, audit_id)
        if not allowed or not audit:
            return RedirectResponse("/v2-clean?error=forbidden", status_code=303)
        process = db.get(ManagementProcess, audit.process_id)
        vehicle = db.get(Vehicle, audit.vehicle_id) if audit.vehicle_id else None
        parties = list(
            db.scalars(
                select(SupplierAuditParty)
                .where(SupplierAuditParty.audit_id == audit.id)
                .order_by(SupplierAuditParty.id)
            )
        )
        drafts = list(
            db.scalars(
                select(SupplierAuditEmailDraft)
                .where(SupplierAuditEmailDraft.audit_id == audit.id)
                .order_by(SupplierAuditEmailDraft.id.desc())
            )
        )
        history = list(
            db.scalars(
                select(ManagementHistory)
                .where(ManagementHistory.process_id == process.id)
                .order_by(ManagementHistory.changed_at.desc())
            )
        )
        links = list(
            db.execute(
                select(DocumentLink, Document)
                .join(Document, Document.id == DocumentLink.document_id)
                .where(
                    DocumentLink.entity_type == "supplier_audit",
                    DocumentLink.entity_id == str(audit.id),
                )
            )
        )
        docs = (
            list(
                db.scalars(
                    select(Document)
                    .where(Document.vehicle_id == audit.vehicle_id)
                    .order_by(Document.id.desc())
                    .limit(50)
                )
            )
            if audit.vehicle_id
            else []
        )
        task_links = [
            task
            for task in db.scalars(
                select(Task)
                .join(
                    ManagementProcessAssociation,
                    (ManagementProcessAssociation.entity_type == "task")
                    & (ManagementProcessAssociation.entity_id == Task.id),
                )
                .where(
                    ManagementProcessAssociation.process_id == process.id,
                    ManagementProcessAssociation.active.is_(True),
                )
                .order_by(Task.id)
            )
            if _task_visible(db, user, task)
        ]
        closable_task_ids = {
            task.id
            for task in task_links
            if task.status not in {"closed", "cancelled", "no_action_needed"}
            and user_can_access_task_workspace(
                db, user, workspace_for_task_type(task.task_type), action="close"
            )
            and _task_hierarchy_scope_allows(db, user.id, task, action="close")
        }
        suppliers = list(
            db.scalars(
                select(StockSupplier)
                .where(StockSupplier.active.is_(True))
                .order_by(StockSupplier.name)
            )
        )
        return templates.TemplateResponse(
            request,
            "supplier_audit_detail.html",
            {
                "audit": audit,
                "process": process,
                "vehicle": vehicle,
                "parties": parties,
                "drafts": drafts,
                "history": history,
                "links": links,
                "documents": docs,
                "task_links": task_links,
                "closable_task_ids": closable_task_ids,
                "suppliers": suppliers,
                "labels": LABELS,
                "model": PROBLEM_MODELS.get(audit.problem_type, (audit.problem_type, [])),
                "can_write": _can(request, db, True)[1],
                "statuses": STATUSES,
                "grades": GRADES,
                "conclusions": CONCLUSIONS,
                "draft_statuses": DRAFT_STATUSES,
            },
        )


@supplier_audit_router.post("/v2-clean/processes/supplier-audits/{audit_id}/tasks")
def supplier_audit_link_task(request: Request, audit_id: int, task_id: int = Form(...)):
    with SessionLocal() as db:
        user, allowed = _can(request, db, True)
        audit, task = _audit(db, audit_id), db.get(Task, task_id)
        if not allowed or not audit or not _task_visible(db, user, task):
            return RedirectResponse(
                f"/v2-clean/processes/supplier-audits/{audit_id}?error=invalid", status_code=303
            )
        matches = _matching_audits(db, task)
        if any(item.id != audit.id for item in matches):
            return RedirectResponse(
                f"/v2-clean/processes/supplier-audits/{audit_id}?error=duplicate", status_code=303
            )
        _link_task(db, audit, task, user)
        db.commit()
    return RedirectResponse(
        f"/v2-clean/processes/supplier-audits/{audit_id}#registration", status_code=303
    )


@supplier_audit_router.post("/v2-clean/processes/supplier-audits/{audit_id}/tasks/{task_id}/close")
def supplier_audit_close_task(
    request: Request, audit_id: int, task_id: int, reason: str = Form("")
):
    with SessionLocal() as db:
        user, allowed = _can(request, db, True)
        audit, task = _audit(db, audit_id), db.get(Task, task_id)
        association = (
            db.scalar(
                select(ManagementProcessAssociation).where(
                    ManagementProcessAssociation.process_id == audit.process_id,
                    ManagementProcessAssociation.entity_type == "task",
                    ManagementProcessAssociation.entity_id == task_id,
                    ManagementProcessAssociation.active.is_(True),
                )
            )
            if audit
            else None
        )
        if (
            not allowed
            or not audit
            or not association
            or not _task_visible(db, user, task)
            or not user_can_access_task_workspace(
                db, user, workspace_for_task_type(task.task_type), action="close"
            )
            or not _task_hierarchy_scope_allows(db, user.id, task, action="close")
            or task.status in {"closed", "cancelled", "no_action_needed"}
            or not reason.strip()
        ):
            return RedirectResponse(
                f"/v2-clean/processes/supplier-audits/{audit_id}?error=invalid", status_code=303
            )
        if required_photo_blockers(db, task_id=task.id):
            return RedirectResponse(
                f"/v2-clean/processes/supplier-audits/{audit_id}?error=photo_required",
                status_code=303,
            )
        process = db.get(ManagementProcess, audit.process_id)
        clean_reason = reason.strip()[:4000]
        comment = f"Fecho associado a {process.internal_reference}: {clean_reason}"
        now = datetime.now(UTC)
        prior_status = task.status
        task.status = "closed"
        task.closed_at = now
        mark_task_resolved(db, task, actor_user_id=user.id, now=now)
        db.add(TaskComment(task_id=task.id, user_id=user.id, comment=comment))
        db.add(
            TaskHistory(
                task_id=task.id,
                user_id=user.id,
                field_name="supplier_audit_closure_reason",
                old_value=None,
                new_value=comment,
            )
        )
        db.add(
            TaskHistory(
                task_id=task.id,
                user_id=user.id,
                field_name="status",
                old_value=prior_status,
                new_value="closed",
            )
        )
        _history(
            db,
            audit,
            user,
            "supplier_audit_task_closed",
            f"Tarefa CF-{task.id:05d} fechada: {clean_reason}",
        )
        record_audit(
            db,
            action="task.close",
            entity_type="task",
            entity_id=task.id,
            detail=comment,
            user_id=user.id,
        )
        create_task_notifications(
            db,
            task=task,
            event_type="task_closed",
            title=f"Tarefa fechada: {task.title}",
            actor_user_id=user.id,
        )
        db.commit()
    return RedirectResponse(
        f"/v2-clean/processes/supplier-audits/{audit_id}#registration", status_code=303
    )


@supplier_audit_router.post("/v2-clean/processes/supplier-audits/{audit_id}/vehicle")
def supplier_audit_link_vehicle(request: Request, audit_id: int, plate: str = Form(...)):
    with SessionLocal() as db:
        user, allowed = _can(request, db, True)
        audit = _audit(db, audit_id)
        plate_key = plate.strip().upper().replace("-", "").replace(" ", "")
        vehicle = (
            db.scalar(
                select(Vehicle).where(
                    func.upper(func.replace(func.replace(Vehicle.plate, "-", ""), " ", ""))
                    == plate_key
                )
            )
            if plate_key
            else None
        )
        if not allowed or not audit or not vehicle:
            return RedirectResponse(
                f"/v2-clean/processes/supplier-audits/{audit_id}?error=invalid", status_code=303
            )
        old_vehicle_id = audit.vehicle_id
        if old_vehicle_id != vehicle.id:
            if old_vehicle_id:
                previous_links = db.scalars(
                    select(ManagementProcessAssociation).where(
                        ManagementProcessAssociation.process_id == audit.process_id,
                        ManagementProcessAssociation.entity_type == "vehicle",
                        ManagementProcessAssociation.entity_id == old_vehicle_id,
                        ManagementProcessAssociation.active.is_(True),
                    )
                )
                for link in previous_links:
                    link.active = False
                    link.ended_at = datetime.now(UTC)
                    link.ended_by_id = user.id
            audit.vehicle_id = vehicle.id
            db.add(
                ManagementProcessAssociation(
                    process_id=audit.process_id,
                    entity_type="vehicle",
                    entity_id=vehicle.id,
                    association_role="identified_after_review",
                    created_by_id=user.id,
                    reason=(
                        "Matrícula literal preservada: "
                        f"{db.get(ManagementProcess, audit.process_id).plate or 'não indicada'}"
                    ),
                )
            )
            _history(
                db,
                audit,
                user,
                "supplier_audit_vehicle_linked",
                f"Ficha da viatura associada: {old_vehicle_id or 'nenhuma'} → "
                f"{vehicle.id} ({vehicle.plate}); matrícula indicada preservada.",
            )
            db.commit()
    return RedirectResponse(
        f"/v2-clean/processes/supplier-audits/{audit_id}#registration", status_code=303
    )


@supplier_audit_router.post("/v2-clean/processes/supplier-audits/{audit_id}/verification")
def supplier_audit_verification(
    request: Request,
    audit_id: int,
    assessment_grade: str = Form(...),
    status: str = Form(...),
    verification_data: str = Form(""),
    missing_elements: str = Form(""),
):
    with SessionLocal() as db:
        user, allowed = _can(request, db, True)
        audit = _audit(db, audit_id)
        if not allowed or not audit or assessment_grade not in GRADES or status not in STATUSES:
            return RedirectResponse(
                f"/v2-clean/processes/supplier-audits/{audit_id}?error=invalid", status_code=303
            )
        process = db.get(ManagementProcess, audit.process_id)
        audit.assessment_grade = assessment_grade
        process.status = status
        process.phase = "verification"
        audit.verification_data_json = (
            {"notes": verification_data.strip()} if verification_data.strip() else {}
        )
        audit.missing_elements_json = [
            x.strip() for x in missing_elements.splitlines() if x.strip()
        ]
        _history(
            db,
            audit,
            user,
            "supplier_audit_verified",
            "Verificação atualizada sem conclusão automática de responsabilidade.",
        )
        db.commit()
    return RedirectResponse(
        f"/v2-clean/processes/supplier-audits/{audit_id}#verification", status_code=303
    )


@supplier_audit_router.post("/v2-clean/processes/supplier-audits/{audit_id}/parties")
def supplier_audit_party(
    request: Request,
    audit_id: int,
    entity_name: str = Form(""),
    supplier_id: int | None = Form(None),
    role: str = Form(...),
    related_intervention: str = Form(""),
    request_text: str = Form(""),
    due_on: str = Form(""),
    response_status: str = Form("not_requested"),
    position_summary: str = Form(""),
):
    with SessionLocal() as db:
        user, allowed = _can(request, db, True)
        audit = _audit(db, audit_id)
        supplier = db.get(StockSupplier, supplier_id) if supplier_id else None
        party_name = supplier.name if supplier else entity_name.strip()
        if (
            not allowed
            or not audit
            or not party_name
            or response_status not in {"not_requested", "waiting", "answered"}
            or (
                supplier
                and db.scalar(
                    select(SupplierAuditParty.id).where(
                        SupplierAuditParty.audit_id == audit.id,
                        SupplierAuditParty.supplier_id == supplier.id,
                    )
                )
            )
        ):
            return RedirectResponse(
                f"/v2-clean/processes/supplier-audits/{audit_id}?error=invalid", status_code=303
            )
        party = SupplierAuditParty(
            audit_id=audit.id,
            supplier_id=supplier.id if supplier else None,
            entity_name=party_name,
            role=role.strip(),
            related_intervention=related_intervention.strip() or None,
            request_text=request_text.strip() or None,
            due_on=date.fromisoformat(due_on) if due_on else None,
            response_status=response_status,
            position_summary=position_summary.strip() or None,
        )
        db.add(party)
        db.flush()
        _history(
            db,
            audit,
            user,
            "supplier_audit_party_added",
            f"Interveniente associado: {party.entity_name}.",
        )
        db.commit()
    return RedirectResponse(
        f"/v2-clean/processes/supplier-audits/{audit_id}#contacts", status_code=303
    )


@supplier_audit_router.post("/v2-clean/processes/supplier-audits/{audit_id}/parties/{party_id}")
def supplier_audit_party_update(
    request: Request,
    audit_id: int,
    party_id: int,
    role: str = Form(...),
    request_text: str = Form(""),
    response_status: str = Form(...),
    position_summary: str = Form(""),
    evidence_notes: str = Form(""),
    conclusion: str = Form(""),
):
    with SessionLocal() as db:
        user, allowed = _can(request, db, True)
        audit, party = _audit(db, audit_id), db.get(SupplierAuditParty, party_id)
        if (
            not allowed
            or not audit
            or not party
            or party.audit_id != audit.id
            or response_status not in {"not_requested", "waiting", "answered"}
            or not role.strip()
        ):
            return RedirectResponse(
                f"/v2-clean/processes/supplier-audits/{audit_id}?error=invalid", status_code=303
            )
        party.role = role.strip()[:120]
        party.request_text = request_text.strip() or None
        party.response_status = response_status
        party.position_summary = position_summary.strip() or None
        party.evidence_notes = evidence_notes.strip() or None
        party.conclusion = conclusion.strip() or None
        _history(
            db,
            audit,
            user,
            "supplier_audit_party_updated",
            f"Interveniente {party.entity_name} atualizado: resposta {response_status}; "
            f"conclusão individual {'registada' if party.conclusion else 'pendente'}.",
        )
        db.commit()
    return RedirectResponse(
        f"/v2-clean/processes/supplier-audits/{audit_id}#contacts", status_code=303
    )


@supplier_audit_router.post("/v2-clean/processes/supplier-audits/{audit_id}/documents")
def supplier_audit_document(
    request: Request, audit_id: int, document_id: int = Form(...), category: str = Form("evidence")
):
    with SessionLocal() as db:
        user, allowed = _can(request, db, True)
        audit = _audit(db, audit_id)
        document = db.get(Document, document_id)
        process = db.get(ManagementProcess, audit.process_id) if audit else None
        source_task_ids = (
            set(
                db.scalars(
                    select(ManagementProcessAssociation.entity_id).where(
                        ManagementProcessAssociation.process_id == audit.process_id,
                        ManagementProcessAssociation.entity_type == "task",
                        ManagementProcessAssociation.active.is_(True),
                    )
                )
            )
            if audit
            else set()
        )
        related = (
            audit
            and document
            and (
                (audit.vehicle_id is not None and document.vehicle_id == audit.vehicle_id)
                or (
                    document.plate
                    and process.plate
                    and document.plate.upper() == process.plate.upper()
                )
                or document.task_id in source_task_ids
                or db.scalar(
                    select(TaskDocument.document_id).where(
                        TaskDocument.task_id.in_(source_task_ids),
                        TaskDocument.document_id == document.id,
                    )
                )
                is not None
            )
        )
        if not allowed or not audit or not document or not related:
            return RedirectResponse(
                f"/v2-clean/processes/supplier-audits/{audit_id}?error=invalid", status_code=303
            )
        existing = db.scalar(
            select(DocumentLink).where(
                DocumentLink.document_id == document.id,
                DocumentLink.entity_type == "supplier_audit",
                DocumentLink.entity_id == str(audit.id),
            )
        )
        if not existing:
            db.add(
                DocumentLink(
                    document_id=document.id,
                    entity_type="supplier_audit",
                    entity_id=str(audit.id),
                    category=category[:120],
                )
            )
            _history(
                db,
                audit,
                user,
                "supplier_audit_document_linked",
                f"Documento {document.id} associado sem duplicar ficheiro.",
            )
        db.commit()
    return RedirectResponse(
        f"/v2-clean/processes/supplier-audits/{audit_id}#documents", status_code=303
    )


@supplier_audit_router.post("/v2-clean/processes/supplier-audits/{audit_id}/drafts")
def supplier_audit_draft(
    request: Request,
    audit_id: int,
    revision_of_id: int | None = Form(None),
    party_id: int | None = Form(None),
    recipient: str = Form(""),
    subject: str = Form(...),
    body: str = Form(...),
    concrete_request: str = Form(""),
    due_on: str = Form(""),
    references: str = Form(""),
    status: str = Form("preparing"),
):
    with SessionLocal() as db:
        user, allowed = _can(request, db, True)
        audit = _audit(db, audit_id)
        previous = db.get(SupplierAuditEmailDraft, revision_of_id) if revision_of_id else None
        party = db.get(SupplierAuditParty, party_id) if party_id else None
        if (
            not allowed
            or not audit
            or status not in DRAFT_STATUSES
            or (previous and previous.audit_id != audit.id)
            or (party and party.audit_id != audit.id)
        ):
            return RedirectResponse(
                f"/v2-clean/processes/supplier-audits/{audit_id}?error=invalid", status_code=303
            )
        draft = SupplierAuditEmailDraft(
            audit_id=audit.id,
            revision_of_id=previous.id if previous else None,
            version=(previous.version + 1) if previous else 1,
            party_id=party_id or (previous.party_id if previous else None),
            recipient=recipient.strip() or None,
            subject=subject.strip(),
            body=body.strip(),
            concrete_request=concrete_request.strip() or None,
            due_on=date.fromisoformat(due_on) if due_on else None,
            references_json=[item.strip() for item in references.splitlines() if item.strip()],
            status=status,
            created_by_id=user.id,
        )
        db.add(draft)
        db.flush()
        _history(
            db,
            audit,
            user,
            "supplier_audit_email_draft_created",
            f"Rascunho v{draft.version} registado; nenhum email foi enviado.",
        )
        db.commit()
    return RedirectResponse(
        f"/v2-clean/processes/supplier-audits/{audit_id}#contacts", status_code=303
    )


@supplier_audit_router.post("/v2-clean/processes/supplier-audits/{audit_id}/conclusion")
def supplier_audit_conclusion(
    request: Request,
    audit_id: int,
    conclusion: str = Form(...),
    cause: str = Form(""),
    probable_responsibility: str = Form(""),
    impact: str = Form(""),
    requested_outcome: str = Form(""),
    final_result: str = Form(""),
):
    with SessionLocal() as db:
        user, allowed = _can(request, db, True)
        audit = _audit(db, audit_id)
        if not allowed or not audit or conclusion not in CONCLUSIONS:
            return RedirectResponse(
                f"/v2-clean/processes/supplier-audits/{audit_id}?error=invalid", status_code=303
            )
        audit.conclusion = conclusion
        audit.cause = cause.strip() or None
        audit.probable_responsibility = probable_responsibility.strip() or None
        audit.impact = impact.strip() or None
        audit.requested_outcome = requested_outcome.strip() or None
        audit.final_result = final_result.strip() or None
        process = db.get(ManagementProcess, audit.process_id)
        process.phase = "conclusion"
        process.status = "closed"
        process.closed_at = datetime.now(UTC)
        _history(
            db,
            audit,
            user,
            "supplier_audit_concluded",
            f"Conclusão humana registada: {conclusion}.",
        )
        db.commit()
    return RedirectResponse(
        f"/v2-clean/processes/supplier-audits/{audit_id}#conclusion", status_code=303
    )
