from datetime import UTC, date, datetime
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from time import monotonic

from fastapi import APIRouter, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select

from app.core.database import SessionLocal
from app.core.security import verify_password
from app.models.admin import User
from app.models.documents import Document, DocumentEvent
from app.models.imports import ImportBatch, ImportError, ImportFile, ImportRawRow
from app.models.incidents import Incident, IncidentEvent, IncidentEvidence
from app.models.organization import Team
from app.models.pilot import PilotFeedback
from app.models.tasks import QuickRecord, Task, TaskComment, TaskHistory
from app.models.vehicles import Vehicle, VehicleExternalSnapshot, VehicleOperationalStatusEvent
from app.models.workshop import WorkshopProcess, WorkshopProcessEvidence, WorkshopProcessNote
from app.services.rentway_fleet_importer import import_rentway_fleet_xlsx
from app.services.audit import record_audit
from app.services.authorization import get_user_authorized_unit_codes, get_user_permission_codes
from app.services.users import create_user

templates = Jinja2Templates(directory="app/templates")
web_router = APIRouter(include_in_schema=False)


def rentway_unit_sort_key(vehicle: Vehicle) -> tuple[int, int, str]:
    unit = (vehicle.rentway_unit_nr or "").strip()
    match = re.search(r"\d+", unit)
    if match:
        return (1, int(match.group(0)), unit)
    return (0, 0, unit)

WORKSHOP_OPENING_TYPES = [
    ("walk_in", "Entrada imediata"),
    ("appointment", "Marcação"),
]

WORKSHOP_STATUSES = [
    ("opening", "Abertura"),
    ("reception", "Receção"),
    ("diagnosis", "Diagnóstico"),
    ("decision", "Decisão"),
    ("waiting_analysis", "Aguardar análise"),
    ("waiting_parts", "Aguardar material"),
    ("in_progress", "Em execução"),
    ("validation", "Validação"),
    ("closed", "Fechado"),
]

WORKSHOP_DECISIONS = [
    ("repair", "Reparar"),
    ("wait_analysis", "Aguardar análise"),
    ("order_parts", "Encomendar material"),
    ("send_to_brand", "Enviar para marca"),
    ("request_quote", "Pedir orçamento"),
    ("no_action_needed", "Sem intervenção necessária"),
]

WORKSHOP_EVIDENCE_TYPES = [
    ("photo", "Foto"),
    ("video", "Vídeo"),
    ("document", "Documento"),
    ("note", "Nota técnica"),
]

WORKSHOP_EVIDENCE_CATEGORIES = [
    ("noise", "Ruído anormal"),
    ("visible_damage", "Dano visível"),
    ("warning_light", "Luz de avaria"),
    ("wear", "Desgaste irregular"),
    ("leak", "Fuga"),
    ("broken_part", "Peça partida"),
    ("intermittent_failure", "Falha intermitente"),
    ("mileage_inconsistency", "KM incoerentes"),
    ("safety", "Segurança"),
    ("other", "Outra anomalia"),
]

WORKSHOP_EVIDENCE_STATUSES = [
    ("registered", "Registada"),
    ("reviewed", "Analisada"),
    ("resolved", "Resolvida"),
    ("no_action_needed", "Sem intervenção necessária"),
]

WORKSHOP_OPENING_LABELS = dict(WORKSHOP_OPENING_TYPES)
WORKSHOP_STATUS_LABELS = dict(WORKSHOP_STATUSES)
WORKSHOP_DECISION_LABELS = dict(WORKSHOP_DECISIONS)
WORKSHOP_EVIDENCE_TYPE_LABELS = dict(WORKSHOP_EVIDENCE_TYPES)
WORKSHOP_EVIDENCE_CATEGORY_LABELS = dict(WORKSHOP_EVIDENCE_CATEGORIES)
WORKSHOP_EVIDENCE_STATUS_LABELS = dict(WORKSHOP_EVIDENCE_STATUSES)

INCIDENT_TYPES = [
    ("technical", "Técnico"),
    ("damage", "Dano"),
    ("safety", "Segurança"),
    ("customer", "Cliente"),
    ("supplier", "Fornecedor"),
    ("operational", "Operacional"),
    ("other", "Outro"),
]
INCIDENT_TYPE_LABELS = dict(INCIDENT_TYPES)

INCIDENT_CATEGORIES = [
    ("noise", "Ruído anormal"),
    ("visible_damage", "Dano visível"),
    ("warning_light", "Luz de avaria"),
    ("wear", "Desgaste irregular"),
    ("leak", "Fuga"),
    ("broken_part", "Peça partida"),
    ("safety", "Segurança"),
    ("documentation", "Documentação"),
    ("customer_report", "Reporte de cliente"),
    ("other", "Outra situação"),
]
INCIDENT_CATEGORY_LABELS = dict(INCIDENT_CATEGORIES)

INCIDENT_SEVERITIES = [
    ("low", "Baixa"),
    ("medium", "Média"),
    ("high", "Alta"),
    ("critical", "Crítica"),
]
INCIDENT_SEVERITY_LABELS = dict(INCIDENT_SEVERITIES)

INCIDENT_STATUSES = [
    ("new", "Novo"),
    ("analysis", "Em análise"),
    ("in_treatment", "Em tratamento"),
    ("waiting_decision", "A aguardar decisão"),
    ("waiting_supplier", "A aguardar fornecedor"),
    ("resolved", "Resolvido"),
    ("closed", "Fechado"),
    ("no_action_needed", "Sem ação necessária"),
]
INCIDENT_STATUS_LABELS = dict(INCIDENT_STATUSES)

INCIDENT_EVIDENCE_TYPES = [
    ("photo", "Foto"),
    ("video", "Vídeo"),
    ("audio", "Áudio/nota de voz"),
    ("document", "Documento"),
    ("link", "Link externo"),
]
INCIDENT_EVIDENCE_TYPE_LABELS = dict(INCIDENT_EVIDENCE_TYPES)

TASK_STATUSES = [
    ("new", "Nova"),
    ("in_treatment", "Em tratamento"),
    ("waiting", "A aguardar"),
    ("closed", "Fechada"),
]

TASK_STATUS_LABELS = dict(TASK_STATUSES)
TASK_LEGACY_STATUS_LABELS = {
    "analysis": "Em análise",
    "waiting_customer": "A aguardar cliente",
    "waiting_internal": "A aguardar interno",
    "waiting_supplier": "A aguardar fornecedor",
    "answered": "Respondida",
    "resolved": "Resolvida",
    "no_action_needed": "Sem ação necessária",
    "cancelled": "Cancelada",
}
TASK_STATUS_DISPLAY_LABELS = {**TASK_STATUS_LABELS, **TASK_LEGACY_STATUS_LABELS}

PRIORITIES = [
    ("normal", "Normal"),
    ("high", "Alta"),
    ("urgent", "Urgente"),
]
PRIORITY_LABELS = dict(PRIORITIES)
PRIORITY_DISPLAY_LABELS = {**PRIORITY_LABELS, "low": "Baixa"}

TASK_ARCHIVE_STATUSES = {"closed", "cancelled", "no_action_needed"}

TASK_TYPES = [
    ("operational_task", "Tarefa operacional"),
    ("management_task", "Tarefa de gestão"),
    ("request_info", "Pedido / Informação"),
    ("operational_incident", "Incidente operacional"),
    ("technical_incident", "Incidente técnico"),
    ("entity_incident", "Incidente entidade"),
    ("workshop_audit", "Tarefa de auditoria"),
]
TASK_LEGACY_TYPE_LABELS = {
    "task": "Tarefa",
    "request": "Pedido",
    "incident": "Incidente",
}
LEGACY_TASK_TYPES = list(TASK_LEGACY_TYPE_LABELS.items())
TASK_TYPE_LABELS = {**dict(TASK_TYPES), **TASK_LEGACY_TYPE_LABELS}
TASK_TYPE_CANONICAL_GROUP = {
    "task": "operational_task",
    "request": "request_info",
    "incident": "operational_incident",
}
TASK_TYPE_LEGACY_BY_CANONICAL = {
    "operational_task": ["task"],
    "request_info": ["request"],
    "operational_incident": ["incident"],
}
TASK_BOARD_TYPE_LABELS = {
    "operational_task": "Tarefas operacionais",
    "management_task": "Tarefas de gestão",
    "request_info": "Pedidos / Informação",
    "operational_incident": "Incidentes operacionais",
    "technical_incident": "Incidentes técnicos",
    "entity_incident": "Incidentes entidade",
    "workshop_audit": "Tarefas de auditoria",
}

TASK_WORKSPACES = [
    ("operational", "Operacional"),
    ("workshop", "Oficina"),
    ("management", "Gestão"),
    ("administration", "Administração"),
]
TASK_WORKSPACE_LABELS = dict(TASK_WORKSPACES)

QUICK_RECORD_TYPES_BY_WORKSPACE = {
    "operational": [
        ("request", "Pedido"),
        ("information", "Informação / Comunicação"),
        ("anomaly_incident", "Anomalia / Incidente"),
        ("complaint", "Reclamação"),
        ("other", "Outro"),
    ],
    "workshop": [
        ("technical_request", "Pedido técnico"),
        ("information", "Informação / Comunicação"),
        ("anomaly_incident", "Anomalia / Incidente"),
        ("material", "Material"),
        ("evidence", "Evidência"),
        ("other", "Outro"),
    ],
    "management": [
        ("implementation", "Implementação"),
        ("supervision", "Supervisão"),
        ("decision", "Decisão"),
        ("improvement", "Melhoria"),
        ("other", "Outro"),
    ],
    "administration": [
        ("decision", "Decisão"),
        ("sensitive_document", "Documento sensível"),
        ("finance_topic", "Tema financeiro"),
        ("reserved_followup", "Follow-up reservado"),
        ("other", "Outro"),
    ],
}
QUICK_RECORD_TYPE_LABELS = {
    code: label
    for items in QUICK_RECORD_TYPES_BY_WORKSPACE.values()
    for code, label in items
}
QUICK_RECORD_STATUSES = [
    ("new", "Novo"),
    ("analysis", "Em análise"),
    ("converted", "Convertido"),
    ("no_action_needed", "Sem ação necessária"),
    ("closed", "Fechado"),
]
QUICK_RECORD_STATUS_LABELS = dict(QUICK_RECORD_STATUSES)

WORKSHOP_BLOCKED_VEHICLE_STATUSES = {"sold", "written_off", "inactive"}

TASK_SOURCES = [
    ("manual", "Manual"),
    ("system", "Sistema"),
    ("external", "Externo"),
]

TASK_SOURCE_LABELS = dict(TASK_SOURCES)
TASK_LEGACY_SOURCE_LABELS = {
    "email": "E-mail",
    "whatsapp": "WhatsApp",
    "webex": "Webex",
    "rentway": "Rentway",
    "external_portal": "Portal externo",
}
TASK_SOURCE_DISPLAY_LABELS = {**TASK_SOURCE_LABELS, **TASK_LEGACY_SOURCE_LABELS}

TASK_CATEGORIES = [
    ("support", "Suporte"),
    ("operations", "Operações"),
    ("workshop", "Oficina"),
    ("finance", "Financeira"),
]

TASK_CATEGORY_LABELS = dict(TASK_CATEGORIES)
TASK_LEGACY_CATEGORY_LABELS = {
    "reservas": "Reservas",
    "alteracoes": "Alterações",
    "cancelamentos": "Cancelamentos",
    "caucoes_reembolsos": "Cauções/Reembolsos",
    "faturacao": "Faturação",
    "danos": "Danos",
    "sinistros": "Sinistros",
    "reclamacoes": "Reclamações",
    "assistencia": "Assistência",
    "shuttle_aeroporto": "Shuttle/Aeroporto",
    "manutencao": "Manutenção",
    "logistica_viaturas": "Logística de viaturas",
    "brokers": "Brokers",
    "corporate": "Corporate",
    "sem_acao_necessaria": "Sem ação necessária",
}
TASK_CATEGORY_DISPLAY_LABELS = {**TASK_CATEGORY_LABELS, **TASK_LEGACY_CATEGORY_LABELS}

EXTERNAL_PORTAL_CATEGORIES = [
    ("operations", "Pedido geral"),
    ("reservas", "Reserva"),
    ("alteracoes", "Alteração"),
    ("faturacao", "Faturação"),
    ("danos", "Danos"),
    ("sinistros", "Sinistro"),
    ("assistencia", "Assistência"),
    ("workshop", "Oficina"),
]
EXTERNAL_PORTAL_CATEGORY_LABELS = dict(EXTERNAL_PORTAL_CATEGORIES)
EXTERNAL_PORTAL_RATE_LIMIT: dict[str, list[float]] = {}
EXTERNAL_PORTAL_RATE_LIMIT_WINDOW_SECONDS = 600
EXTERNAL_PORTAL_RATE_LIMIT_MAX_REQUESTS = 5

PILOT_FEEDBACK_KINDS = [
    ("question", "Pedir ajuda"),
    ("experience", "Relatar experiência"),
]
PILOT_FEEDBACK_KIND_LABELS = dict(PILOT_FEEDBACK_KINDS)
PILOT_FEEDBACK_SOURCE_LABELS = {
    "dashboard": "Dashboard",
    "tasks": "Gestão de Tarefas",
    "workshop": "Oficina",
    "fleet": "Frota",
    "imports": "Importações",
    "documents": "Documentos",
    "admin": "Administração",
    "general": "Geral",
}

ADMIN_USER_ROLES = [
    ("operator", "Operador"),
    ("manager", "Gestor"),
    ("admin", "Admin"),
    ("viewer", "Consulta"),
]

IMPLEMENTATION_ROADMAP = [
    {
        "area": "Piloto",
        "title": "Gestão de relatos",
        "status": "Próximo",
        "priority": "Alta",
        "summary": "Ver autor, responder, fechar ou converter relatos em tarefas.",
    },
    {
        "area": "Documentos",
        "title": "Anexos por link",
        "status": "Próximo",
        "priority": "Alta",
        "summary": "Associar links 365, fotos, vídeos ou evidências a tarefas e processos.",
    },
    {
        "area": "Stock",
        "title": "Gestão de stock fase 1",
        "status": "A avaliar",
        "priority": "Alta",
        "summary": "Artigos, movimentos simples, pedidos e consumo associado à operação.",
    },
    {
        "area": "Tarefas",
        "title": "Fluxos por tarefa tipo lego",
        "status": "A desenhar",
        "priority": "Alta",
        "summary": "Montar fluxos com ações reutilizáveis por natureza ou contexto.",
    },
    {
        "area": "Comunicação",
        "title": "Envio e receção de e-mails",
        "status": "A avaliar",
        "priority": "Média",
        "summary": "Criar tarefas a partir de e-mail e responder com histórico associado.",
    },
    {
        "area": "Arquivo",
        "title": "Estrutura documental 365",
        "status": "A validar",
        "priority": "Média",
        "summary": "Regras leves de arquivo por Frota, Financeiro, Rentway e Arquivo Geral.",
    },
    {
        "area": "Portal externo",
        "title": "Portal externo fase 2",
        "status": "Futuro",
        "priority": "Média",
        "summary": "Permitir anexos e melhor classificação de pedidos externos.",
    },
    {
        "area": "Administração",
        "title": "Permissões e áreas",
        "status": "A validar",
        "priority": "Média",
        "summary": "Afinar áreas autorizadas, equipas, filas e níveis de acesso.",
    },
]

DOCUMENT_AREAS = [
    ("fleet", "Frota"),
    ("finance", "Financeiro"),
    ("rentway_imports", "Rentway Importações"),
    ("general_archive", "Arquivo Geral"),
]
DOCUMENT_AREA_LABELS = dict(DOCUMENT_AREAS)

DOCUMENT_TYPES = [
    ("general_fleet", "Geral Frota"),
    ("general_finance", "Geral Financeiro"),
    ("general_rentway", "Geral Rentway"),
    ("general_archive", "Geral Arquivo"),
]
DOCUMENT_TYPE_LABELS = dict(DOCUMENT_TYPES)

DOCUMENT_STATUSES = [
    ("unclassified", "Por classificar"),
    ("classified", "Classificado"),
    ("archived", "Arquivado"),
    ("rejected", "Rejeitado / Sem interesse"),
]
DOCUMENT_STATUS_LABELS = dict(DOCUMENT_STATUSES)

DOCUMENT_SOURCES = [
    ("email", "E-mail"),
    ("manual", "Manual"),
    ("whatsapp", "WhatsApp"),
    ("scanner", "Scanner"),
    ("rentway", "Rentway"),
    ("onedrive", "OneDrive/SharePoint"),
    ("other", "Outro"),
]


@web_router.get("/portal", response_class=HTMLResponse)
@web_router.get("/portal/pedido", response_class=HTMLResponse)
def external_portal_request_form(
    request: Request,
    sent: str | None = None,
    ref: str | None = None,
    error: str | None = None,
):
    error_messages = {
        "required": "Indica o assunto, a mensagem e pelo menos um contacto.",
        "consent": "Confirma que podemos usar os dados enviados para tratar o pedido.",
        "rate_limit": "Foram enviados vários pedidos recentemente. Tenta novamente dentro de alguns minutos.",
        "spam": "Não foi possível registar o pedido.",
    }
    return templates.TemplateResponse(
        request,
        "external_request.html",
        {
            "categories": EXTERNAL_PORTAL_CATEGORIES,
            "sent": sent == "1",
            "reference": ref,
            "error": error_messages.get(error),
        },
    )


@web_router.post("/portal/pedido", response_class=HTMLResponse)
def external_portal_request_create(
    request: Request,
    name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    category: str = Form("operations"),
    subject: str = Form(""),
    message: str = Form(""),
    plate: str = Form(""),
    reservation_number: str = Form(""),
    contract_number: str = Form(""),
    station: str = Form(""),
    consent: str = Form(""),
    company: str = Form(""),
):
    if company.strip():
        return RedirectResponse("/portal/pedido?error=spam", status_code=303)
    if not external_portal_rate_limit_allows(external_client_key(request)):
        return RedirectResponse("/portal/pedido?error=rate_limit", status_code=303)
    if not consent:
        return RedirectResponse("/portal/pedido?error=consent", status_code=303)

    clean_subject = subject.strip()
    clean_message = message.strip()
    clean_email = email.strip().lower()
    clean_phone = phone.strip()
    clean_name = name.strip()
    if not clean_subject or not clean_message or not (clean_email or clean_phone):
        return RedirectResponse("/portal/pedido?error=required", status_code=303)
    if category not in EXTERNAL_PORTAL_CATEGORY_LABELS:
        category = "operations"

    with SessionLocal() as db:
        assigned_team_id = default_team_id(db, "support") or default_team_id(db, "operations")
        task = Task(
            title=clean_subject[:200],
            description=build_external_portal_description(
                message=clean_message,
                category=category,
                station=station,
            ),
            task_type="request_info",
            source="external_portal",
            category=category,
            subcategory="Portal externo",
            status="new",
            priority="normal",
            customer_name=clean_name[:200] or None,
            customer_contact=(clean_email or clean_phone)[:200] or None,
            customer_email=clean_email[:255] or None,
            customer_phone=clean_phone[:80] or None,
            plate=plate.strip().upper().replace(" ", "")[:40] or None,
            reservation_number=reservation_number.strip()[:120] or None,
            contract_number=contract_number.strip()[:120] or None,
            station=station.strip()[:120] or None,
            department="Suporte",
            external_source_id=None,
            assigned_to_id=None,
            team_id=assigned_team_id,
            created_by_id=None,
        )
        db.add(task)
        db.flush()
        task.external_source_id = f"portal:{task.id:05d}"
        db.add(
            TaskHistory(
                task_id=task.id,
                user_id=None,
                field_name="status",
                old_value=None,
                new_value="new",
            )
        )
        db.add(
            TaskComment(
                task_id=task.id,
                user_id=None,
                comment="Pedido recebido através do portal externo.",
            )
        )
        record_audit(
            db,
            action="external_portal.task_created",
            entity_type="task",
            entity_id=task.id,
            detail=f"Pedido externo registado: {task.title}",
            after_json={
                "source": "external_portal",
                "category": category,
                "team_id": assigned_team_id,
            },
            user_id=None,
        )
        db.commit()
        reference = f"CF-TASK-{task.id:05d}"

    return RedirectResponse(f"/portal/pedido?sent=1&ref={reference}", status_code=303)


@web_router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user:
            return RedirectResponse("/login", status_code=303)
        today = date.today()
        open_task_condition = (Task.closed_at.is_(None), ~Task.status.in_(TASK_ARCHIVE_STATUSES))
        unavailable_vehicle_statuses = {"blocked", "in_maintenance", "in_preparation", "in_impro"}
        open_workshop_statuses = {code for code, _ in WORKSHOP_STATUSES if code != "closed"}
        metrics = {
            "vehicles": db.scalar(select(Vehicle).count()) if False else count_rows(db, Vehicle),
            "for_sale_vehicles": db.scalar(
                select(func.count()).select_from(Vehicle).where(Vehicle.lifecycle_status == "for_sale")
            )
            or 0,
            "open_tasks": db.scalar(
                select(func.count()).select_from(Task).where(*open_task_condition)
            )
            or 0,
            "imports": count_rows(db, ImportBatch),
            "documents": count_rows(db, Document),
            "overdue_tasks": db.scalar(
                select(func.count()).select_from(Task).where(
                    *open_task_condition,
                    Task.due_on.is_not(None),
                    Task.due_on < today,
                )
            )
            or 0,
            "unassigned_tasks": db.scalar(
                select(func.count()).select_from(Task).where(
                    *open_task_condition,
                    Task.assigned_to_id.is_(None),
                    Task.team_id.is_(None),
                )
            )
            or 0,
            "due_today_tasks": db.scalar(
                select(func.count()).select_from(Task).where(*open_task_condition, Task.due_on == today)
            )
            or 0,
            "unavailable_vehicles": db.scalar(
                select(func.count()).select_from(Vehicle).where(
                    Vehicle.active.is_(True),
                    Vehicle.operational_status.in_(unavailable_vehicle_statuses),
                )
            )
            or 0,
            "open_workshop": db.scalar(
                select(func.count()).select_from(WorkshopProcess).where(
                    WorkshopProcess.closed_at.is_(None),
                    WorkshopProcess.status.in_(open_workshop_statuses),
                )
            )
            or 0,
            "document_inbox": db.scalar(
                select(func.count()).select_from(Document).where(
                    Document.archived.is_(False),
                    Document.status.in_({"received", "unclassified"}),
                )
            )
            or 0,
            "import_errors": db.scalar(select(func.count()).select_from(ImportError)) or 0,
        }
        priority_tasks = db.scalars(
            select(Task)
            .where(*open_task_condition)
            .order_by(Task.due_on.is_(None), Task.due_on, Task.priority.desc(), Task.id.desc())
            .limit(5)
        ).all()
        critical_vehicles = db.scalars(
            select(Vehicle)
            .where(
                Vehicle.active.is_(True),
                Vehicle.operational_status.in_(unavailable_vehicle_statuses),
            )
            .order_by(Vehicle.updated_at.desc(), Vehicle.id.desc())
            .limit(5)
        ).all()
        recent_tasks = db.scalars(select(Task).order_by(Task.created_at.desc(), Task.id.desc()).limit(3)).all()
        recent_workshop = db.scalars(
            select(WorkshopProcess).order_by(WorkshopProcess.created_at.desc(), WorkshopProcess.id.desc()).limit(3)
        ).all()
        recent_imports = db.scalars(select(ImportBatch).order_by(ImportBatch.id.desc()).limit(3)).all()
        recent_activity = (
            [{"kind": "Tarefa", "title": item.title, "detail": item.status, "created_at": item.created_at} for item in recent_tasks]
            + [
                {"kind": "Oficina", "title": item.title, "detail": item.status, "created_at": item.created_at}
                for item in recent_workshop
            ]
            + [
                {
                    "kind": "Importação",
                    "title": f"{item.source_system} / {item.import_type}",
                    "detail": item.status,
                    "created_at": item.created_at,
                }
                for item in recent_imports
            ]
        )
        recent_activity = sorted(
            recent_activity,
            key=lambda item: item["created_at"] or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )[:6]
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "user": user,
                "permissions": sorted(get_user_permission_codes(db, user)),
                "authorized_units": sorted(get_user_authorized_unit_codes(db, user)),
                "metrics": metrics,
                "priority_tasks": priority_tasks,
                "critical_vehicles": critical_vehicles,
                "recent_activity": recent_activity,
                "task_status_labels": TASK_STATUS_DISPLAY_LABELS,
                "task_category_labels": TASK_CATEGORY_DISPLAY_LABELS,
                "priority_labels": PRIORITY_DISPLAY_LABELS,
                "vehicle_status_labels": {
                    "blocked": "Bloqueada",
                    "in_maintenance": "Em manutenção",
                    "in_preparation": "Em preparação",
                    "in_impro": "Em impro",
                },
            },
        )


@web_router.get("/admin", response_class=HTMLResponse)
def admin_page(
    request: Request,
    user_created: str | None = None,
    error: str | None = None,
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user:
            return RedirectResponse("/login", status_code=303)
        pilot_feedback_items = db.scalars(
            select(PilotFeedback).order_by(PilotFeedback.id.desc()).limit(20)
        ).all()
        pilot_feedback_counts = {
            "total": db.scalar(select(func.count()).select_from(PilotFeedback)) or 0,
            "open": db.scalar(
                select(func.count()).select_from(PilotFeedback).where(PilotFeedback.status == "open")
            )
            or 0,
            "tasks": db.scalar(
                select(func.count()).select_from(PilotFeedback).where(PilotFeedback.source_area == "tasks")
            )
            or 0,
            "workshop": db.scalar(
                select(func.count()).select_from(PilotFeedback).where(PilotFeedback.source_area == "workshop")
            )
            or 0,
        }
        users = db.scalars(select(User).order_by(User.name, User.email).limit(50)).all()
        return templates.TemplateResponse(
            request,
            "admin.html",
            {
                "user": user,
                "users": users,
                "permissions": sorted(get_user_permission_codes(db, user)),
                "authorized_units": sorted(get_user_authorized_unit_codes(db, user)),
                "pilot_feedback_items": pilot_feedback_items,
                "pilot_feedback_counts": pilot_feedback_counts,
                "pilot_feedback_kind_labels": PILOT_FEEDBACK_KIND_LABELS,
                "pilot_feedback_source_labels": PILOT_FEEDBACK_SOURCE_LABELS,
                "implementation_roadmap": IMPLEMENTATION_ROADMAP,
                "admin_user_roles": ADMIN_USER_ROLES,
                "user_created": user_created,
                "error": error,
            },
        )


@web_router.post("/admin/users", response_class=HTMLResponse)
def admin_create_user(
    request: Request,
    name: str = Form(""),
    email: str = Form(""),
    password: str = Form(""),
    role_code: str = Form("operator"),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    clean_name = name.strip()
    clean_email = email.strip().lower()
    clean_password = password.strip()
    allowed_roles = {code for code, _ in ADMIN_USER_ROLES}
    if role_code not in allowed_roles:
        role_code = "operator"

    if not clean_name or not clean_email or not clean_password:
        return RedirectResponse("/admin?error=Preenche%20nome%2C%20email%20e%20password.", status_code=303)
    if "@" not in clean_email:
        return RedirectResponse("/admin?error=Email%20invalido.", status_code=303)
    if len(clean_password) < 8:
        return RedirectResponse("/admin?error=A%20password%20deve%20ter%20pelo%20menos%208%20caracteres.", status_code=303)

    with SessionLocal() as db:
        current_user = db.get(User, user_id)
        if not current_user:
            return RedirectResponse("/login", status_code=303)
        existing = db.scalar(select(User).where(User.email == clean_email))
        if existing:
            return RedirectResponse("/admin?error=Já%20existe%20um%20utilizador%20com%20esse%20email.", status_code=303)

        new_user = create_user(
            db,
            name=clean_name,
            email=clean_email,
            password=clean_password,
            role_codes=[role_code],
            organizational_unit_codes=["carfast", "workshop"],
        )
        record_audit(
            db,
            action="admin.user.created",
            entity_type="user",
            entity_id=new_user.id,
            detail=f"Utilizador criado na administracao: {new_user.email}",
            after_json={"role": role_code, "units": ["carfast", "workshop"]},
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse("/admin?user_created=1", status_code=303)


@web_router.get("/pilot-feedback/new", response_class=HTMLResponse)
def pilot_feedback_form(
    request: Request,
    kind: str = "question",
    source_area: str = "workshop",
    entity_type: str = "",
    entity_id: str = "",
    return_url: str = "",
    saved: str | None = None,
):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    if kind not in PILOT_FEEDBACK_KIND_LABELS:
        kind = "question"
    return templates.TemplateResponse(
        request,
        "pilot_feedback_form.html",
        {
            "kind": kind,
            "kind_label": PILOT_FEEDBACK_KIND_LABELS[kind],
            "source_area": source_area,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "return_url": return_url,
            "saved": saved,
            "kind_labels": PILOT_FEEDBACK_KIND_LABELS,
        },
    )


@web_router.get("/manual", response_class=HTMLResponse)
def app_manual_page(request: Request, return_url: str = ""):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    safe_return_url = return_url if return_url.startswith("/") else ""
    return templates.TemplateResponse(
        request,
        "app_manual.html",
        {
            "return_url": safe_return_url,
        },
    )


@web_router.post("/pilot-feedback", response_class=HTMLResponse)
def pilot_feedback_create(
    request: Request,
    kind: str = Form("question"),
    source_area: str = Form("workshop"),
    entity_type: str = Form(""),
    entity_id: str = Form(""),
    subject: str = Form(""),
    body: str = Form(""),
    attachment_url: str = Form(""),
    current_url: str = Form(""),
    return_url: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    if kind not in PILOT_FEEDBACK_KIND_LABELS:
        kind = "question"

    clean_subject = subject.strip()
    clean_body = body.strip() or "Registo criado sem detalhe."
    clean_attachment_url = attachment_url.strip()
    if clean_attachment_url:
        clean_body = f"{clean_body}\n\nAnexo / evidência: {clean_attachment_url}"
    with SessionLocal() as db:
        item = PilotFeedback(
            kind=kind,
            status="open",
            source_area=source_area.strip() or None,
            entity_type=entity_type.strip() or None,
            entity_id=entity_id.strip() or None,
            subject=clean_subject or PILOT_FEEDBACK_KIND_LABELS[kind],
            body=clean_body,
            current_url=current_url.strip() or None,
            user_id=user_id,
        )
        db.add(item)
        db.flush()
        record_audit(
            db,
            action="pilot.feedback.created",
            entity_type="pilot_feedback",
            entity_id=item.id,
            detail=f"Feedback de piloto registado: {PILOT_FEEDBACK_KIND_LABELS[kind]}",
            after_json={
                "kind": kind,
                "source_area": item.source_area,
                "linked_entity_type": item.entity_type,
                "linked_entity_id": item.entity_id,
            },
            user_id=user_id,
        )
        db.commit()

    if return_url.startswith("/"):
        return RedirectResponse(add_query_flag(return_url, "feedback_saved", "1"), status_code=303)
    return RedirectResponse(f"/pilot-feedback/new?kind={kind}&saved=1", status_code=303)


@web_router.get("/fleet", response_class=HTMLResponse)
def vehicles_page(request: Request, q: str | None = None, scope: str = "active", imported: str | None = None):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    with SessionLocal() as db:
        stmt = select(Vehicle).order_by(Vehicle.id.desc()).limit(5000)
        if scope not in {"active", "for_sale", "sold", "all"}:
            scope = "active"
        sold_filter = or_(Vehicle.lifecycle_status == "sold", Vehicle.operational_status == "sold")
        if scope == "active":
            stmt = stmt.where(Vehicle.active.is_(True), ~sold_filter)
        elif scope == "for_sale":
            stmt = stmt.where(Vehicle.lifecycle_status == "for_sale")
        elif scope == "sold":
            stmt = stmt.where(sold_filter)
        if q:
            normalized = q.strip().upper().replace(" ", "")
            stmt = stmt.where(
                (Vehicle.plate == normalized)
                | (Vehicle.vin == normalized)
                | (Vehicle.rentway_unit_nr == normalized)
                | Vehicle.brand.ilike(f"%{q}%")
                | Vehicle.model.ilike(f"%{q}%")
            )
        vehicles = sorted(db.scalars(stmt).all(), key=rentway_unit_sort_key, reverse=True)[:100]
        last_fleet_import = db.scalar(
            select(ImportBatch)
            .where(ImportBatch.import_type == "rentway_fleet")
            .order_by(ImportBatch.id.desc())
            .limit(1)
        )
        for_sale_count = db.scalar(
            select(func.count()).select_from(Vehicle).where(Vehicle.lifecycle_status == "for_sale")
        ) or 0
        return templates.TemplateResponse(
            request,
            "vehicles.html",
            {
                "vehicles": vehicles,
                "q": q or "",
                "scope": scope,
                "imported": imported,
                "last_fleet_import": last_fleet_import,
                "for_sale_count": for_sale_count,
            },
        )


@web_router.get("/fleet/{vehicle_id}", response_class=HTMLResponse)
def vehicle_detail(
    request: Request,
    vehicle_id: int,
    saved: str | None = None,
    task_created: str | None = None,
    document_created: str | None = None,
):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        vehicle = db.get(Vehicle, vehicle_id)
        if not vehicle:
            return RedirectResponse("/fleet", status_code=303)

        snapshot = db.scalar(
            select(VehicleExternalSnapshot)
            .where(VehicleExternalSnapshot.vehicle_id == vehicle.id)
            .order_by(VehicleExternalSnapshot.updated_at.desc())
        )
        events = db.scalars(
            select(VehicleOperationalStatusEvent)
            .where(VehicleOperationalStatusEvent.vehicle_id == vehicle.id)
            .order_by(VehicleOperationalStatusEvent.created_at.desc())
            .limit(20)
        ).all()
        vehicle_tasks = db.scalars(
            select(Task)
            .where(
                Task.entity_type == "vehicle",
                Task.entity_id == str(vehicle.id),
                Task.closed_at.is_(None),
            )
            .order_by(Task.id.desc())
        ).all()
        workshop_processes = db.scalars(
            select(WorkshopProcess)
            .where(
                WorkshopProcess.vehicle_id == vehicle.id,
                WorkshopProcess.closed_at.is_(None),
            )
            .order_by(WorkshopProcess.id.desc())
        ).all()
        documents = db.scalars(
            select(Document)
            .where(or_(Document.vehicle_id == vehicle.id, Document.plate == (vehicle.plate or "")))
            .order_by(Document.id.desc())
            .limit(20)
        ).all()
        return templates.TemplateResponse(
            request,
            "vehicle_detail.html",
            {
                "vehicle": vehicle,
                "snapshot": snapshot,
                "events": events,
                "vehicle_tasks": vehicle_tasks,
                "workshop_processes": workshop_processes,
                "documents": documents,
                "document_status_labels": DOCUMENT_STATUS_LABELS,
                "document_area_labels": DOCUMENT_AREA_LABELS,
                "document_type_labels": DOCUMENT_TYPE_LABELS,
                "workshop_status_labels": WORKSHOP_STATUS_LABELS,
                "saved": saved,
                "task_created": task_created,
                "document_created": document_created,
                "error": None,
            },
        )


@web_router.post("/fleet/{vehicle_id}/events", response_class=HTMLResponse)
def vehicle_add_event(
    request: Request,
    vehicle_id: int,
    note: str = Form(...),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    clean_note = note.strip()
    with SessionLocal() as db:
        vehicle = db.get(Vehicle, vehicle_id)
        if not vehicle:
            return RedirectResponse("/fleet", status_code=303)
        if not clean_note:
            snapshot = db.scalar(
                select(VehicleExternalSnapshot)
                .where(VehicleExternalSnapshot.vehicle_id == vehicle.id)
                .order_by(VehicleExternalSnapshot.updated_at.desc())
            )
            events = db.scalars(
                select(VehicleOperationalStatusEvent)
                .where(VehicleOperationalStatusEvent.vehicle_id == vehicle.id)
                .order_by(VehicleOperationalStatusEvent.created_at.desc())
                .limit(20)
            ).all()
            vehicle_tasks = db.scalars(
                select(Task)
                .where(
                    Task.entity_type == "vehicle",
                    Task.entity_id == str(vehicle.id),
                    Task.closed_at.is_(None),
                )
                .order_by(Task.id.desc())
            ).all()
            workshop_processes = db.scalars(
                select(WorkshopProcess)
                .where(
                    WorkshopProcess.vehicle_id == vehicle.id,
                    WorkshopProcess.closed_at.is_(None),
                )
                .order_by(WorkshopProcess.id.desc())
            ).all()
            return templates.TemplateResponse(
                request,
                "vehicle_detail.html",
                {
                    "vehicle": vehicle,
                    "snapshot": snapshot,
                    "events": events,
                    "vehicle_tasks": vehicle_tasks,
                    "workshop_processes": workshop_processes,
                    "workshop_status_labels": WORKSHOP_STATUS_LABELS,
                    "saved": None,
                    "task_created": None,
                    "error": "Escreve uma nota antes de gravar.",
                },
                status_code=400,
            )

        db.add(
            VehicleOperationalStatusEvent(
                vehicle_id=vehicle.id,
                status=vehicle.operational_status or "note",
                occurred_at=datetime.now(UTC),
                source="internal",
                note=clean_note,
            )
        )
        record_audit(
            db,
            action="vehicle.event.created",
            entity_type="vehicle",
            entity_id=vehicle.id,
            detail=f"Nota interna adicionada a {vehicle.plate or vehicle.id}",
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse(f"/fleet/{vehicle_id}?saved=1", status_code=303)


@web_router.post("/fleet/{vehicle_id}/tasks", response_class=HTMLResponse)
def vehicle_create_task(
    request: Request,
    vehicle_id: int,
    title: str = Form(...),
    priority: str = Form("normal"),
    description: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    clean_title = title.strip()
    with SessionLocal() as db:
        vehicle = db.get(Vehicle, vehicle_id)
        if not vehicle:
            return RedirectResponse("/fleet", status_code=303)

        if not clean_title:
            snapshot = db.scalar(
                select(VehicleExternalSnapshot)
                .where(VehicleExternalSnapshot.vehicle_id == vehicle.id)
                .order_by(VehicleExternalSnapshot.updated_at.desc())
            )
            events = db.scalars(
                select(VehicleOperationalStatusEvent)
                .where(VehicleOperationalStatusEvent.vehicle_id == vehicle.id)
                .order_by(VehicleOperationalStatusEvent.created_at.desc())
                .limit(20)
            ).all()
            vehicle_tasks = db.scalars(
                select(Task)
                .where(
                    Task.entity_type == "vehicle",
                    Task.entity_id == str(vehicle.id),
                    Task.closed_at.is_(None),
                )
                .order_by(Task.id.desc())
            ).all()
            workshop_processes = db.scalars(
                select(WorkshopProcess)
                .where(
                    WorkshopProcess.vehicle_id == vehicle.id,
                    WorkshopProcess.closed_at.is_(None),
                )
                .order_by(WorkshopProcess.id.desc())
            ).all()
            return templates.TemplateResponse(
                request,
                "vehicle_detail.html",
                {
                    "vehicle": vehicle,
                    "snapshot": snapshot,
                    "events": events,
                    "vehicle_tasks": vehicle_tasks,
                    "workshop_processes": workshop_processes,
                    "workshop_status_labels": WORKSHOP_STATUS_LABELS,
                    "saved": None,
                    "task_created": None,
                    "error": "Indica um título para a tarefa.",
                },
                status_code=400,
            )

        task = Task(
            title=clean_title,
            description=description.strip() or None,
            task_type="operational_task",
            source="manual",
            category="operations",
            subcategory="Frota",
            status="new",
            priority=priority,
            team_id=default_team_id(db, "operations"),
            entity_type="vehicle",
            entity_id=str(vehicle.id),
            created_by_id=user_id,
        )
        db.add(task)
        db.flush()
        db.add(
            TaskHistory(
                task_id=task.id,
                user_id=user_id,
                field_name="status",
                old_value=None,
                new_value="new",
            )
        )
        record_audit(
            db,
            action="task.create",
            entity_type="task",
            entity_id=task.id,
            detail=f"Tarefa criada para viatura {vehicle.plate or vehicle.id}: {task.title}",
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse(f"/fleet/{vehicle_id}?task_created=1", status_code=303)


@web_router.post("/fleet/{vehicle_id}/documents", response_class=HTMLResponse)
def vehicle_create_document(
    request: Request,
    vehicle_id: int,
    title: str = Form(""),
    status: str = Form("unclassified"),
    document_date: str = Form(""),
    source: str = Form("email"),
    entry_channel: str = Form(""),
    source_sender: str = Form(""),
    source_subject: str = Form(""),
    url_original: str = Form(""),
    url_archive: str = Form(""),
    supplier_name: str = Form(""),
    notes: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        vehicle = db.get(Vehicle, vehicle_id)
        if not vehicle:
            return RedirectResponse("/fleet", status_code=303)
        try:
            add_document_record(
                db,
                title=title,
                classification="fleet",
                document_type="general_fleet",
                status=status,
                document_date=parse_optional_date(document_date),
                source=source,
                entry_channel=entry_channel,
                source_sender=source_sender,
                source_subject=source_subject,
                url_original=url_original,
                url_archive=url_archive,
                plate=vehicle.plate or "",
                vehicle_id=vehicle.id,
                supplier_name=supplier_name,
                customer_name="",
                task_id=None,
                workshop_process_id=None,
                notes=notes,
                user_id=user_id,
            )
        except ValueError:
            return RedirectResponse(f"/fleet/{vehicle_id}?error=Indica%20título%20e%20link.", status_code=303)
        db.commit()

    return RedirectResponse(f"/fleet/{vehicle_id}?document_created=1", status_code=303)


@web_router.get("/workshop", response_class=HTMLResponse)
def workshop_center_page(
    request: Request,
    created: str | None = None,
    closed: str | None = None,
    feedback_saved: str | None = None,
):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        open_query = select(func.count()).select_from(WorkshopProcess).where(WorkshopProcess.closed_at.is_(None))
        open_count = db.scalar(open_query) or 0
        waiting_parts_count = db.scalar(
            open_query.where(WorkshopProcess.status == "waiting_parts")
        ) or 0
        waiting_analysis_count = db.scalar(
            open_query.where(WorkshopProcess.status == "waiting_analysis")
        ) or 0
        vehicles_preview = sorted(
            db.scalars(select(Vehicle).order_by(Vehicle.id.desc()).limit(5000)).all(),
            key=rentway_unit_sort_key,
            reverse=True,
        )[:3]
        return templates.TemplateResponse(
            request,
            "workshop_center.html",
            {
                "open_count": open_count,
                "waiting_parts_count": waiting_parts_count,
                "waiting_analysis_count": waiting_analysis_count,
                "vehicles_preview": vehicles_preview,
                "created": created,
                "closed": closed,
                "feedback_saved": feedback_saved,
            },
        )


@web_router.get("/workshop/new", response_class=HTMLResponse)
def workshop_new_page(request: Request, error: str | None = None):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        vehicles = sorted(
            db.scalars(select(Vehicle).order_by(Vehicle.id.desc()).limit(5000)).all(),
            key=rentway_unit_sort_key,
            reverse=True,
        )
        return templates.TemplateResponse(
            request,
            "workshop_new.html",
            {
                "vehicles": vehicles,
                "error": task_detail_error_message(error),
                "opening_types": WORKSHOP_OPENING_TYPES,
                "opening_type_labels": WORKSHOP_OPENING_LABELS,
            },
        )


@web_router.get("/workshop/manage", response_class=HTMLResponse)
def workshop_manage_page(
    request: Request,
    created: str | None = None,
    closed: str | None = None,
    feedback_saved: str | None = None,
):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        processes = db.scalars(
            select(WorkshopProcess)
            .where(WorkshopProcess.closed_at.is_(None))
            .order_by(WorkshopProcess.id.desc())
            .limit(100)
        ).all()
        vehicles = sorted(
            db.scalars(select(Vehicle).order_by(Vehicle.id.desc()).limit(5000)).all(),
            key=rentway_unit_sort_key,
            reverse=True,
        )
        vehicle_by_id = {item.id: item for item in vehicles}
        return templates.TemplateResponse(
            request,
            "workshop.html",
            {
                "processes": processes,
                "vehicle_by_id": vehicle_by_id,
                "created": created,
                "closed": closed,
                "feedback_saved": feedback_saved,
                "status_labels": WORKSHOP_STATUS_LABELS,
                "decision_labels": WORKSHOP_DECISION_LABELS,
                "opening_type_labels": WORKSHOP_OPENING_LABELS,
            },
        )


@web_router.post("/workshop", response_class=HTMLResponse)
@web_router.post("/workshop/new", response_class=HTMLResponse)
def workshop_create(
    request: Request,
    vehicle_id: str = Form(""),
    title: str = Form(""),
    opening_type: str = Form("walk_in"),
    priority: str = Form("normal"),
    km_entry: str = Form(""),
    expected_exit_on: str = Form(""),
    note: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    clean_title = title.strip()
    parsed_vehicle_id = parse_optional_int(vehicle_id)
    with SessionLocal() as db:
        vehicle = db.get(Vehicle, parsed_vehicle_id) if parsed_vehicle_id else None
        vehicle_blocked_statuses = {
            (vehicle.lifecycle_status or "").strip().lower(),
            (vehicle.operational_status or "").strip().lower(),
        } if vehicle else set()
        if not vehicle or vehicle_blocked_statuses.intersection(WORKSHOP_BLOCKED_VEHICLE_STATUSES):
            error_message = (
                "A viatura selecionada já não está elegível para reparação interna."
                if vehicle
                else "Escolhe a viatura para ligar o processo ao histórico correto."
            )
            return templates.TemplateResponse(
                request,
                "workshop_new.html",
                {
                    "error": error_message,
                    "opening_types": WORKSHOP_OPENING_TYPES,
                    "opening_type_labels": WORKSHOP_OPENING_LABELS,
                },
                status_code=400,
            )

        expected_date = parse_optional_date(expected_exit_on)
        fallback_title = note.strip().splitlines()[0][:120] if note.strip() else ""
        clean_title = clean_title or fallback_title or f"Processo oficina - {vehicle.plate or vehicle.id}"
        process = WorkshopProcess(
            vehicle_id=vehicle.id,
            title=clean_title,
            opening_type=opening_type,
            status="opening",
            priority=priority,
            source="internal",
            opened_by_id=user_id,
            opened_on=date.today(),
            expected_exit_on=expected_date,
            km_entry=parse_optional_int(km_entry),
            note=note.strip() or None,
        )
        db.add(process)
        db.flush()
        record_audit(
            db,
            action="workshop.process.created",
            entity_type="workshop_process",
            entity_id=process.id,
            detail=f"Processo de oficina criado para {vehicle.plate or vehicle.id}: {process.title}",
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse("/workshop/manage?created=1", status_code=303)


def render_workshop_detail(
    request: Request,
    db,
    process: WorkshopProcess,
    *,
    noted: str | None = None,
    evidence_created: str | None = None,
    incident_created: str | None = None,
    document_created: str | None = None,
    feedback_saved: str | None = None,
    error: str | None = None,
    status_code: int = 200,
):
    vehicle = db.get(Vehicle, process.vehicle_id)
    notes = db.scalars(
        select(WorkshopProcessNote)
        .where(WorkshopProcessNote.process_id == process.id)
        .order_by(WorkshopProcessNote.created_at.desc())
    ).all()
    evidences = db.scalars(
        select(WorkshopProcessEvidence)
        .where(WorkshopProcessEvidence.process_id == process.id)
        .order_by(WorkshopProcessEvidence.id.desc())
    ).all()
    incidents = db.scalars(
        select(Incident)
        .where(Incident.workshop_process_id == process.id)
        .order_by(Incident.id.desc())
    ).all()
    incident_evidences = db.scalars(
        select(IncidentEvidence)
        .where(IncidentEvidence.incident_id.in_([item.id for item in incidents]))
        .order_by(IncidentEvidence.id.desc())
    ).all() if incidents else []
    incident_evidences_by_incident: dict[int, list[IncidentEvidence]] = {}
    for item in incident_evidences:
        incident_evidences_by_incident.setdefault(item.incident_id, []).append(item)
    documents = db.scalars(
        select(Document)
        .where(Document.workshop_process_id == process.id)
        .order_by(Document.id.desc())
        .limit(20)
    ).all()
    return templates.TemplateResponse(
        request,
        "workshop_detail.html",
        {
            "process": process,
            "vehicle": vehicle,
            "notes": notes,
            "evidences": evidences,
            "incidents": incidents,
            "incident_evidences_by_incident": incident_evidences_by_incident,
            "documents": documents,
            "noted": noted,
            "evidence_created": evidence_created,
            "incident_created": incident_created,
            "document_created": document_created,
            "feedback_saved": feedback_saved,
            "error": error,
            "statuses": WORKSHOP_STATUSES,
            "decisions": WORKSHOP_DECISIONS,
            "evidence_types": WORKSHOP_EVIDENCE_TYPES,
            "evidence_categories": WORKSHOP_EVIDENCE_CATEGORIES,
            "evidence_statuses": WORKSHOP_EVIDENCE_STATUSES,
            "opening_type_labels": WORKSHOP_OPENING_LABELS,
            "status_labels": WORKSHOP_STATUS_LABELS,
            "decision_labels": WORKSHOP_DECISION_LABELS,
            "evidence_type_labels": WORKSHOP_EVIDENCE_TYPE_LABELS,
            "evidence_category_labels": WORKSHOP_EVIDENCE_CATEGORY_LABELS,
            "evidence_status_labels": WORKSHOP_EVIDENCE_STATUS_LABELS,
            "incident_types": INCIDENT_TYPES,
            "incident_type_labels": INCIDENT_TYPE_LABELS,
            "incident_categories": INCIDENT_CATEGORIES,
            "incident_category_labels": INCIDENT_CATEGORY_LABELS,
            "incident_severities": INCIDENT_SEVERITIES,
            "incident_severity_labels": INCIDENT_SEVERITY_LABELS,
            "incident_status_labels": INCIDENT_STATUS_LABELS,
            "incident_evidence_types": INCIDENT_EVIDENCE_TYPES,
            "incident_evidence_type_labels": INCIDENT_EVIDENCE_TYPE_LABELS,
            "document_statuses": DOCUMENT_STATUSES,
            "document_status_labels": DOCUMENT_STATUS_LABELS,
            "document_area_labels": DOCUMENT_AREA_LABELS,
            "document_type_labels": DOCUMENT_TYPE_LABELS,
            "document_sources": DOCUMENT_SOURCES,
        },
        status_code=status_code,
    )


@web_router.get("/workshop/{process_id}", response_class=HTMLResponse)
def workshop_detail(
    request: Request,
    process_id: int,
    noted: str | None = None,
    evidence_created: str | None = None,
    incident_created: str | None = None,
    document_created: str | None = None,
    feedback_saved: str | None = None,
):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        process = db.get(WorkshopProcess, process_id)
        if not process:
            return RedirectResponse("/workshop", status_code=303)
        return render_workshop_detail(
            request,
            db,
            process,
            noted=noted,
            evidence_created=evidence_created,
            incident_created=incident_created,
            document_created=document_created,
            feedback_saved=feedback_saved,
        )


@web_router.post("/workshop/{process_id}/notes", response_class=HTMLResponse)
def workshop_add_note(
    request: Request,
    process_id: int,
    note: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    clean_note = note.strip()
    with SessionLocal() as db:
        process = db.get(WorkshopProcess, process_id)
        if not process:
            return RedirectResponse("/workshop", status_code=303)
        if not clean_note:
            return RedirectResponse(f"/workshop/{process_id}", status_code=303)

        db.add(WorkshopProcessNote(process_id=process.id, user_id=user_id, note=clean_note))
        record_audit(
            db,
            action="workshop.process.note.created",
            entity_type="workshop_process",
            entity_id=process.id,
            detail=f"Nota adicionada ao processo de oficina: {process.title}",
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse(f"/workshop/{process_id}?noted=1", status_code=303)


@web_router.post("/workshop/{process_id}/evidences", response_class=HTMLResponse)
def workshop_add_evidence(
    request: Request,
    process_id: int,
    phase: str = Form(...),
    evidence_type: str = Form(...),
    anomaly_category: str = Form(...),
    status: str = Form("registered"),
    description: str = Form(""),
    external_url: str = Form(""),
    storage_provider: str = Form("external"),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    allowed_phases = {code for code, _ in WORKSHOP_STATUSES}
    allowed_types = {code for code, _ in WORKSHOP_EVIDENCE_TYPES}
    allowed_categories = {code for code, _ in WORKSHOP_EVIDENCE_CATEGORIES}
    allowed_statuses = {code for code, _ in WORKSHOP_EVIDENCE_STATUSES}
    if phase not in allowed_phases:
        phase = "diagnosis"
    if evidence_type not in allowed_types:
        evidence_type = "photo"
    if anomaly_category not in allowed_categories:
        anomaly_category = "other"
    if status not in allowed_statuses:
        status = "registered"

    clean_description = description.strip()
    clean_url = external_url.strip()
    clean_provider = storage_provider.strip() or "external"

    with SessionLocal() as db:
        process = db.get(WorkshopProcess, process_id)
        if not process:
            return RedirectResponse("/workshop", status_code=303)
        if not clean_description:
            clean_description = "Evidência registada sem descrição."

        evidence = WorkshopProcessEvidence(
            process_id=process.id,
            vehicle_id=process.vehicle_id,
            user_id=user_id,
            phase=phase,
            evidence_type=evidence_type,
            anomaly_category=anomaly_category,
            status=status,
            description=clean_description,
            storage_provider=clean_provider,
            external_url=clean_url or None,
        )
        db.add(evidence)
        db.add(
            WorkshopProcessNote(
                process_id=process.id,
                user_id=user_id,
                note=(
                    "Evidência registada: "
                    f"{WORKSHOP_EVIDENCE_CATEGORY_LABELS.get(anomaly_category, anomaly_category)} - "
                    f"{clean_description}"
                ),
            )
        )
        record_audit(
            db,
            action="workshop.process.evidence.created",
            entity_type="workshop_process",
            entity_id=process.id,
            detail=f"Evidência de anomalia registada: {process.title}",
            after_json={
                "phase": phase,
                "evidence_type": evidence_type,
                "anomaly_category": anomaly_category,
                "status": status,
                "has_external_url": bool(clean_url),
            },
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse(f"/workshop/{process_id}?evidence_created=1", status_code=303)


@web_router.post("/workshop/{process_id}/incidents", response_class=HTMLResponse)
def workshop_create_incident(
    request: Request,
    process_id: int,
    title: str = Form(""),
    description: str = Form(""),
    incident_type: str = Form("technical"),
    category: str = Form("other"),
    severity: str = Form("medium"),
    evidence_type: str = Form("photo"),
    evidence_description: str = Form(""),
    evidence_url: str = Form(""),
    storage_provider: str = Form("external"),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    if incident_type not in INCIDENT_TYPE_LABELS:
        incident_type = "technical"
    if category not in INCIDENT_CATEGORY_LABELS:
        category = "other"
    if severity not in INCIDENT_SEVERITY_LABELS:
        severity = "medium"
    if evidence_type not in INCIDENT_EVIDENCE_TYPE_LABELS:
        evidence_type = "photo"

    clean_description = description.strip()
    clean_evidence_description = evidence_description.strip()
    clean_evidence_url = evidence_url.strip()
    clean_provider = storage_provider.strip() or "external"

    with SessionLocal() as db:
        process = db.get(WorkshopProcess, process_id)
        if not process:
            return RedirectResponse("/workshop", status_code=303)
        vehicle = db.get(Vehicle, process.vehicle_id)
        clean_title = title.strip()
        if not clean_title:
            clean_title = clean_description.splitlines()[0][:160] if clean_description else ""
        if not clean_title:
            clean_title = f"Incidente {INCIDENT_CATEGORY_LABELS.get(category, category)}"

        incident = Incident(
            title=clean_title,
            description=clean_description or None,
            incident_type=incident_type,
            category=category,
            severity=severity,
            status="new",
            source="workshop",
            vehicle_id=process.vehicle_id,
            workshop_process_id=process.id,
            plate=vehicle.plate if vehicle else None,
            created_by_id=user_id,
            occurred_at=datetime.now(UTC),
        )
        db.add(incident)
        db.flush()
        db.add(
            IncidentEvent(
                incident_id=incident.id,
                action="created",
                new_value=incident.title,
                user_id=user_id,
            )
        )
        if clean_evidence_url or clean_evidence_description:
            db.add(
                IncidentEvidence(
                    incident_id=incident.id,
                    evidence_type=evidence_type,
                    description=clean_evidence_description or None,
                    storage_provider=clean_provider,
                    external_url=clean_evidence_url or None,
                    user_id=user_id,
                )
            )
            db.add(
                IncidentEvent(
                    incident_id=incident.id,
                    action="evidence_added",
                    new_value=INCIDENT_EVIDENCE_TYPE_LABELS.get(evidence_type, evidence_type),
                    user_id=user_id,
                )
            )
        db.add(
            WorkshopProcessNote(
                process_id=process.id,
                user_id=user_id,
                note=f"Incidente criado: {incident.title}",
            )
        )
        record_audit(
            db,
            action="incident.created",
            entity_type="incident",
            entity_id=incident.id,
            detail=f"Incidente criado no processo de oficina: {incident.title}",
            after_json={
                "workshop_process_id": process.id,
                "vehicle_id": process.vehicle_id,
                "category": category,
                "severity": severity,
                "has_evidence": bool(clean_evidence_url or clean_evidence_description),
            },
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse(f"/workshop/{process_id}?incident_created=1", status_code=303)


@web_router.post("/workshop/{process_id}/documents", response_class=HTMLResponse)
def workshop_create_document(
    request: Request,
    process_id: int,
    title: str = Form(""),
    status: str = Form("unclassified"),
    document_date: str = Form(""),
    source: str = Form("email"),
    entry_channel: str = Form(""),
    source_sender: str = Form(""),
    source_subject: str = Form(""),
    url_original: str = Form(""),
    url_archive: str = Form(""),
    supplier_name: str = Form(""),
    notes: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        process = db.get(WorkshopProcess, process_id)
        if not process:
            return RedirectResponse("/workshop", status_code=303)
        vehicle = db.get(Vehicle, process.vehicle_id)
        try:
            add_document_record(
                db,
                title=title,
                classification="fleet",
                document_type="general_fleet",
                status=status,
                document_date=parse_optional_date(document_date),
                source=source,
                entry_channel=entry_channel,
                source_sender=source_sender,
                source_subject=source_subject,
                url_original=url_original,
                url_archive=url_archive,
                plate=(vehicle.plate if vehicle else "") or "",
                vehicle_id=process.vehicle_id,
                supplier_name=supplier_name,
                customer_name="",
                task_id=None,
                workshop_process_id=process.id,
                notes=notes,
                user_id=user_id,
            )
        except ValueError:
            return RedirectResponse(f"/workshop/{process_id}?error=Indica%20título%20e%20link.", status_code=303)
        db.commit()

    return RedirectResponse(f"/workshop/{process_id}?document_created=1", status_code=303)


@web_router.post("/workshop/{process_id}/flow")
def workshop_update_flow(
    request: Request,
    process_id: int,
    status: str = Form(...),
    decision: str = Form(""),
    decision_note: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    allowed_statuses = {code for code, _ in WORKSHOP_STATUSES}
    allowed_decisions = {code for code, _ in WORKSHOP_DECISIONS}
    if status not in allowed_statuses:
        status = "opening"
    if decision and decision not in allowed_decisions:
        decision = ""

    with SessionLocal() as db:
        process = db.get(WorkshopProcess, process_id)
        if not process:
            return RedirectResponse("/workshop", status_code=303)

        old_status = process.status
        old_decision = process.decision
        process.status = status
        process.decision = decision or None
        process.decision_note = decision_note.strip() or None
        if decision and decision != old_decision:
            process.decided_by_id = user_id
            process.decided_at = datetime.now(UTC)
        if status == "closed":
            process.closed_at = process.closed_at or datetime.now(UTC)
        else:
            process.closed_at = None

        db.add(
            WorkshopProcessNote(
                process_id=process.id,
                user_id=user_id,
                note=(
                    "Fluxo atualizado: "
                    f"{WORKSHOP_STATUS_LABELS.get(old_status, old_status)} -> "
                    f"{WORKSHOP_STATUS_LABELS.get(status, status)}"
                ),
            )
        )
        record_audit(
            db,
            action="workshop.process.flow.updated",
            entity_type="workshop_process",
            entity_id=process.id,
            detail=f"Fluxo de oficina atualizado: {process.title}",
            before_json={"status": old_status, "decision": old_decision},
            after_json={"status": process.status, "decision": process.decision},
            user_id=user_id,
        )
        db.commit()

    if status == "closed":
        return RedirectResponse("/workshop/manage?closed=1", status_code=303)
    return RedirectResponse(f"/workshop/{process_id}?noted=1", status_code=303)


@web_router.post("/workshop/{process_id}/close")
def workshop_close(request: Request, process_id: int):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        process = db.get(WorkshopProcess, process_id)
        if process and not process.closed_at:
            process.status = "closed"
            process.closed_at = datetime.now(UTC)
            record_audit(
                db,
                action="workshop.process.closed",
                entity_type="workshop_process",
                entity_id=process.id,
                detail=f"Processo de oficina fechado: {process.title}",
                user_id=user_id,
            )
            db.commit()

    return RedirectResponse("/workshop/manage?closed=1", status_code=303)


@web_router.get("/imports/fleet", response_class=HTMLResponse)
def fleet_import_form(request: Request):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "fleet_import.html", {"error": None})


@web_router.post("/imports/fleet", response_class=HTMLResponse)
def fleet_import_submit(request: Request, file: UploadFile):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    if not file.filename.lower().endswith(".xlsx"):
        return templates.TemplateResponse(
            request,
            "fleet_import.html",
            {"error": "Carrega um ficheiro XLSX."},
            status_code=400,
        )

    suffix = Path(file.filename).suffix
    with NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file.file.read())
        tmp_path = Path(tmp.name)

    try:
        with SessionLocal() as db:
            stats = import_rentway_fleet_xlsx(db, tmp_path, original_name=file.filename)
    finally:
        tmp_path.unlink(missing_ok=True)

    return RedirectResponse(
        f"/fleet?imported={stats['created_rows']}+criadas,+{stats['updated_rows']}+atualizadas",
        status_code=303,
    )


@web_router.get("/imports", response_class=HTMLResponse)
def imports_page(request: Request):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        batches = db.scalars(select(ImportBatch).order_by(ImportBatch.id.desc()).limit(100)).all()
        return templates.TemplateResponse(
            request,
            "imports.html",
            {
                "batches": batches,
            },
        )


@web_router.get("/imports/{batch_id}", response_class=HTMLResponse)
def import_detail(request: Request, batch_id: int):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        batch = db.get(ImportBatch, batch_id)
        if not batch:
            return RedirectResponse("/imports", status_code=303)
        files = db.scalars(
            select(ImportFile).where(ImportFile.batch_id == batch.id).order_by(ImportFile.id)
        ).all()
        errors = db.scalars(
            select(ImportError).where(ImportError.batch_id == batch.id).order_by(ImportError.id).limit(100)
        ).all()
        raw_rows = db.scalar(
            select(func.count()).select_from(ImportRawRow).where(ImportRawRow.batch_id == batch.id)
        ) or 0
        return templates.TemplateResponse(
            request,
            "import_detail.html",
            {
                "batch": batch,
                "files": files,
                "errors": errors,
                "raw_rows": raw_rows,
            },
        )


@web_router.get("/documents", response_class=HTMLResponse)
def documents_center_page(
    request: Request,
    created: str | None = None,
    updated: str | None = None,
    feedback_saved: str | None = None,
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        metrics = {
            "total": db.scalar(select(func.count()).select_from(Document)) or 0,
            "unclassified": db.scalar(
                select(func.count()).select_from(Document).where(Document.status == "unclassified")
            )
            or 0,
            "classified": db.scalar(
                select(func.count()).select_from(Document).where(Document.status == "classified")
            )
            or 0,
            "archived": db.scalar(
                select(func.count()).select_from(Document).where(Document.status == "archived")
            )
            or 0,
        }
        return templates.TemplateResponse(
            request,
            "documents_center.html",
            {
                "metrics": metrics,
                "created": created,
                "updated": updated,
                "feedback_saved": feedback_saved,
            },
        )


@web_router.get("/documents/new", response_class=HTMLResponse)
def documents_new_page(request: Request, error: str | None = None):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request,
        "documents_new.html",
        {
            "areas": DOCUMENT_AREAS,
            "document_types": DOCUMENT_TYPES,
            "statuses": DOCUMENT_STATUSES,
            "sources": DOCUMENT_SOURCES,
            "error": error,
        },
    )


@web_router.get("/documents/manage", response_class=HTMLResponse)
def documents_manage_page(
    request: Request,
    q: str = "",
    status: str = "",
    area: str = "",
    document_type: str = "",
    created: str | None = None,
    updated: str | None = None,
    error: str | None = None,
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    clean_q = q.strip()
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user:
            return RedirectResponse("/login", status_code=303)

        statement = select(Document)
        if clean_q:
            pattern = f"%{clean_q}%"
            statement = statement.where(
                or_(
                    Document.title.ilike(pattern),
                    Document.plate.ilike(pattern),
                    Document.supplier_name.ilike(pattern),
                    Document.customer_name.ilike(pattern),
                    Document.entry_channel.ilike(pattern),
                    Document.source_sender.ilike(pattern),
                    Document.source_subject.ilike(pattern),
                )
            )
        if status in DOCUMENT_STATUS_LABELS:
            statement = statement.where(Document.status == status)
        if area in DOCUMENT_AREA_LABELS:
            statement = statement.where(Document.classification == area)
        if document_type in DOCUMENT_TYPE_LABELS:
            statement = statement.where(Document.document_type == document_type)

        documents = db.scalars(statement.order_by(Document.id.desc()).limit(100)).all()
        metrics = {
            "total": db.scalar(select(func.count()).select_from(Document)) or 0,
            "unclassified": db.scalar(
                select(func.count()).select_from(Document).where(Document.status == "unclassified")
            )
            or 0,
            "classified": db.scalar(
                select(func.count()).select_from(Document).where(Document.status == "classified")
            )
            or 0,
            "archived": db.scalar(
                select(func.count()).select_from(Document).where(Document.status == "archived")
            )
            or 0,
        }
        return templates.TemplateResponse(
            request,
            "documents.html",
            {
                "user": user,
                "documents": documents,
                "metrics": metrics,
                "filters": {
                    "q": q,
                    "status": status,
                    "area": area,
                    "document_type": document_type,
                },
                "areas": DOCUMENT_AREAS,
                "area_labels": DOCUMENT_AREA_LABELS,
                "document_types": DOCUMENT_TYPES,
                "document_type_labels": DOCUMENT_TYPE_LABELS,
                "statuses": DOCUMENT_STATUSES,
                "status_labels": DOCUMENT_STATUS_LABELS,
                "sources": DOCUMENT_SOURCES,
                "created": created,
                "updated": updated,
                "error": error,
            },
        )


@web_router.post("/documents", response_class=HTMLResponse)
@web_router.post("/documents/new", response_class=HTMLResponse)
def document_create(
    request: Request,
    title: str = Form(""),
    classification: str = Form("fleet"),
    document_type: str = Form("general_fleet"),
    status: str = Form("unclassified"),
    document_date: str = Form(""),
    source: str = Form("email"),
    entry_channel: str = Form(""),
    source_sender: str = Form(""),
    source_subject: str = Form(""),
    url_original: str = Form(""),
    url_archive: str = Form(""),
    plate: str = Form(""),
    supplier_name: str = Form(""),
    customer_name: str = Form(""),
    task_id: str = Form(""),
    workshop_process_id: str = Form(""),
    import_batch_id: str = Form(""),
    notes: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    clean_title = title.strip()
    clean_original_url = url_original.strip()
    clean_archive_url = url_archive.strip()
    if not clean_title:
        return RedirectResponse("/documents/new?error=Indica%20um%20título.", status_code=303)
    if not clean_original_url and not clean_archive_url:
        return RedirectResponse("/documents/new?error=Indica%20pelo%20menos%20um%20link.", status_code=303)
    if classification not in DOCUMENT_AREA_LABELS:
        classification = "general_archive"
    if document_type not in DOCUMENT_TYPE_LABELS:
        document_type = default_document_type_for_area(classification)
    if status not in DOCUMENT_STATUS_LABELS:
        status = "unclassified"

    parsed_document_date = parse_optional_date(document_date)
    clean_plate = plate.strip().upper()
    folder_path = suggest_document_folder_path(classification, parsed_document_date, clean_plate)
    archived = status == "archived"

    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user:
            return RedirectResponse("/login", status_code=303)

        vehicle_id = None
        if clean_plate:
            vehicle = db.scalar(select(Vehicle).where(Vehicle.plate == clean_plate))
            vehicle_id = vehicle.id if vehicle else None
        parsed_task_id = parse_optional_int(task_id)
        if parsed_task_id and not db.get(Task, parsed_task_id):
            parsed_task_id = None
        parsed_workshop_process_id = parse_optional_int(workshop_process_id)
        if parsed_workshop_process_id and not db.get(WorkshopProcess, parsed_workshop_process_id):
            parsed_workshop_process_id = None

        document = Document(
            title=clean_title,
            document_type=document_type,
            classification=classification,
            status=status,
            source=source.strip() or None,
            entry_channel=entry_channel.strip() or None,
            source_sender=source_sender.strip() or None,
            source_subject=source_subject.strip() or None,
            original_name=clean_title[:255],
            file_name=clean_title[:255],
            file_type=None,
            file_size=None,
            storage_provider="sharepoint",
            storage_path=clean_original_url or clean_archive_url,
            storage_key=clean_original_url or None,
            external_url=clean_archive_url or clean_original_url,
            folder_path=folder_path,
            vehicle_id=vehicle_id,
            task_id=parsed_task_id,
            workshop_process_id=parsed_workshop_process_id,
            plate=clean_plate or None,
            customer_name=customer_name.strip() or None,
            supplier_name=supplier_name.strip() or None,
            document_date=parsed_document_date,
            uploaded_by_id=user_id,
            archived_by_id=user_id if archived else None,
            archived_at=datetime.now(UTC) if archived else None,
            archived=archived,
        )
        db.add(document)
        db.flush()
        if import_batch_id.strip():
            db.add(
                DocumentEvent(
                    document_id=document.id,
                    action="linked.import_batch",
                    old_value=None,
                    new_value=import_batch_id.strip(),
                    user_id=user_id,
                )
            )
        if notes.strip():
            db.add(
                DocumentEvent(
                    document_id=document.id,
                    action="note",
                    old_value=None,
                    new_value=notes.strip(),
                    user_id=user_id,
                )
            )
        db.add(
            DocumentEvent(
                document_id=document.id,
                action="created",
                old_value=None,
                new_value=f"Documento criado em {DOCUMENT_AREA_LABELS[classification]}",
                user_id=user_id,
            )
        )
        record_audit(
            db,
            action="document.created",
            entity_type="document",
            entity_id=document.id,
            detail=f"Documento registado: {document.title}",
            after_json={
                "classification": classification,
                "document_type": document_type,
                "status": status,
                "folder_path": folder_path,
            },
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse("/documents/manage?created=1", status_code=303)


@web_router.get("/documents/{document_id}", response_class=HTMLResponse)
def document_detail(request: Request, document_id: int, updated: str | None = None):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        document = db.get(Document, document_id)
        if not user or not document:
            return RedirectResponse("/documents", status_code=303)
        events = db.scalars(
            select(DocumentEvent)
            .where(DocumentEvent.document_id == document.id)
            .order_by(DocumentEvent.id.desc())
        ).all()
        return templates.TemplateResponse(
            request,
            "document_detail.html",
            {
                "user": user,
                "document": document,
                "events": events,
                "areas": DOCUMENT_AREAS,
                "area_labels": DOCUMENT_AREA_LABELS,
                "document_types": DOCUMENT_TYPES,
                "document_type_labels": DOCUMENT_TYPE_LABELS,
                "statuses": DOCUMENT_STATUSES,
                "status_labels": DOCUMENT_STATUS_LABELS,
                "sources": DOCUMENT_SOURCES,
                "updated": updated,
            },
        )


@web_router.post("/documents/{document_id}/update", response_class=HTMLResponse)
def document_update(
    request: Request,
    document_id: int,
    classification: str = Form(""),
    document_type: str = Form(""),
    status: str = Form(""),
    url_archive: str = Form(""),
    notes: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        document = db.get(Document, document_id)
        if not document:
            return RedirectResponse("/documents", status_code=303)

        changes = []
        if classification in DOCUMENT_AREA_LABELS and classification != document.classification:
            changes.append(("classification", document.classification, classification))
            document.classification = classification
        if document_type in DOCUMENT_TYPE_LABELS and document_type != document.document_type:
            changes.append(("document_type", document.document_type, document_type))
            document.document_type = document_type
        if status in DOCUMENT_STATUS_LABELS and status != document.status:
            changes.append(("status", document.status, status))
            document.status = status
        clean_archive_url = url_archive.strip()
        if clean_archive_url and clean_archive_url != document.external_url:
            changes.append(("url_archive", document.external_url, clean_archive_url))
            document.external_url = clean_archive_url
        document.folder_path = suggest_document_folder_path(
            document.classification or "general_archive",
            document.document_date,
            document.plate,
        )
        if document.status == "archived":
            document.archived = True
            document.archived_by_id = user_id
            document.archived_at = document.archived_at or datetime.now(UTC)
        else:
            document.archived = False

        for field, old_value, new_value in changes:
            db.add(
                DocumentEvent(
                    document_id=document.id,
                    action=f"updated.{field}",
                    old_value=str(old_value or ""),
                    new_value=str(new_value or ""),
                    user_id=user_id,
                )
            )
        if notes.strip():
            db.add(
                DocumentEvent(
                    document_id=document.id,
                    action="note",
                    old_value=None,
                    new_value=notes.strip(),
                    user_id=user_id,
                )
            )
        if changes or notes.strip():
            record_audit(
                db,
                action="document.updated",
                entity_type="document",
                entity_id=document.id,
                detail=f"Documento atualizado: {document.title}",
                after_json={"changes": [field for field, _, _ in changes]},
                user_id=user_id,
            )
        db.commit()
    return RedirectResponse(f"/documents/{document_id}?updated=1", status_code=303)


@web_router.get("/task-board", response_class=HTMLResponse)
def task_center(request: Request):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        current_user = db.get(User, user_id)
        today = date.today()
        open_count = db.scalar(
            select(func.count()).select_from(Task).where(
                Task.closed_at.is_(None),
                ~Task.status.in_(TASK_ARCHIVE_STATUSES),
            )
        ) or 0
        due_today = db.scalar(
            select(func.count()).select_from(Task).where(
                Task.closed_at.is_(None),
                ~Task.status.in_(TASK_ARCHIVE_STATUSES),
                Task.due_on == today,
            )
        ) or 0
        quick_open_count = db.scalar(
            select(func.count()).select_from(QuickRecord).where(
                QuickRecord.workspace == "operational",
                QuickRecord.closed_at.is_(None),
                ~QuickRecord.status.in_(("closed", "no_action_needed", "converted")),
            )
        ) or 0
        return templates.TemplateResponse(
            request,
            "task_center.html",
            {
                "open_count": open_count,
                "due_today": due_today,
                "quick_open_count": quick_open_count,
                "current_user": current_user,
            },
        )


@web_router.get("/task-board/manage", response_class=HTMLResponse)
def task_board_manage(
    request: Request,
    created: str | None = None,
    closed: str | None = None,
    quick_created: str | None = None,
    feedback_saved: str | None = None,
    q: str = "",
    status: str = "",
    task_type: str = "",
    category: str = "",
    source: str = "",
    assigned_to_id: str = "",
    team_id: str = "",
    station: str = "",
    view: str = "",
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        today = date.today()
        today_start = datetime(today.year, today.month, today.day, tzinfo=UTC)
        tomorrow_start = datetime.fromtimestamp(today_start.timestamp() + 86400, UTC)
        archived_condition = (Task.closed_at.is_not(None)) | (Task.status.in_(TASK_ARCHIVE_STATUSES))
        open_stmt = select(Task).where(Task.closed_at.is_(None), ~Task.status.in_(TASK_ARCHIVE_STATUSES))
        metrics = {
            "open": db.scalar(
                select(func.count()).select_from(Task).where(Task.closed_at.is_(None), ~Task.status.in_(TASK_ARCHIVE_STATUSES))
            )
            or 0,
            "in_treatment": db.scalar(
                select(func.count()).select_from(Task).where(
                    Task.closed_at.is_(None),
                    ~Task.status.in_(TASK_ARCHIVE_STATUSES),
                    Task.status == "in_treatment",
                )
            )
            or 0,
            "unassigned": db.scalar(
                select(func.count()).select_from(Task).where(
                    Task.closed_at.is_(None),
                    ~Task.status.in_(TASK_ARCHIVE_STATUSES),
                    Task.assigned_to_id.is_(None),
                    Task.team_id.is_(None),
                )
            )
            or 0,
            "overdue": db.scalar(
                select(func.count()).select_from(Task).where(
                    Task.closed_at.is_(None),
                    ~Task.status.in_(TASK_ARCHIVE_STATUSES),
                    Task.due_on.is_not(None),
                    Task.due_on < today,
                )
            )
            or 0,
            "due_today": db.scalar(
                select(func.count()).select_from(Task).where(
                    Task.closed_at.is_(None),
                    ~Task.status.in_(TASK_ARCHIVE_STATUSES),
                    Task.due_on == today,
                )
            )
            or 0,
            "closed_today": db.scalar(
                select(func.count()).select_from(Task).where(
                    Task.closed_at.is_not(None),
                    Task.closed_at >= today_start,
                    Task.closed_at < tomorrow_start,
                )
            )
            or 0,
            "archived": db.scalar(select(func.count()).select_from(Task).where(archived_condition)) or 0,
            "quick_open": db.scalar(
                select(func.count()).select_from(QuickRecord).where(
                    QuickRecord.workspace == "operational",
                    QuickRecord.closed_at.is_(None),
                    ~QuickRecord.status.in_(("closed", "no_action_needed", "converted")),
                )
            )
            or 0,
        }

        stmt = open_stmt
        if view == "archived" or status in TASK_ARCHIVE_STATUSES:
            stmt = select(Task).where(archived_condition)
        elif view == "all":
            stmt = select(Task)
        elif view == "mine":
            stmt = stmt.where(Task.assigned_to_id == user_id)
        elif view == "team":
            stmt = stmt.where(Task.team_id.is_not(None))
        elif view == "urgent":
            stmt = stmt.where(Task.priority == "urgent")
        elif view == "unassigned":
            stmt = stmt.where(Task.assigned_to_id.is_(None), Task.team_id.is_(None))
        elif view == "overdue":
            stmt = stmt.where(Task.due_on.is_not(None), Task.due_on < today)
        elif view == "due_today":
            stmt = stmt.where(Task.due_on == today)

        clean_q = q.strip()
        if clean_q:
            like_q = f"%{clean_q}%"
            normalized_plate = clean_q.upper().replace(" ", "")
            stmt = stmt.where(
                (Task.title.ilike(like_q))
                | (Task.description.ilike(like_q))
                | (Task.customer_name.ilike(like_q))
                | (Task.customer_email.ilike(like_q))
                | (Task.customer_phone.ilike(like_q))
                | (Task.plate == normalized_plate)
                | (Task.reservation_number.ilike(like_q))
                | (Task.contract_number.ilike(like_q))
                | (Task.external_source_id.ilike(like_q))
            )
        if status:
            stmt = stmt.where(Task.status == status)
        if task_type:
            matching_task_types = [task_type, *TASK_TYPE_LEGACY_BY_CANONICAL.get(task_type, [])]
            stmt = stmt.where(Task.task_type.in_(matching_task_types))
        if category:
            stmt = stmt.where(Task.category == category)
        if source:
            stmt = stmt.where(Task.source == source)
        parsed_assigned_to_id = parse_optional_int(assigned_to_id)
        if parsed_assigned_to_id:
            stmt = stmt.where(Task.assigned_to_id == parsed_assigned_to_id)
        parsed_team_id = parse_optional_int(team_id)
        if parsed_team_id:
            stmt = stmt.where(Task.team_id == parsed_team_id)
        if station.strip():
            stmt = stmt.where(Task.station.ilike(f"%{station.strip()}%"))

        quick_archived_condition = (
            (QuickRecord.closed_at.is_not(None))
            | (QuickRecord.status.in_(("closed", "no_action_needed", "converted")))
        )
        quick_stmt = select(QuickRecord).where(QuickRecord.workspace == "operational")
        if view == "archived":
            quick_stmt = quick_stmt.where(quick_archived_condition)
        elif view == "all":
            quick_stmt = quick_stmt
        else:
            quick_stmt = quick_stmt.where(~quick_archived_condition)
        if clean_q:
            like_q = f"%{clean_q}%"
            normalized_plate = clean_q.upper().replace(" ", "")
            quick_stmt = quick_stmt.where(
                (QuickRecord.title.ilike(like_q))
                | (QuickRecord.description.ilike(like_q))
                | (QuickRecord.customer_name.ilike(like_q))
                | (QuickRecord.customer_email.ilike(like_q))
                | (QuickRecord.customer_phone.ilike(like_q))
                | (QuickRecord.plate == normalized_plate)
            )
        if status and status in QUICK_RECORD_STATUS_LABELS:
            quick_stmt = quick_stmt.where(QuickRecord.status == status)
        if source:
            quick_stmt = quick_stmt.where(QuickRecord.source == source)
        if station.strip():
            quick_stmt = quick_stmt.where(QuickRecord.station.ilike(f"%{station.strip()}%"))

        tasks = db.scalars(
            stmt.order_by(
                Task.due_on.is_(None),
                Task.due_on,
                Task.priority.desc(),
                Task.id.desc(),
            ).limit(100)
        ).all()
        quick_records = db.scalars(
            quick_stmt.order_by(QuickRecord.created_at.desc(), QuickRecord.id.desc()).limit(100)
        ).all()
        grouped_tasks = []
        used_task_types = set()
        canonical_task_type_filter = TASK_TYPE_CANONICAL_GROUP.get(task_type, task_type)
        for type_code, type_label in TASK_TYPES:
            group_items = [
                task
                for task in tasks
                if TASK_TYPE_CANONICAL_GROUP.get(task.task_type or "task", task.task_type or "task")
                == type_code
            ]
            should_show_group = (
                bool(group_items)
                or canonical_task_type_filter == type_code
            )
            if should_show_group:
                grouped_tasks.append(
                    {
                        "code": type_code,
                        "label": TASK_BOARD_TYPE_LABELS.get(type_code, type_label),
                        "tasks": group_items,
                        "count": len(group_items),
                    }
                )
                used_task_types.add(type_code)
        other_tasks = [task for task in tasks if (task.task_type or "task") not in used_task_types]
        if other_tasks:
            grouped_tasks.append(
                {
                    "code": "other",
                    "label": "Outras",
                    "tasks": other_tasks,
                    "count": len(other_tasks),
                }
            )
        quick_record_groups = []
        operational_record_type_codes = {code for code, _ in QUICK_RECORD_TYPES_BY_WORKSPACE["operational"]}
        for type_code, type_label in QUICK_RECORD_TYPES_BY_WORKSPACE["operational"]:
            group_items = [record for record in quick_records if (record.record_type or "other") == type_code]
            if group_items:
                quick_record_groups.append(
                    {
                        "code": type_code,
                        "label": type_label,
                        "records": group_items,
                        "count": len(group_items),
                    }
                )
        other_quick_records = [
            record
            for record in quick_records
            if (record.record_type or "other") not in operational_record_type_codes
        ]
        if other_quick_records:
            quick_record_groups.append(
                {
                    "code": "other",
                    "label": "Outro",
                    "records": other_quick_records,
                    "count": len(other_quick_records),
                }
            )
        users = db.scalars(select(User).where(User.active.is_(True)).order_by(User.name, User.email)).all()
        user_by_id = {item.id: item for item in users}
        teams = db.scalars(select(Team).where(Team.active.is_(True)).order_by(Team.name)).all()
        team_by_id = {item.id: item for item in teams}
        stations = [
            item
            for item in db.scalars(
                select(Task.station)
                .where(Task.station.is_not(None), Task.station != "")
                .distinct()
                .order_by(Task.station)
                .limit(100)
            ).all()
            if item
        ]
        return templates.TemplateResponse(
            request,
            "tasks.html",
            {
                "tasks": tasks,
                "task_groups": grouped_tasks,
                "users": users,
                "current_user": user_by_id.get(user_id),
                "user_by_id": user_by_id,
                "teams": teams,
                "team_by_id": team_by_id,
                "created": created,
                "closed": closed,
                "quick_created": quick_created,
                "feedback_saved": feedback_saved,
                "error": None,
                "metrics": metrics,
                "filters": {
                    "q": q,
                    "status": status,
                    "task_type": task_type,
                    "category": category,
                    "source": source,
                    "assigned_to_id": assigned_to_id,
                    "team_id": team_id,
                    "station": station,
                    "view": view,
                },
                "archive_statuses": TASK_ARCHIVE_STATUSES,
                "quick_record_groups": quick_record_groups,
                "quick_record_status_labels": QUICK_RECORD_STATUS_LABELS,
                "quick_record_type_labels": QUICK_RECORD_TYPE_LABELS,
                "stations": stations,
                "task_statuses": TASK_STATUSES,
                "task_status_labels": TASK_STATUS_DISPLAY_LABELS,
                "priorities": PRIORITIES,
                "priority_labels": PRIORITY_DISPLAY_LABELS,
                "task_types": TASK_TYPES,
                "task_type_labels": TASK_TYPE_LABELS,
                "task_sources": TASK_SOURCES,
                "task_source_labels": TASK_SOURCE_DISPLAY_LABELS,
                "task_categories": TASK_CATEGORIES,
                "task_category_labels": TASK_CATEGORY_DISPLAY_LABELS,
            },
        )


@web_router.get("/task-board/new", response_class=HTMLResponse)
def task_new_form(
    request: Request,
    error: str | None = None,
    mode: str = "task",
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        current_user = db.get(User, user_id)
        users = db.scalars(select(User).where(User.active.is_(True)).order_by(User.name, User.email)).all()
        teams = db.scalars(select(Team).where(Team.active.is_(True)).order_by(Team.name)).all()
        return templates.TemplateResponse(
            request,
            "task_new.html",
            {
                "users": users,
                "current_user": current_user,
                "teams": teams,
                "error": "Escolhe uma pessoa responsável ou uma equipa/fila." if error == "missing_destination" else None,
                "form_mode": "quick" if mode == "quick" else "task",
                "form_values": {
                    "task_type": "request_info" if mode == "quick" else "operational_task",
                    "record_type": "request",
                },
                "duplicate_tasks": [],
                "task_types": TASK_TYPES,
                "quick_record_types": QUICK_RECORD_TYPES_BY_WORKSPACE["operational"],
                "workspaces": TASK_WORKSPACES,
                "task_sources": TASK_SOURCES,
                "task_categories": TASK_CATEGORIES,
                "priorities": PRIORITIES,
            },
        )


@web_router.get("/task-board/vehicle-search")
def task_vehicle_search(request: Request):
    if not get_web_user_id(request):
        return JSONResponse({"items": []}, status_code=401)

    query = (request.query_params.get("q") or "").strip().upper().replace(" ", "")
    context = (request.query_params.get("context") or "").strip().lower()
    with SessionLocal() as db:
        statement = select(Vehicle).where(Vehicle.plate.is_not(None), Vehicle.plate != "")
        if context == "workshop":
            statement = statement.where(
                or_(
                    Vehicle.lifecycle_status.is_(None),
                    ~func.lower(Vehicle.lifecycle_status).in_(WORKSHOP_BLOCKED_VEHICLE_STATUSES),
                ),
                or_(
                    Vehicle.operational_status.is_(None),
                    ~func.lower(Vehicle.operational_status).in_(WORKSHOP_BLOCKED_VEHICLE_STATUSES),
                ),
            )
        if query:
            statement = statement.where(Vehicle.plate.ilike(f"{query}%"))
        vehicles = db.scalars(statement.order_by(Vehicle.plate).limit(12)).all()
        return {
            "items": [
                {
                    "id": vehicle.id,
                    "plate": vehicle.plate,
                    "label": " · ".join(
                        item
                        for item in [
                            vehicle.plate or "",
                            " ".join(
                                part for part in [vehicle.brand, vehicle.model] if part
                            ).strip(),
                        ]
                        if item
                    ),
                }
                for vehicle in vehicles
                if vehicle.plate
            ]
        }


@web_router.post("/task-board/quick/new", response_class=HTMLResponse)
def quick_record_create(
    request: Request,
    title: str = Form(...),
    record_type: str = Form("request"),
    workspace: str = Form("operational"),
    source: str = Form("manual"),
    priority: str = Form("normal"),
    customer_name: str = Form(""),
    customer_contact: str = Form(""),
    customer_email: str = Form(""),
    customer_phone: str = Form(""),
    plate: str = Form(""),
    station: str = Form(""),
    description: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    clean_workspace = workspace if workspace in TASK_WORKSPACE_LABELS else "operational"
    allowed_record_types = {code for code, _ in QUICK_RECORD_TYPES_BY_WORKSPACE.get(clean_workspace, [])}
    if record_type not in allowed_record_types:
        record_type = "other"
    if source not in TASK_SOURCE_DISPLAY_LABELS:
        source = "manual"
    if priority not in PRIORITY_DISPLAY_LABELS:
        priority = "normal"
    clean_title = title.strip()
    clean_plate = plate.strip().upper().replace(" ", "")
    form_values = {
        "title": clean_title,
        "description": description,
        "record_type": record_type,
        "priority": priority,
        "source": source,
        "plate": clean_plate,
        "station": station,
        "customer_name": customer_name,
        "customer_contact": customer_contact,
        "customer_email": customer_email,
        "customer_phone": customer_phone,
    }
    if not clean_title:
        with SessionLocal() as db:
            current_user = db.get(User, user_id)
            users = db.scalars(select(User).where(User.active.is_(True)).order_by(User.name, User.email)).all()
            teams = db.scalars(select(Team).where(Team.active.is_(True)).order_by(Team.name)).all()
        return templates.TemplateResponse(
            request,
            "task_new.html",
            {
                "users": users,
                "current_user": current_user,
                "teams": teams,
                "error": "Indica um assunto para o registo rápido.",
                "form_mode": "quick",
                "form_values": form_values,
                "duplicate_tasks": [],
                "task_sources": TASK_SOURCES,
                "task_types": TASK_TYPES,
                "quick_record_types": QUICK_RECORD_TYPES_BY_WORKSPACE.get(clean_workspace, []),
                "workspaces": TASK_WORKSPACES,
                "task_categories": TASK_CATEGORIES,
                "priorities": PRIORITIES,
            },
            status_code=400,
        )

    with SessionLocal() as db:
        record = QuickRecord(
            workspace=clean_workspace,
            record_type=record_type,
            title=clean_title,
            description=description.strip() or None,
            status="new",
            priority=priority,
            source=source,
            customer_name=customer_name.strip() or None,
            customer_contact=customer_contact.strip() or None,
            customer_email=customer_email.strip().lower() or None,
            customer_phone=customer_phone.strip() or None,
            plate=clean_plate or None,
            station=station.strip() or None,
            created_by_id=user_id,
        )
        db.add(record)
        db.flush()
        record_audit(
            db,
            action="quick_record.create",
            entity_type="quick_record",
            entity_id=record.id,
            detail=f"Registo rápido criado: {record.title}",
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse("/task-board/manage?quick_created=1", status_code=303)


@web_router.post("/task-board", response_class=HTMLResponse)
@web_router.post("/task-board/new", response_class=HTMLResponse)
def task_create(
    request: Request,
    title: str = Form(...),
    task_type: str = Form("operational_task"),
    category: str = Form("operations"),
    subcategory: str = Form(""),
    source: str = Form("manual"),
    priority: str = Form("normal"),
    assigned_to_id: str = Form(""),
    team_id: str = Form(""),
    due_on: str = Form(""),
    customer_name: str = Form(""),
    customer_contact: str = Form(""),
    customer_email: str = Form(""),
    customer_phone: str = Form(""),
    plate: str = Form(""),
    reservation_number: str = Form(""),
    contract_number: str = Form(""),
    station: str = Form(""),
    department: str = Form(""),
    external_source_id: str = Form(""),
    description: str = Form(""),
    confirm_duplicate: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    clean_title = title.strip()
    if not clean_title:
        with SessionLocal() as db:
            current_user = db.get(User, user_id)
            users = db.scalars(select(User).where(User.active.is_(True)).order_by(User.name, User.email)).all()
            teams = db.scalars(select(Team).where(Team.active.is_(True)).order_by(Team.name)).all()
        return templates.TemplateResponse(
            request,
            "task_new.html",
            {
                "users": users,
                "current_user": current_user,
                "teams": teams,
                "error": "Indica um título para a tarefa.",
                "form_mode": "task",
                "form_values": {},
                "duplicate_tasks": [],
                "task_sources": TASK_SOURCES,
                "task_types": TASK_TYPES,
                "quick_record_types": QUICK_RECORD_TYPES_BY_WORKSPACE["operational"],
                "workspaces": TASK_WORKSPACES,
                "task_categories": TASK_CATEGORIES,
                "priorities": PRIORITIES,
            },
            status_code=400,
        )

    with SessionLocal() as db:
        clean_plate = plate.strip().upper().replace(" ", "")
        if source not in TASK_SOURCE_DISPLAY_LABELS:
            source = "manual"
        if task_type not in TASK_TYPE_LABELS:
            task_type = "operational_task"
        if category not in TASK_CATEGORY_LABELS:
            category = "operations"
        assigned_user_id = parse_optional_int(assigned_to_id)
        if assigned_user_id and not db.get(User, assigned_user_id):
            assigned_user_id = None
        assigned_team_id = parse_optional_int(team_id)
        if assigned_team_id and not db.get(Team, assigned_team_id):
            assigned_team_id = None
        assigned_team_id = assigned_team_id or default_team_id(db, "operations")
        if not assigned_user_id and not assigned_team_id:
            return RedirectResponse("/task-board/new?error=missing_destination", status_code=303)
        duplicate_tasks = []
        if clean_plate and confirm_duplicate != "1":
            duplicate_tasks = db.scalars(
                select(Task)
                .where(
                    Task.plate == clean_plate,
                    Task.closed_at.is_(None),
                    ~Task.status.in_(TASK_ARCHIVE_STATUSES),
                )
                .order_by(Task.due_on.is_(None), Task.due_on, Task.id.desc())
                .limit(8)
            ).all()
        if duplicate_tasks:
            users = db.scalars(select(User).where(User.active.is_(True)).order_by(User.name, User.email)).all()
            teams = db.scalars(select(Team).where(Team.active.is_(True)).order_by(Team.name)).all()
            return templates.TemplateResponse(
                request,
                "task_new.html",
                {
                    "users": users,
                    "current_user": db.get(User, user_id),
                    "teams": teams,
                    "error": None,
                    "duplicate_tasks": duplicate_tasks,
                    "form_mode": "quick" if task_type == "request_info" else "task",
                    "form_values": {
                        "title": clean_title,
                        "description": description,
                        "task_type": task_type,
                        "priority": priority,
                        "source": source,
                        "plate": clean_plate,
                        "station": station,
                        "due_on": due_on,
                        "customer_name": customer_name,
                        "customer_contact": customer_contact,
                        "customer_email": customer_email,
                        "customer_phone": customer_phone,
                        "reservation_number": reservation_number,
                        "contract_number": contract_number,
                        "assigned_to_id": assigned_to_id,
                        "team_id": team_id,
                        "department": department,
                        "external_source_id": external_source_id,
                    },
                    "task_status_labels": TASK_STATUS_DISPLAY_LABELS,
                    "task_sources": TASK_SOURCES,
                    "task_types": TASK_TYPES,
                    "quick_record_types": QUICK_RECORD_TYPES_BY_WORKSPACE["operational"],
                    "workspaces": TASK_WORKSPACES,
                    "task_categories": TASK_CATEGORIES,
                    "priorities": PRIORITIES,
                },
                status_code=409,
            )
        task = Task(
            title=clean_title,
            description=description.strip() or None,
            task_type=task_type,
            source=source,
            category=category,
            subcategory=subcategory.strip() or None,
            status="new",
            priority=priority,
            customer_name=customer_name.strip() or None,
            customer_contact=customer_contact.strip() or None,
            customer_email=customer_email.strip().lower() or None,
            customer_phone=customer_phone.strip() or None,
            plate=clean_plate or None,
            reservation_number=reservation_number.strip() or None,
            contract_number=contract_number.strip() or None,
            station=station.strip() or None,
            department=department.strip() or None,
            external_source_id=external_source_id.strip() or None,
            assigned_to_id=assigned_user_id,
            team_id=assigned_team_id,
            created_by_id=user_id,
            due_on=parse_optional_date(due_on),
        )
        db.add(task)
        db.flush()
        db.add(
            TaskHistory(
                task_id=task.id,
                user_id=user_id,
                field_name="status",
                old_value=None,
                new_value="new",
            )
        )
        record_audit(
            db,
            action="task.create",
            entity_type="task",
            entity_id=task.id,
            detail=f"Tarefa criada: {task.title}",
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse("/task-board/manage?created=1", status_code=303)


@web_router.get("/task-board/{task_id}", response_class=HTMLResponse)
def task_detail(
    request: Request,
    task_id: int,
    commented: str | None = None,
    feedback_saved: str | None = None,
    error: str | None = None,
):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        current_user = db.get(User, get_web_user_id(request))
        task = db.get(Task, task_id)
        if not task:
            return RedirectResponse("/task-board/manage", status_code=303)
        comments = db.scalars(
            select(TaskComment).where(TaskComment.task_id == task.id).order_by(TaskComment.created_at.desc())
        ).all()
        history = db.scalars(
            select(TaskHistory).where(TaskHistory.task_id == task.id).order_by(TaskHistory.changed_at.desc())
        ).all()
        linked_vehicle = None
        if task.entity_type == "vehicle" and task.entity_id and task.entity_id.isdigit():
            linked_vehicle = db.get(Vehicle, int(task.entity_id))
        elif task.plate:
            linked_vehicle = db.scalar(select(Vehicle).where(Vehicle.plate == task.plate))
        documents = db.scalars(
            select(Document)
            .where(Document.task_id == task.id)
            .order_by(Document.id.desc())
            .limit(20)
        ).all()
        users = db.scalars(select(User).where(User.active.is_(True)).order_by(User.name, User.email)).all()
        user_by_id = {item.id: item for item in users}
        teams = db.scalars(select(Team).where(Team.active.is_(True)).order_by(Team.name)).all()
        assigned_user = db.get(User, task.assigned_to_id) if task.assigned_to_id else None
        assigned_team = db.get(Team, task.team_id) if task.team_id else None
        return templates.TemplateResponse(
            request,
            "task_detail.html",
            {
                "task": task,
                "comments": comments,
                "history": history,
                "linked_vehicle": linked_vehicle,
                "documents": documents,
                "users": users,
                "current_user": current_user,
                "user_by_id": user_by_id,
                "teams": teams,
                "assigned_user": assigned_user,
                "assigned_team": assigned_team,
                "commented": commented,
                "feedback_saved": feedback_saved,
                "error": "Escolhe uma pessoa responsável ou uma equipa/fila." if error == "missing_destination" else None,
                "task_statuses": TASK_STATUSES,
                "task_status_labels": TASK_STATUS_DISPLAY_LABELS,
                "priorities": PRIORITIES,
                "priority_labels": PRIORITY_DISPLAY_LABELS,
                "task_types": TASK_TYPES,
                "task_type_labels": TASK_TYPE_LABELS,
                "task_source_labels": TASK_SOURCE_DISPLAY_LABELS,
                "task_categories": TASK_CATEGORIES,
                "task_category_labels": TASK_CATEGORY_DISPLAY_LABELS,
                "document_statuses": DOCUMENT_STATUSES,
                "document_status_labels": DOCUMENT_STATUS_LABELS,
                "document_area_labels": DOCUMENT_AREA_LABELS,
                "document_type_labels": DOCUMENT_TYPE_LABELS,
                "document_sources": DOCUMENT_SOURCES,
            },
        )


@web_router.post("/task-board/{task_id}/update", response_class=HTMLResponse)
def task_update(
    request: Request,
    task_id: int,
    status: str = Form("new"),
    priority: str = Form("normal"),
    task_type: str = Form("operational_task"),
    category: str | None = Form(None),
    subcategory: str | None = Form(None),
    assigned_to_id: str | None = Form(None),
    team_id: str | None = Form(None),
    due_on: str = Form(""),
    department: str | None = Form(None),
    station: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    allowed_statuses = {code for code, _ in TASK_STATUSES} | TASK_ARCHIVE_STATUSES
    if status not in allowed_statuses:
        status = "new"
    if task_type not in TASK_TYPE_LABELS:
        task_type = "operational_task"

    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if not task:
            return RedirectResponse("/task-board/manage", status_code=303)
        clean_category = (category.strip() if category else None) or task.category or "operations"
        if clean_category not in TASK_CATEGORY_LABELS:
            clean_category = task.category or "operations"
        clean_subcategory = subcategory.strip() if subcategory is not None else (task.subcategory or "")
        clean_department = department.strip() if department is not None else (task.department or "")

        assigned_user_id = parse_optional_int(assigned_to_id)
        if assigned_user_id and not db.get(User, assigned_user_id):
            assigned_user_id = None
        assigned_team_id = parse_optional_int(team_id)
        if assigned_team_id and not db.get(Team, assigned_team_id):
            assigned_team_id = None
        if not assigned_user_id and not assigned_team_id:
            assigned_user_id = task.assigned_to_id
            assigned_team_id = task.team_id
        parsed_due_on = parse_optional_date(due_on)

        changes = [
            ("status", task.status, status),
            ("priority", task.priority, priority),
            ("task_type", task.task_type, task_type),
            ("category", task.category, clean_category),
            ("subcategory", task.subcategory, clean_subcategory),
            ("assigned_to_id", str(task.assigned_to_id or ""), str(assigned_user_id or "")),
            ("team_id", str(task.team_id or ""), str(assigned_team_id or "")),
            ("due_on", task.due_on.isoformat() if task.due_on else "", parsed_due_on.isoformat() if parsed_due_on else ""),
            ("department", task.department, clean_department),
            ("station", task.station, station.strip()),
        ]

        task.status = status
        task.priority = priority
        task.task_type = task_type
        task.category = clean_category
        task.subcategory = clean_subcategory or None
        task.assigned_to_id = assigned_user_id
        task.team_id = assigned_team_id
        task.due_on = parsed_due_on
        task.department = clean_department or None
        task.station = station.strip() or None
        if status in {"resolved", "closed", "no_action_needed"}:
            task.resolved_at = task.resolved_at or datetime.now(UTC)
        else:
            task.resolved_at = None
        if status in {"closed", "cancelled", "no_action_needed"}:
            task.closed_at = task.closed_at or datetime.now(UTC)
        else:
            task.closed_at = None

        for field_name, old_value, new_value in changes:
            if old_value != new_value:
                db.add(
                    TaskHistory(
                        task_id=task.id,
                        user_id=user_id,
                        field_name=field_name,
                        old_value=old_value or None,
                        new_value=new_value or None,
                    )
                )

        record_audit(
            db,
            action="task.update",
            entity_type="task",
            entity_id=task.id,
            detail=f"Tarefa atualizada: {task.title}",
            user_id=user_id,
        )
        db.commit()

    if status in {"closed", "cancelled", "no_action_needed"}:
        return RedirectResponse("/task-board/manage?closed=1", status_code=303)
    return RedirectResponse(f"/task-board/{task_id}?commented=1", status_code=303)


@web_router.post("/task-board/{task_id}/comments", response_class=HTMLResponse)
def task_add_comment(
    request: Request,
    task_id: int,
    comment: str = Form(...),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    clean_comment = comment.strip()
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if not task:
            return RedirectResponse("/task-board/manage", status_code=303)

        if not clean_comment:
            comments = db.scalars(
                select(TaskComment)
                .where(TaskComment.task_id == task.id)
                .order_by(TaskComment.created_at.desc())
            ).all()
            history = db.scalars(
                select(TaskHistory)
                .where(TaskHistory.task_id == task.id)
                .order_by(TaskHistory.changed_at.desc())
            ).all()
            linked_vehicle = None
            if task.entity_type == "vehicle" and task.entity_id and task.entity_id.isdigit():
                linked_vehicle = db.get(Vehicle, int(task.entity_id))
            elif task.plate:
                linked_vehicle = db.scalar(select(Vehicle).where(Vehicle.plate == task.plate))
            documents = db.scalars(
                select(Document)
                .where(Document.task_id == task.id)
                .order_by(Document.id.desc())
                .limit(20)
            ).all()
            users = db.scalars(select(User).where(User.active.is_(True)).order_by(User.name, User.email)).all()
            user_by_id = {item.id: item for item in users}
            teams = db.scalars(select(Team).where(Team.active.is_(True)).order_by(Team.name)).all()
            assigned_user = db.get(User, task.assigned_to_id) if task.assigned_to_id else None
            assigned_team = db.get(Team, task.team_id) if task.team_id else None
            return templates.TemplateResponse(
                request,
                "task_detail.html",
                {
                    "task": task,
                    "comments": comments,
                    "history": history,
                    "linked_vehicle": linked_vehicle,
                    "documents": documents,
                    "users": users,
                    "user_by_id": user_by_id,
                    "teams": teams,
                    "assigned_user": assigned_user,
                    "assigned_team": assigned_team,
                    "commented": None,
                    "error": "Escreve um comentário antes de gravar.",
                    "task_statuses": TASK_STATUSES,
                    "task_status_labels": TASK_STATUS_DISPLAY_LABELS,
                    "priorities": PRIORITIES,
                    "priority_labels": PRIORITY_DISPLAY_LABELS,
                    "task_types": TASK_TYPES,
                    "task_type_labels": TASK_TYPE_LABELS,
                    "task_source_labels": TASK_SOURCE_DISPLAY_LABELS,
                    "task_categories": TASK_CATEGORIES,
                    "task_category_labels": TASK_CATEGORY_DISPLAY_LABELS,
                    "document_statuses": DOCUMENT_STATUSES,
                    "document_status_labels": DOCUMENT_STATUS_LABELS,
                    "document_area_labels": DOCUMENT_AREA_LABELS,
                    "document_type_labels": DOCUMENT_TYPE_LABELS,
                    "document_sources": DOCUMENT_SOURCES,
                },
                status_code=400,
            )

        db.add(TaskComment(task_id=task.id, user_id=user_id, comment=clean_comment))
        record_audit(
            db,
            action="task.comment.created",
            entity_type="task",
            entity_id=task.id,
            detail=f"Comentário adicionado à tarefa: {task.title}",
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse(f"/task-board/{task_id}?commented=1", status_code=303)


@web_router.post("/task-board/{task_id}/documents", response_class=HTMLResponse)
def task_create_document(
    request: Request,
    task_id: int,
    title: str = Form(""),
    classification: str = Form("general_archive"),
    document_type: str = Form("general_archive"),
    status: str = Form("unclassified"),
    document_date: str = Form(""),
    source: str = Form("email"),
    entry_channel: str = Form(""),
    source_sender: str = Form(""),
    source_subject: str = Form(""),
    url_original: str = Form(""),
    url_archive: str = Form(""),
    supplier_name: str = Form(""),
    notes: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if not task:
            return RedirectResponse("/task-board/manage", status_code=303)
        vehicle = db.scalar(select(Vehicle).where(Vehicle.plate == task.plate)) if task.plate else None
        if classification not in DOCUMENT_AREA_LABELS:
            classification = "general_archive"
        if document_type not in DOCUMENT_TYPE_LABELS:
            document_type = default_document_type_for_area(classification)
        try:
            add_document_record(
                db,
                title=title,
                classification=classification,
                document_type=document_type,
                status=status,
                document_date=parse_optional_date(document_date),
                source=source,
                entry_channel=entry_channel,
                source_sender=source_sender,
                source_subject=source_subject,
                url_original=url_original,
                url_archive=url_archive,
                plate=task.plate or "",
                vehicle_id=vehicle.id if vehicle else None,
                supplier_name=supplier_name,
                customer_name=task.customer_name or "",
                task_id=task.id,
                workshop_process_id=None,
                notes=notes,
                user_id=user_id,
            )
        except ValueError:
            return RedirectResponse(f"/task-board/{task_id}?error=missing_document_fields", status_code=303)
        db.commit()

    return RedirectResponse(f"/task-board/{task_id}?commented=1", status_code=303)


@web_router.post("/task-board/{task_id}/close")
def task_close(request: Request, task_id: int):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if task and not task.closed_at:
            old_status = task.status
            task.status = "closed"
            task.resolved_at = task.resolved_at or datetime.now(UTC)
            task.closed_at = datetime.now(UTC)
            db.add(
                TaskHistory(
                    task_id=task.id,
                    user_id=user_id,
                    field_name="status",
                    old_value=old_status,
                    new_value="closed",
                )
            )
            record_audit(
                db,
                action="task.close",
                entity_type="task",
                entity_id=task.id,
                detail=f"Tarefa fechada: {task.title}",
                user_id=user_id,
            )
            db.commit()

    return RedirectResponse("/task-board/manage?closed=1", status_code=303)


@web_router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@web_router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email.strip().lower()))
        if not user or not user.active or not verify_password(password, user.password_hash):
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "Email ou password invalidos."},
                status_code=401,
            )
        request.session["user_id"] = user.id
        record_audit(
            db,
            action="web.login",
            entity_type="user",
            entity_id=user.id,
            detail=f"Login web de {user.email}",
            user_id=user.id,
        )
        db.commit()
    return RedirectResponse("/", status_code=303)


@web_router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


def get_web_user_id(request: Request) -> int | None:
    user_id = request.session.get("user_id") if hasattr(request, "session") else None
    if not user_id:
        return None
    return int(user_id)


def count_rows(db, model) -> int:
    from sqlalchemy import func

    return db.scalar(select(func.count()).select_from(model)) or 0


def count_open_tasks(db) -> int:
    return db.scalar(select(func.count()).select_from(Task).where(Task.closed_at.is_(None))) or 0


def default_team_id(db, code: str) -> int | None:
    team = db.scalar(select(Team).where(Team.code == code, Team.active.is_(True)))
    return team.id if team else None


def external_client_key(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()[:80]
    if request.client:
        return request.client.host[:80]
    return "unknown"


def external_portal_rate_limit_allows(client_key: str) -> bool:
    now = monotonic()
    window_start = now - EXTERNAL_PORTAL_RATE_LIMIT_WINDOW_SECONDS
    recent_requests = [
        timestamp for timestamp in EXTERNAL_PORTAL_RATE_LIMIT.get(client_key, []) if timestamp >= window_start
    ]
    if len(recent_requests) >= EXTERNAL_PORTAL_RATE_LIMIT_MAX_REQUESTS:
        EXTERNAL_PORTAL_RATE_LIMIT[client_key] = recent_requests
        return False
    recent_requests.append(now)
    EXTERNAL_PORTAL_RATE_LIMIT[client_key] = recent_requests
    return True


def build_external_portal_description(*, message: str, category: str, station: str) -> str:
    lines = [
        "Pedido recebido através do portal externo.",
        f"Tipo de pedido: {EXTERNAL_PORTAL_CATEGORY_LABELS.get(category, category)}",
    ]
    if station.strip():
        lines.append(f"Estação indicada: {station.strip()}")
    lines.extend(["", message.strip()])
    return "\n".join(lines)[:5000]


def default_document_type_for_area(area: str) -> str:
    return {
        "fleet": "general_fleet",
        "finance": "general_finance",
        "rentway_imports": "general_rentway",
        "general_archive": "general_archive",
    }.get(area, "general_archive")


def task_detail_error_message(error: str | None) -> str | None:
    if error == "missing_destination":
        return "Escolhe uma pessoa responsável ou uma equipa/fila."
    if error == "missing_document_fields":
        return "Indica título e pelo menos um link para associar o documento."
    return None


def add_document_record(
    db,
    *,
    title: str,
    classification: str,
    document_type: str,
    status: str,
    document_date: date | None,
    source: str,
    entry_channel: str,
    source_sender: str,
    source_subject: str,
    url_original: str,
    url_archive: str,
    plate: str,
    vehicle_id: int | None,
    supplier_name: str,
    customer_name: str,
    task_id: int | None,
    workshop_process_id: int | None,
    notes: str,
    user_id: int,
) -> Document:
    clean_title = title.strip()
    clean_original_url = url_original.strip()
    clean_archive_url = url_archive.strip()
    if not clean_title or not (clean_original_url or clean_archive_url):
        raise ValueError("title_and_link_required")
    if classification not in DOCUMENT_AREA_LABELS:
        classification = "general_archive"
    if document_type not in DOCUMENT_TYPE_LABELS:
        document_type = default_document_type_for_area(classification)
    if status not in DOCUMENT_STATUS_LABELS:
        status = "unclassified"

    clean_plate = plate.strip().upper()
    archived = status == "archived"
    document = Document(
        title=clean_title,
        document_type=document_type,
        classification=classification,
        status=status,
        source=source.strip() or None,
        entry_channel=entry_channel.strip() or None,
        source_sender=source_sender.strip() or None,
        source_subject=source_subject.strip() or None,
        original_name=clean_title[:255],
        file_name=clean_title[:255],
        file_type=None,
        file_size=None,
        storage_provider="sharepoint",
        storage_path=clean_original_url or clean_archive_url,
        storage_key=clean_original_url or None,
        external_url=clean_archive_url or clean_original_url,
        folder_path=suggest_document_folder_path(classification, document_date, clean_plate),
        vehicle_id=vehicle_id,
        task_id=task_id,
        workshop_process_id=workshop_process_id,
        plate=clean_plate or None,
        customer_name=customer_name.strip() or None,
        supplier_name=supplier_name.strip() or None,
        document_date=document_date,
        uploaded_by_id=user_id,
        archived_by_id=user_id if archived else None,
        archived_at=datetime.now(UTC) if archived else None,
        archived=archived,
    )
    db.add(document)
    db.flush()
    if notes.strip():
        db.add(
            DocumentEvent(
                document_id=document.id,
                action="note",
                old_value=None,
                new_value=notes.strip(),
                user_id=user_id,
            )
        )
    db.add(
        DocumentEvent(
            document_id=document.id,
            action="created",
            old_value=None,
            new_value=f"Documento criado em {DOCUMENT_AREA_LABELS[classification]}",
            user_id=user_id,
        )
    )
    record_audit(
        db,
        action="document.created",
        entity_type="document",
        entity_id=document.id,
        detail=f"Documento registado: {document.title}",
        after_json={
            "classification": classification,
            "document_type": document_type,
            "status": status,
            "folder_path": document.folder_path,
            "task_id": task_id,
            "workshop_process_id": workshop_process_id,
            "vehicle_id": vehicle_id,
        },
        user_id=user_id,
    )
    return document


def suggest_document_folder_path(
    area: str,
    document_date: date | None,
    plate: str | None = None,
) -> str:
    reference_date = document_date or date.today()
    year = f"{reference_date.year:04d}"
    month = f"{reference_date.month:02d}"
    clean_plate = (plate or "").strip().upper()
    if area == "fleet":
        return f"Frota/{clean_plate or 'Sem_Matricula'}"
    if area == "finance":
        return f"Financeiro/{year}/{month}"
    if area == "rentway_imports":
        return f"Rentway_Importacoes/{year}/{month}"
    return f"Arquivo_Geral/{year}/{month}"


def parse_optional_date(value: str | None) -> date | None:
    if not value or not value.strip():
        return None
    return date.fromisoformat(value.strip())


def parse_optional_int(value: str | None) -> int | None:
    if not value or not value.strip():
        return None
    return int(value.strip())


def add_query_flag(url: str, key: str, value: str) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{key}={value}"
