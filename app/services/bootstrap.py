from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.admin import Permission, Role, RolePermission
from app.models.organization import OrganizationalUnit
from app.models.settings import SettingsCatalog, SettingsValue

INITIAL_PERMISSIONS = [
    ("admin.manage", "Gerir administracao"),
    ("settings.manage", "Gerir parametrizacao"),
    ("users.manage", "Gerir utilizadores"),
    ("vehicles.read", "Ver viaturas"),
    ("vehicles.write", "Editar viaturas"),
    ("imports.run", "Executar importacoes"),
    ("imports.approve", "Aprovar importacoes"),
    ("tasks.read", "Ver tarefas"),
    ("tasks.write", "Editar tarefas"),
    ("documents.write", "Gerir documentos"),
    ("workshop.read", "Ver oficina"),
    ("workshop.write", "Editar oficina"),
    ("workshop.validate", "Validar oficina"),
]

INITIAL_ROLES = [
    ("admin", "Admin"),
    ("manager", "Gestor"),
    ("operator", "Operador"),
    ("viewer", "Consulta"),
]

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
    "task_status": ["new", "in_progress", "waiting", "done", "cancelled"],
    "task_priority": ["low", "normal", "high", "urgent"],
    "document_type": ["general", "invoice", "report", "photo", "contract"],
    "import_type": ["rentway_fleet", "rentway_contracts", "rentway_impros"],
    "workshop_process_type": ["workshop_phased"],
    "workshop_process_status": [
        "scheduled",
        "reception_pending",
        "in_progress",
        "pending_review",
        "completed",
        "completed_with_pending_items",
        "cancelled",
    ],
    "workshop_creation_mode": ["immediate_entry", "appointment"],
    "workshop_report_origin": ["stellantis_machine", "autel", "other"],
    "workshop_report_status": [
        "pending",
        "added",
        "read_automatically",
        "pending_validation",
        "validated",
        "corrected_manually",
        "unable_to_read",
        "not_applicable",
    ],
}


def seed_initial_data(db: Session) -> None:
    seed_permissions(db)
    seed_roles(db)
    seed_organizational_units(db)
    seed_catalogs(db)
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
    for permission in permissions:
        exists = db.scalar(
            select(RolePermission).where(
                RolePermission.role_id == admin.id,
                RolePermission.permission_id == permission.id,
            )
        )
        if not exists:
            db.add(RolePermission(role_id=admin.id, permission_id=permission.id))


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


def seed_catalogs(db: Session) -> None:
    for catalog_code, values in INITIAL_CATALOGS.items():
        catalog = db.scalar(select(SettingsCatalog).where(SettingsCatalog.code == catalog_code))
        if not catalog:
            catalog = SettingsCatalog(
                code=catalog_code,
                name=catalog_code.replace("_", " ").title(),
            )
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
