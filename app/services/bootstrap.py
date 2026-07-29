from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.admin import Permission, Role, RolePermission
from app.models.organization import OrganizationalUnit, Team
from app.models.settings import SettingsCatalog, SettingsValue
from app.services.management_center import ensure_management_defaults
from app.services.workshop_configuration import ensure_workshop_configuration_defaults

INITIAL_PERMISSIONS = [
    ("dashboard.read", "Ver dashboard"),
    ("admin.manage", "Gerir administracao"),
    ("settings.manage", "Gerir parametrizacao"),
    ("users.manage", "Gerir utilizadores"),
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
    ("tasks.administration.read", "Ver centro de tarefas administração"),
    ("tasks.administration.write", "Gerir centro de tarefas administração"),
    ("tasks.create_recurring", "Criar tarefas recorrentes"),
    ("documents.read", "Ver documentos"),
    ("documents.write", "Gerir documentos"),
    ("management_center.read", "Ver Centro de Gestão e Acompanhamento"),
    ("management_center.write", "Gerir Centro de Gestão e Acompanhamento"),
]

INITIAL_ROLES = [
    ("admin", "Admin"),
    ("manager", "Gestor"),
    ("operator", "Operador"),
    ("viewer", "Consulta"),
]

DEFAULT_ROLE_PERMISSIONS = {
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
        "tasks.administration.read",
        "tasks.administration.write",
        "tasks.create_recurring",
        "documents.read",
        "documents.write",
        "management_center.read",
        "management_center.write",
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
        "documents.read",
        "documents.write",
        "management_center.read",
        "management_center.write",
    },
    "viewer": {
        "dashboard.read",
        "vehicles.read",
        "workshop.read",
        "tasks.read",
        "tasks.operational.read",
        "tasks.workshop.read",
        "documents.read",
        "management_center.read",
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
    "document_type": ["general", "invoice", "report", "photo", "contract"],
    "import_type": ["rentway_fleet", "rentway_contracts", "rentway_impros", "trade_debt"],
}


def seed_initial_data(db: Session) -> None:
    seed_permissions(db)
    seed_roles(db)
    seed_organizational_units(db)
    seed_teams(db)
    seed_catalogs(db)
    ensure_management_defaults(db)
    ensure_workshop_configuration_defaults(db)
    db.commit()


def seed_permissions(db: Session) -> None:
    for code, name in INITIAL_PERMISSIONS:
        exists = db.scalar(select(Permission).where(Permission.code == code))
        if not exists:
            db.add(Permission(code=code, name=name))


def seed_roles(db: Session) -> None:
    for code, name in INITIAL_ROLES:
        exists = db.scalar(select(Role).where(Role.code == code))
        if not exists:
            db.add(Role(code=code, name=name, is_system=True))
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
