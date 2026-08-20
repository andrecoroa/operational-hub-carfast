from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.admin import Permission, Role, RolePermission
from app.models.email import EmailChannel
from app.models.organization import OrganizationalUnit, Team
from app.models.settings import SettingsCatalog, SettingsValue
from app.models.work_hierarchy import (
    ServiceDeskCategoryPolicy,
    ServiceDeskTicketType,
    WorkCategory,
    WorkDepartment,
    WorkQueue,
)
from app.services.management_center import ensure_management_defaults
from app.services.stock import ensure_stock_defaults
from app.services.workshop_configuration import ensure_workshop_configuration_defaults

INITIAL_PERMISSIONS = [
    ("dashboard.read", "Ver dashboard"),
    ("admin.manage", "Gerir administracao"),
    ("settings.manage", "Gerir parametrizacao"),
    ("users.manage", "Gerir utilizadores"),
    ("admin.dashboard.read", "Ver visão geral da administração"),
    ("admin.users.read", "Ver utilizadores"),
    ("admin.users.manage", "Gerir utilizadores e acessos"),
    ("admin.users.credentials", "Definir credenciais temporárias"),
    ("admin.roles.read", "Ver perfis e permissões"),
    ("admin.roles.manage", "Gerir perfis e permissões"),
    ("admin.organization.read", "Ver organização e equipas"),
    ("admin.organization.manage", "Gerir organização e equipas"),
    ("admin.settings.read", "Ver configurações"),
    ("admin.settings.manage", "Gerir configurações"),
    ("admin.workshop_models.read", "Ver modelos da Oficina"),
    ("admin.workshop_models.manage", "Gerir modelos da Oficina"),
    ("admin.workshop_models.publish", "Publicar modelos da Oficina"),
    ("admin.audit.read", "Consultar auditoria do sistema"),
    ("admin.audit.export", "Exportar auditoria do sistema"),
    ("admin.integrations.read", "Ver integrações"),
    ("admin.integrations.manage", "Gerir integrações"),
    ("admin.integrations.credentials", "Gerir credenciais de integrações"),
    ("admin.security.read", "Ver revisão de acessos"),
    ("admin.security.manage", "Gerir controlos de segurança"),
    ("admin.evolution.read", "Consultar Registo de Evolução"),
    ("admin.evolution.manage", "Gerir Registo de Evolução"),
    ("experience.legacy.access", "Abrir versão anterior da CarFast"),
    ("vehicles.read", "Ver viaturas"),
    ("vehicles.write", "Editar viaturas"),
    ("fleet.commerce.manage", "Gerir lista para comercio"),
    ("workshop.read", "Ver oficina"),
    ("workshop.write", "Gerir oficina"),
    ("imports.run", "Executar importacoes"),
    ("imports.approve", "Aprovar importacoes"),
    ("tasks.read", "Ver tarefas"),
    ("tasks.write", "Editar tarefas"),
    ("tasks.operational.read", "Ver centro de tarefas operacional"),
    ("tasks.operational.write", "Gerir centro de tarefas operacional"),
    ("tasks.workshop.read", "Ver centro de tarefas oficina"),
    ("tasks.workshop.write", "Gerir centro de tarefas oficina"),
    ("tasks.audit.read", "Ver centro de tarefas auditoria"),
    ("tasks.audit.write", "Gerir centro de tarefas auditoria"),
    ("tasks.assign.peer", "Atribuir tarefas a utilizadores do mesmo nível"),
    ("tasks.administration.read", "Ver centro de tarefas administração"),
    ("tasks.administration.write", "Gerir centro de tarefas administração"),
    ("tasks.management.read", "Consultar fila de tarefas Gestão"),
    ("tasks.management.create", "Criar tarefas na fila Gestão"),
    ("tasks.management.update", "Alterar tarefas na fila Gestão"),
    ("tasks.management.close", "Fechar e reabrir tarefas na fila Gestão"),
    ("tasks.recurring.manage", "Gerir modelos de tarefas recorrentes"),
    ("service_desk.read", "Consultar tickets do Service Desk"),
    ("service_desk.create", "Criar tickets do Service Desk"),
    ("service_desk.assume", "Assumir tickets elegíveis"),
    ("service_desk.assign", "Atribuir executores elegíveis"),
    ("service_desk.update", "Alterar tickets do Service Desk"),
    ("service_desk.respond", "Responder em tickets do Service Desk"),
    ("service_desk.complete", "Concluir tickets do Service Desk"),
    ("service_desk.sla.manage", "Gerir SLA do Service Desk"),
    ("service_desk.classifications.manage", "Administrar classificações do Service Desk"),
    ("documents.read", "Ver documentos"),
    ("documents.write", "Gerir documentos"),
    ("email.read", "Consultar conversas de email"),
    ("email.triage", "Fazer triagem de email"),
    ("email.reply", "Preparar respostas de email"),
    ("email.approve", "Aprovar e enviar respostas de email"),
    ("email.manage", "Gerir caixas e conversas de email"),
    ("email.assume", "Assumir conversas de email elegíveis"),
    ("email.assign", "Atribuir conversas de email"),
    ("email.sla.manage", "Gerir SLA de email"),
    ("stock.read", "Consultar Stock"),
    ("stock.operate", "Gerir artigos, receções e movimentos operacionais de Stock"),
    ("stock.manage", "Gerir fornecedores, mínimos, acertos e configuração de Stock"),
    ("stock.orders.manage", "Gerir encomendas de Stock"),
    ("stock.inventory.count", "Executar contagens cegas de Stock"),
    ("stock.inventory.confirm", "Confirmar diferenças e acertos de inventário"),
    ("stock.compatibility.manage", "Gerir compatibilidades artigo-viatura"),
    ("stock.conference", "Conferir documentos de Stock"),
    ("management_center.read", "Ver Centro de Gestão e Acompanhamento"),
    ("management_center.write", "Gerir Centro de Gestão e Acompanhamento"),
]

INITIAL_ROLES = [
    ("admin", "Admin"),
    ("user_admin", "Administrador de Utilizadores"),
    ("functional_admin", "Administrador Funcional"),
    ("auditor", "Auditor / Conformidade"),
    ("manager", "Gestor"),
    ("operator", "Operador"),
    ("viewer", "Consulta"),
]

DEFAULT_ROLE_PERMISSIONS = {
    "user_admin": {
        "dashboard.read",
        "admin.dashboard.read",
        "admin.users.read",
        "admin.users.manage",
        "admin.users.credentials",
        "admin.roles.read",
        "admin.roles.manage",
        "admin.organization.read",
        "admin.security.read",
    },
    "functional_admin": {
        "dashboard.read",
        "experience.legacy.access",
        "admin.dashboard.read",
        "admin.settings.read",
        "admin.settings.manage",
        "admin.workshop_models.read",
        "admin.workshop_models.manage",
        "admin.workshop_models.publish",
        "admin.integrations.read",
        "admin.integrations.manage",
        "admin.audit.read",
        "admin.evolution.read",
        "admin.evolution.manage",
        "email.read",
        "email.triage",
        "email.reply",
        "email.approve",
        "email.manage",
        "email.assume",
        "email.assign",
        "email.sla.manage",
        "service_desk.read",
        "service_desk.create",
        "service_desk.assume",
        "service_desk.assign",
        "service_desk.update",
        "service_desk.respond",
        "service_desk.complete",
        "service_desk.sla.manage",
        "service_desk.classifications.manage",
        "stock.read",
        "stock.manage",
        "stock.compatibility.manage",
    },
    "auditor": {
        "dashboard.read",
        "admin.dashboard.read",
        "admin.users.read",
        "admin.roles.read",
        "admin.organization.read",
        "admin.settings.read",
        "admin.workshop_models.read",
        "admin.audit.read",
        "admin.audit.export",
        "admin.integrations.read",
        "admin.security.read",
        "admin.evolution.read",
        "vehicles.read",
        "workshop.read",
        "tasks.read",
        "tasks.audit.read",
        "tasks.audit.write",
        "documents.read",
        "stock.read",
    },
    "manager": {
        "dashboard.read",
        "vehicles.read",
        "vehicles.write",
        "fleet.commerce.manage",
        "workshop.read",
        "workshop.write",
        "imports.run",
        "tasks.read",
        "tasks.write",
        "tasks.operational.read",
        "tasks.operational.write",
        "tasks.workshop.read",
        "tasks.workshop.write",
        "tasks.audit.read",
        "tasks.audit.write",
        "tasks.assign.peer",
        "tasks.administration.read",
        "tasks.administration.write",
        "tasks.management.read",
        "tasks.management.create",
        "tasks.management.update",
        "tasks.management.close",
        "tasks.recurring.manage",
        "service_desk.read",
        "service_desk.create",
        "service_desk.assume",
        "service_desk.assign",
        "service_desk.update",
        "service_desk.respond",
        "service_desk.complete",
        "service_desk.sla.manage",
        "documents.read",
        "documents.write",
        "management_center.read",
        "management_center.write",
        "stock.read",
        "stock.operate",
        "stock.manage",
        "stock.orders.manage",
        "stock.inventory.count",
        "stock.inventory.confirm",
        "stock.compatibility.manage",
        "stock.conference",
    },
    "operator": {
        "dashboard.read",
        "vehicles.read",
        "workshop.read",
        "workshop.write",
        "tasks.read",
        "tasks.write",
        "tasks.operational.read",
        "tasks.operational.write",
        "tasks.workshop.read",
        "tasks.workshop.write",
        "tasks.audit.read",
        "tasks.audit.write",
        "tasks.assign.peer",
        "service_desk.read",
        "service_desk.create",
        "service_desk.assume",
        "service_desk.update",
        "service_desk.respond",
        "service_desk.complete",
        "documents.read",
        "documents.write",
        "management_center.read",
        "management_center.write",
        "stock.read",
        "stock.operate",
        "stock.inventory.count",
        "stock.conference",
    },
    "viewer": {
        "dashboard.read",
        "vehicles.read",
        "workshop.read",
        "tasks.read",
        "tasks.operational.read",
        "tasks.workshop.read",
        "tasks.audit.read",
        "service_desk.read",
        "documents.read",
        "management_center.read",
        "stock.read",
    },
}

INITIAL_UNITS = [
    ("carfast", "CarFast", "business_area", None),
    ("operations", "Operacoes", "business_area", "carfast"),
    ("fleet", "Frota", "workspace_area", "operations"),
    ("workshop", "Oficina", "workspace_area", "operations"),
    ("stock", "Stock", "workspace_area", "operations"),
    ("management", "Gestao", "workspace_area", "carfast"),
    ("administration", "Administracao", "workspace_area", "carfast"),
    ("locations", "Localizacoes", "business_area", "carfast"),
]

INITIAL_TEAMS = [
    ("support", "Suporte", "administration"),
    ("operations", "Operacoes", "operations"),
    ("workshop", "Oficina", "workshop"),
    ("finance", "Financeira", "administration"),
    ("management", "Gestão", "management"),
]

INITIAL_CATALOGS = {
    "vehicle_lifecycle_status": ["active", "for_sale", "sold", "inactive", "written_off"],
    "vehicle_operational_status": [
        "in_contract",
        "free",
        "in_impro",
        "in_preparation",
        "blocked",
        "in_maintenance",
        "reserved",
        "in_transfer",
    ],
    "task_status": [
        "planned",
        "new",
        "in_execution",
        "delegated",
        "waiting",
        "execution_done",
        "ready_validation",
        "closed",
        "cancelled",
        "no_action_needed",
    ],
    "task_priority": ["normal", "high", "urgent"],
    "task_area": ["operations", "workshop", "documents", "fleet", "administration"],
    "task_category": ["request", "information", "invoice", "work_order", "diagnostic", "compliance", "other"],
    "task_subcategory": ["validation", "missing_document", "data_mismatch", "follow_up", "support", "other"],
    "document_type": ["general", "invoice", "report", "photo", "contract"],
    "import_type": ["rentway_fleet", "rentway_contracts", "rentway_impros", "trade_debt"],
}


def seed_initial_data(db: Session) -> None:
    seed_permissions(db)
    seed_roles(db)
    seed_organizational_units(db)
    seed_teams(db)
    seed_catalogs(db)
    seed_work_hierarchy(db)
    seed_service_desk(db)
    seed_email_channels(db)
    ensure_management_defaults(db)
    ensure_workshop_configuration_defaults(db)
    ensure_stock_defaults(db)
    db.commit()


SERVICE_DESK_TICKET_TYPES = (
    ("task", "Tarefa", "Trabalho a executar.", 10),
    ("request", "Pedido", "Pedido de serviço ou informação.", 20),
    ("communication", "Comunicação", "Comunicação a acompanhar.", 30),
    ("internal_help", "Ajuda interna", "Pedido de apoio interno.", 40),
    ("incident", "Incidente", "Interrupção ou anomalia operacional.", 50),
    ("approval", "Aprovação", "Decisão ou aprovação formal.", 60),
)


POSTMARK_INBOUND_LOCAL_PART = "da0078240da719f585b6f441e02a1951"
POSTMARK_INBOUND_DOMAIN = "inbound.postmarkapp.com"


def postmark_inbound_address(mailbox_hash: str) -> str:
    return f"{POSTMARK_INBOUND_LOCAL_PART}+{mailbox_hash}@{POSTMARK_INBOUND_DOMAIN}"


EMAIL_CHANNEL_DEFINITIONS = (
    ("test", "Caixa geral", None, "hub"),
    ("multas", "Multas", "multas@carfast.pt", "multas"),
    ("oficina", "Oficina", "oficina@carfast.pt", "oficina"),
    ("sinistros", "Sinistros", "sinistros@carfast.pt", "sinistros"),
    ("vvp", "VVP", "vvp@carfast.pt", "vvp"),
)


def seed_service_desk(db: Session) -> None:
    ticket_types = {
        item.code: item for item in db.scalars(select(ServiceDeskTicketType)).all()
    }
    for code, name, description, sort_order in SERVICE_DESK_TICKET_TYPES:
        if code not in ticket_types:
            db.add(
                ServiceDeskTicketType(
                    code=code,
                    name=name,
                    description=description,
                    active=True,
                    sort_order=sort_order,
                )
            )
    db.flush()
    policy_category_ids = set(db.scalars(select(ServiceDeskCategoryPolicy.category_id)))
    for category in db.scalars(select(WorkCategory)).all():
        if category.id not in policy_category_ids:
            db.add(
                ServiceDeskCategoryPolicy(
                    category_id=category.id,
                    assignment_mode="manual",
                    warning_minutes=60,
                    pause_on_waiting=True,
                    timezone="Europe/Lisbon",
                    active=True,
                )
            )


def seed_email_channels(db: Session) -> None:
    channels_by_code = {item.code: item for item in db.scalars(select(EmailChannel)).all()}
    hub_address = settings.email_initial_address.strip().lower() or "hub@carfast.pt"
    for code, name, configured_address, inbound_hash in EMAIL_CHANNEL_DEFINITIONS:
        address = configured_address or hub_address
        inbound_forward_address = postmark_inbound_address(inbound_hash)
        existing = channels_by_code.get(code)
        if existing:
            if existing.address != address:
                existing.address = address
            if existing.inbound_hash != inbound_hash:
                existing.inbound_hash = inbound_hash
            if existing.inbound_forward_address != inbound_forward_address:
                existing.inbound_forward_address = inbound_forward_address
            continue
        channel = EmailChannel(
            code=code,
            name=name,
            address=address,
            inbound_hash=inbound_hash,
            inbound_forward_address=inbound_forward_address,
            active=True,
            approval_required=True,
            auto_task_mode="none",
            assignment_mode="manual",
            warning_minutes=60,
            pause_on_waiting=True,
        )
        db.add(channel)
        db.flush()
        channels_by_code[code] = channel


def seed_work_hierarchy(db: Session) -> None:
    queue_definitions = (
        (
            "tasks_support",
            "Tarefas e Suporte",
            "Trabalho operacional, apoio e acompanhamento.",
            10,
        ),
        (
            "administration",
            "Administração",
            "Auditoria e trabalho administrativo reservado.",
            20,
        ),
    )
    queues = {item.code: item for item in db.scalars(select(WorkQueue)).all()}
    for code, name, description, sort_order in queue_definitions:
        if code in queues:
            continue
        queue = WorkQueue(
            code=code,
            name=name,
            description=description,
            active=True,
            sort_order=sort_order,
        )
        db.add(queue)
        db.flush()
        queues[code] = queue

    department_definitions = (
        ("tasks_support", "operations", "Operações", False, 10),
        ("tasks_support", "fleet", "Frota", False, 20),
        ("tasks_support", "hr", "RH", False, 30),
        (
            "tasks_support",
            "management_planning",
            "Gestão e Planeamento",
            False,
            40,
        ),
        ("tasks_support", "other", "Outro", True, 90),
        ("administration", "audit", "Auditoria", False, 10),
        ("administration", "other", "Outro", True, 90),
    )
    existing_departments = {
        (item.queue_id, item.code)
        for item in db.scalars(select(WorkDepartment)).all()
    }
    for queue_code, code, name, requires_description, sort_order in department_definitions:
        queue = queues[queue_code]
        if (queue.id, code) in existing_departments:
            continue
        db.add(
            WorkDepartment(
                queue_id=queue.id,
                code=code,
                name=name,
                requires_description=requires_description,
                active=True,
                sort_order=sort_order,
            )
        )


def seed_permissions(db: Session) -> None:
    for code, name in INITIAL_PERMISSIONS:
        exists = db.scalar(select(Permission).where(Permission.code == code))
        if not exists:
            db.add(Permission(code=code, name=name))


def seed_roles(db: Session) -> None:
    created_role_codes: set[str] = set()
    for code, name in INITIAL_ROLES:
        exists = db.scalar(select(Role).where(Role.code == code))
        if not exists:
            db.add(Role(code=code, name=name, is_system=True))
            created_role_codes.add(code)
    db.flush()

    admin = db.scalar(select(Role).where(Role.code == "admin"))
    if not admin:
        return

    permissions = db.scalars(select(Permission)).all()
    permissions_by_code = {permission.code: permission for permission in permissions}
    for permission in permissions:
        exists = db.scalar(
            select(RolePermission).where(
                RolePermission.role_id == admin.id,
                RolePermission.permission_id == permission.id,
            )
        )
        if not exists:
            db.add(RolePermission(role_id=admin.id, permission_id=permission.id))

    roles_by_code = {role.code: role for role in db.scalars(select(Role)).all()}
    for role_code, permission_codes in DEFAULT_ROLE_PERMISSIONS.items():
        if role_code not in created_role_codes:
            continue
        role = roles_by_code.get(role_code)
        if not role:
            continue
        for permission_code in permission_codes:
            permission = permissions_by_code.get(permission_code)
            if not permission:
                continue
            exists = db.scalar(
                select(RolePermission).where(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == permission.id,
                )
            )
            if not exists:
                db.add(RolePermission(role_id=role.id, permission_id=permission.id))


def seed_organizational_units(db: Session) -> None:
    by_code: dict[str, OrganizationalUnit] = {
        unit.code: unit for unit in db.scalars(select(OrganizationalUnit)).all()
    }
    for code, name, unit_type, parent_code in INITIAL_UNITS:
        if code in by_code:
            continue
        parent = by_code.get(parent_code) if parent_code else None
        unit = OrganizationalUnit(
            code=code,
            name=name,
            unit_type=unit_type,
            parent_id=parent.id if parent else None,
        )
        db.add(unit)
        db.flush()
        by_code[code] = unit


def seed_teams(db: Session) -> None:
    units = {unit.code: unit for unit in db.scalars(select(OrganizationalUnit)).all()}
    teams = {team.code: team for team in db.scalars(select(Team)).all()}
    for code, name, unit_code in INITIAL_TEAMS:
        if code in teams:
            continue
        unit = units.get(unit_code)
        db.add(
            Team(
                code=code,
                name=name,
                organizational_unit_id=unit.id if unit else None,
            )
        )


def seed_catalogs(db: Session) -> None:
    for catalog_code, values in INITIAL_CATALOGS.items():
        catalog = db.scalar(select(SettingsCatalog).where(SettingsCatalog.code == catalog_code))
        if not catalog:
            catalog = SettingsCatalog(code=catalog_code, name=catalog_code.replace("_", " ").title())
            db.add(catalog)
            db.flush()
        for index, value_code in enumerate(values, start=1):
            exists = db.scalar(
                select(SettingsValue).where(
                    SettingsValue.catalog_id == catalog.id,
                    SettingsValue.code == value_code,
                )
            )
            if not exists:
                db.add(
                    SettingsValue(
                        catalog_id=catalog.id,
                        code=value_code,
                        label=value_code.replace("_", " ").title(),
                        sort_order=index,
                        is_system=True,
                    )
                )
