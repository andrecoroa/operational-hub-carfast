from copy import deepcopy

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.models.admin import Permission, Role, RolePermission, User, UserRole
from app.models.audit import AuditLog
from app.models.organization import OrganizationalUnit, UserOrganizationalUnit
from app.models.task_templates import ProcessModel, ProcessModelVersion, TaskTemplate, TaskTemplateVersion
from app.models.tasks import Task
from app.models.vehicles import Vehicle
from app.models.documents import Document
from app.models.work_hierarchy import RoleWorkScope, WorkCategory, WorkDepartment, WorkQueue, WorkSubcategory
from app.services.task_templates import (
    CreationDenied,
    TaskCreationCapabilityResolver,
    USED_VEHICLE_SALE_DEFINITION,
    canonical_snapshot,
    complete_process_checkpoint,
    create_task_for_process,
    create_task_from_template,
    advance_process_phase,
    start_process,
    workshop_parity_supported,
)
from app.services.bootstrap import seed_permissions, seed_process_model_library, seed_roles
from app.api.routes.task_templates import TemplateTaskRequest, create_template_task


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def grant(db, user, role_code, permissions, *, scope=None):
    role = Role(code=role_code, name=role_code, active=True)
    db.add(role); db.flush(); db.add(UserRole(user_id=user.id, role_id=role.id))
    for code in permissions:
        permission = Permission(code=code, name=code); db.add(permission); db.flush(); db.add(RolePermission(role_id=role.id, permission_id=permission.id))
    if scope:
        db.add(RoleWorkScope(role_id=role.id, queue_id=scope[0], department_id=scope[1], category_id=scope[2], subcategory_id=scope[3], can_read=True, can_create=scope[4]))
    db.flush(); return role


def setup_template(db, *, permission="tasks.operational.create", can_create=True):
    user = User(name="Executor", email=f"executor-{permission}@test.invalid", password_hash="x", active=True); db.add(user); db.flush()
    queue=WorkQueue(code="ops",name="Operação",active=True);db.add(queue);db.flush()
    department=WorkDepartment(queue_id=queue.id,code="desk",name="Desk",active=True);db.add(department);db.flush()
    category=WorkCategory(department_id=department.id,code="docs",name="Documentos",active=True);db.add(category);db.flush()
    sub=WorkSubcategory(category_id=category.id,code="missing",name="Em falta",active=True);db.add(sub);db.flush()
    grant(db,user,"executor",{permission,"tasks.read","tasks.manage"},scope=(queue.id,department.id,category.id,sub.id,can_create))
    definition={"task_type":"operational_task","required_create_permissions":[permission],"allowed_role_codes":["executor"],"classification":{"queue_id":queue.id,"department_id":department.id,"category_id":category.id,"subcategory_id":sub.id},"defaults":{"title":"Pedir informação","priority":"normal","due_offset_days":2},"checklist":["Confirmar contexto"],"conditional_fields":[],"documents":{"selection":"explicit"}}
    snapshot,digest=canonical_snapshot(definition); template=TaskTemplate(code="request_information",name="Pedir informação",created_by_id=user.id);db.add(template);db.flush();version=TaskTemplateVersion(template_id=template.id,version=1,status="published",definition_json=snapshot,definition_digest=digest,created_by_id=user.id);db.add(version);db.flush();return user,version,category


def test_read_or_manage_never_implies_create(db):
    user,version,_=setup_template(db,permission="tasks.explicit.create",can_create=False)
    with pytest.raises(CreationDenied,match="scope_create_denied"):
        TaskCreationCapabilityResolver(db).require(user,version)


def test_options_and_post_share_fail_closed_resolver(db):
    user,version,category=setup_template(db)
    assert TaskCreationCapabilityResolver(db).options(user)[0].allowed is True
    category.active=False;db.flush()
    assert TaskCreationCapabilityResolver(db).options(user)[0].reason=="inactive_classification"
    with pytest.raises(CreationDenied,match="inactive_classification"):
        create_task_from_template(db,user=user,version_id=version.id)


def test_tampered_ids_and_unknown_overrides_roll_back_atomically(db):
    user,version,_=setup_template(db)
    with pytest.raises(CreationDenied,match="override_not_allowed"):
        create_task_from_template(db,user=user,version_id=version.id,overrides={"work_category_id":999})
    assert db.scalar(select(Task)) is None


def test_created_task_keeps_immutable_version_snapshot(db):
    user,version,_=setup_template(db)
    task=create_task_from_template(db,user=user,version_id=version.id,overrides={"title":"Pedido específico"});db.flush()
    before=deepcopy(task.task_template_snapshot_json); version.definition_json["defaults"]["title"]="Alterado";db.flush()
    assert task.title=="Pedido específico" and task.task_template_snapshot_json==before
    assert task.task_template_snapshot_digest==version.definition_digest


def test_start_process_is_distinct_and_manager_requires_audited_justification(db):
    user=User(name="Gestor",email="manager@test.invalid",password_hash="x",active=True);db.add(user);db.flush();grant(db,user,"manager",{"vehicle_sales.process.create","vehicles.read","documents.read"})
    unit=OrganizationalUnit(code="lisbon",name="Lisboa",unit_type="location",active=True);db.add(unit);db.flush();db.add(UserOrganizationalUnit(user_id=user.id,organizational_unit_id=unit.id));db.flush()
    vehicle=Vehicle(plate="42-ZX-19",active=True,current_location_id=unit.id);db.add(vehicle);db.flush()
    document=Document(title="Documento venda",original_name="doc.pdf",file_name="opaque.pdf",storage_provider="local",storage_path="opaque",status="validated",vehicle_id=vehicle.id,archived=False);db.add(document);db.flush()
    model=ProcessModel(code="used_vehicle_sale_to_merchant",name="Venda de Viatura Usada a Comerciante",created_by_id=user.id);db.add(model);db.flush();snapshot,digest=canonical_snapshot(USED_VEHICLE_SALE_DEFINITION);version=ProcessModelVersion(model_id=model.id,version=1,status="published",definition_json=snapshot,definition_digest=digest,created_by_id=user.id);db.add(version);db.flush()
    context={"title":"Venda 42-ZX-19","organizational_unit_code":"lisbon","selection_mode":"selected","vehicle_ids":[vehicle.id],"document_ids":[document.id]}
    with pytest.raises(CreationDenied,match="manager_justification_required"):
        start_process(db,user=user,model_version_id=version.id,context=context)
    process=start_process(db,user=user,model_version_id=version.id,context=context,justification="Exceção operacional acompanhada")
    assert process.title=="Venda 42-ZX-19" and process.manager_exception_justification
    assert db.scalar(select(Task)) is None
    with pytest.raises(CreationDenied, match="process_source_not_allowed"):
        start_process(db, user=user, model_version_id=version.id, context=context, source="import", justification="Revisão")


def test_all_required_create_permissions_are_mandatory(db):
    user, version, _ = setup_template(db, permission="tasks.explicit.create")
    definition = deepcopy(version.definition_json)
    definition["required_create_permissions"] = ["tasks.explicit.create", "documents.read"]
    version.definition_json, version.definition_digest = canonical_snapshot(definition)
    with pytest.raises(CreationDenied, match="create_permission_required"):
        TaskCreationCapabilityResolver(db).require(user, version)


def test_used_vehicle_sale_contract_is_fail_closed_for_documents_and_portal():
    assert USED_VEHICLE_SALE_DEFINITION["selection"]["documents"]=="explicit_only"
    assert [phase["code"] for phase in USED_VEHICLE_SALE_DEFINITION["phases"]] == [
        "preparation", "operational_validation", "documentation_delivery", "financial", "close"
    ]
    assert "operational_validation" in USED_VEHICLE_SALE_DEFINITION["phases"][3]["depends_on"]
    assert USED_VEHICLE_SALE_DEFINITION["external_effects"]["portal"]["enabled"] is False
    assert USED_VEHICLE_SALE_DEFINITION["external_effects"]["email"]["human_review_required"] is True


def test_process_start_requires_every_declared_permission(db):
    user=User(name="Executor",email="strict-process@test.invalid",password_hash="x",active=True);db.add(user);db.flush();grant(db,user,"operator",{"vehicle_sales.process.create","vehicles.read","documents.read"})
    unit=OrganizationalUnit(code="strict",name="Strict",unit_type="location",active=True);db.add(unit);db.flush();db.add(UserOrganizationalUnit(user_id=user.id,organizational_unit_id=unit.id));vehicle=Vehicle(plate="STRICT-1",active=True,current_location_id=unit.id);db.add(vehicle);db.flush()
    definition=deepcopy(USED_VEHICLE_SALE_DEFINITION);definition["required_start_permissions"]=["vehicle_sales.process.create","second.explicit.permission"]
    model=ProcessModel(code="strict_sale",name="Venda");db.add(model);db.flush();snapshot,digest=canonical_snapshot(definition);version=ProcessModelVersion(model_id=model.id,version=1,status="published",definition_json=snapshot,definition_digest=digest);db.add(version);db.flush()
    with pytest.raises(CreationDenied,match="process_start_permission_required"):
        start_process(db,user=user,model_version_id=version.id,context={"organizational_unit_code":"strict","selection_mode":"selected","vehicle_ids":[vehicle.id],"document_ids":[]})


def test_existing_workshop_can_be_represented_without_migration():
    representation={"phases":[],"tasks":[],"dependencies":[],"required_gates":[],"documents":{},"sla":{},"responsibility_rules":{}}
    assert workshop_parity_supported(representation)


def test_bootstrap_admin_does_not_gain_operational_process_creation(db):
    seed_permissions(db); seed_roles(db); db.flush()
    admin = db.scalar(select(Role).where(Role.code == "admin"))
    granted = set(db.scalars(select(Permission.code).join(RolePermission, RolePermission.permission_id == Permission.id).where(RolePermission.role_id == admin.id)))
    assert "tasks.templates.manage" in granted
    assert "process.models.manage" in granted
    assert "process.instances.start" not in granted
    assert "vehicle_sales.process.create" not in granted


def test_sale_process_library_seed_is_idempotent_and_inert(db):
    seed_process_model_library(db); db.flush()
    seed_process_model_library(db); db.flush()
    assert len(db.scalars(select(ProcessModel)).all()) == 1
    versions = db.scalars(select(ProcessModelVersion)).all()
    assert len(versions) == 1 and versions[0].status == "draft"
    assert db.scalars(select(Task)).all() == []


def test_process_task_requires_instance_scope_current_phase_and_model_mapping(db):
    user, version, _ = setup_template(db, permission="tasks.explicit.create")
    template = db.get(TaskTemplate, version.template_id)
    template.code = "select_vehicles"
    unit = OrganizationalUnit(code="north", name="Norte", unit_type="location", active=True)
    db.add(unit); db.flush(); db.add(UserOrganizationalUnit(user_id=user.id, organizational_unit_id=unit.id))
    vehicle=Vehicle(plate="NORTH-1",active=True,current_location_id=unit.id);db.add(vehicle);db.flush()
    for code in ("vehicle_sales.process.create", "vehicles.read", "documents.read"):
        permission = Permission(code=code, name=code); db.add(permission); db.flush()
        role_id = db.scalar(select(UserRole.role_id).where(UserRole.user_id == user.id))
        db.add(RolePermission(role_id=role_id, permission_id=permission.id))
    model = ProcessModel(code="sale", name="Venda"); db.add(model); db.flush()
    definition = deepcopy(USED_VEHICLE_SALE_DEFINITION)
    snapshot, digest = canonical_snapshot(definition)
    model_version = ProcessModelVersion(model_id=model.id, version=1, status="published", definition_json=snapshot, definition_digest=digest)
    db.add(model_version); db.flush()
    instance = start_process(db, user=user, model_version_id=model_version.id, context={"organizational_unit_code":"north","selection_mode":"selected","vehicle_ids":[vehicle.id],"document_ids":[]})
    task = create_task_for_process(db, user=user, instance=instance, template_version_id=version.id, process_step_code="preparation")
    assert task.process_instance_id == instance.id and task.process_step_code == "preparation"
    with pytest.raises(CreationDenied, match="process_phase_not_actionable"):
        create_task_for_process(db, user=user, instance=instance, template_version_id=version.id, process_step_code="financial")
    with pytest.raises(CreationDenied, match="process_phase_incomplete"):
        advance_process_phase(db, user=user, instance=instance)
    for checkpoint in ("select_vehicles", "select_documents", "prepare_merchant_ticket", "explicit_documents_selected"):
        complete_process_checkpoint(db, user=user, instance=instance, checkpoint_code=checkpoint)
    advance_process_phase(db, user=user, instance=instance)
    assert instance.context_json["current_phase_code"] == "operational_validation"
    instance.organizational_unit_code = "south"
    with pytest.raises(CreationDenied, match="process_instance_scope_denied"):
        create_task_for_process(db, user=user, instance=instance, template_version_id=version.id, process_step_code="preparation")


def test_api_denial_persists_sanitized_audit_and_no_task(db):
    user, version, category = setup_template(db)
    category.active = False; db.commit()
    with pytest.raises(HTTPException) as exc:
        create_template_task(version.id, TemplateTaskRequest(overrides={"title":"Bloqueada"}), db, user)
    assert exc.value.status_code == 403
    assert db.scalar(select(Task)) is None
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "task.template_create_denied"))
    assert audit and audit.detail == "inactive_classification" and audit.after_json is None
