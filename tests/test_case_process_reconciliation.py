import json
from hashlib import sha256

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.admin import Permission, Role, RolePermission, User
from app.models.case_workflow import (
    OperationalCase,
    ProcessPhaseExecution,
    ProcessPhaseInstance,
    WorkflowAuditEvent,
    WorkflowOutboxEvent,
)
from app.models.organization import OrganizationalUnit
from app.models.task_templates import ProcessInstance, ProcessModel, ProcessModelVersion
from app.models.tasks import Task, TaskCase
from app.models.vehicles import Vehicle
from app.services.case_workflow import (
    WorkflowError,
    close_case,
    create_case,
    create_sale_process,
    delegate_phase_to_task,
    publish_process_model_version,
    transition_phase,
    transition_process,
)
from app.services.users import create_user


def make_actor(db: Session, email: str, *, role_codes: list[str] | None = None) -> User:
    actor = create_user(
        db,
        name=email.split("@")[0],
        email=email,
        password="Temporary123!",
        role_codes=role_codes or ["manager"],
        organizational_unit_codes=["carfast"],
    )
    db.flush()
    role = db.scalar(select(Role).where(Role.code == (role_codes or ["manager"])[0]))
    for code in (
        "cases.read",
        "cases.create",
        "cases.update",
        "cases.close_override",
        "process.instances.delegate",
        "process.instances.validate",
        "process.instances.reopen",
    ):
        permission = db.scalar(select(Permission).where(Permission.code == code))
        if permission is None:
            permission = Permission(code=code, name=code)
            db.add(permission)
            db.flush()
        grant = db.scalar(
            select(RolePermission).where(
                RolePermission.role_id == role.id,
                RolePermission.permission_id == permission.id,
            )
        )
        if grant is None:
            db.add(RolePermission(role_id=role.id, permission_id=permission.id))
    db.flush()
    return actor


def foundation(db: Session):
    actor = make_actor(db, "executor.case-workflow@carfast.local")
    validator = make_actor(db, "validator.case-workflow@carfast.local")
    publisher = make_actor(
        db,
        "publisher.case-workflow@carfast.local",
        role_codes=["functional_admin"],
    )
    unit = db.scalar(select(OrganizationalUnit).where(OrganizationalUnit.code == "carfast"))
    vehicle = Vehicle(plate="T1-RE-01", lifecycle_status="sold")
    model = ProcessModel(code="sale-settlement-t1", name="Venda e liquidação")
    db.add_all([vehicle, model])
    db.flush()
    definition = {
        "phases": [
            {"key": "delivery", "title": "Confirmar entrega"},
            {
                "key": "settlement",
                "title": "Confirmar liquidação",
                "sensitive_validation": True,
            },
        ]
    }
    encoded = json.dumps(definition, sort_keys=True, separators=(",", ":")).encode()
    version = ProcessModelVersion(
        model_id=model.id,
        version=1,
        status="draft",
        definition_json=definition,
        definition_digest=sha256(encoded).hexdigest(),
        created_by_id=actor.id,
    )
    db.add(version)
    db.flush()
    publish_process_model_version(db, version, publisher.id)
    case = create_case(
        db,
        title="Venda lote reconciliada",
        organizational_unit_id=unit.id,
        actor_id=actor.id,
    )
    process = create_sale_process(
        db,
        case=case,
        model_version=version,
        proposal_logical_id="PROP-RECONCILED",
        proposal_version=1,
        vehicle_id=vehicle.id,
        title=vehicle.plate,
        actor_id=actor.id,
    )
    db.flush()
    phases = db.scalars(
        select(ProcessPhaseInstance)
        .where(ProcessPhaseInstance.process_instance_id == process.id)
        .order_by(ProcessPhaseInstance.sort_order)
    ).all()
    return actor, validator, case, process, phases


def test_feature_flag_remains_disabled_and_case_is_canonical():
    assert Settings(_env_file=None).cases_v1_enabled is False
    assert OperationalCase is TaskCase
    assert ProcessInstance.__tablename__ == "process_instances"


def test_reconciled_sale_process_reuses_existing_models(db_session: Session):
    actor, _, case, process, phases = foundation(db_session)
    assert case.workspace == "processes"
    assert process.case_id == case.id
    assert process.source == "sale"
    assert [phase.phase_key for phase in phases] == ["delivery", "settlement"]

    duplicate = create_sale_process(
        db_session,
        case=case,
        model_version=db_session.get(ProcessModelVersion, process.model_version_id),
        proposal_logical_id="PROP-RECONCILED",
        proposal_version=1,
        vehicle_id=process.vehicle_id,
        title="duplicate",
        actor_id=actor.id,
    )
    assert duplicate.id == process.id
    assert db_session.scalar(select(func.count()).select_from(ProcessInstance)) == 1


def test_delegated_phase_creates_real_task_and_outbox(db_session: Session):
    actor, _, case, process, phases = foundation(db_session)
    execution = delegate_phase_to_task(
        db_session,
        phase_id=phases[0].id,
        expected_revision=phases[0].revision,
        actor_id=actor.id,
        idempotency_key="RECONCILED-DELEGATION",
    )
    db_session.flush()
    task = db_session.get(Task, execution.task_id)
    assert task.case_id == case.id
    assert task.process_instance_id == process.id
    assert task.process_step_code == "delivery"
    assert db_session.scalar(select(func.count()).select_from(ProcessPhaseExecution)) == 1
    assert db_session.scalar(select(func.count()).select_from(WorkflowOutboxEvent)) == 1

    same = delegate_phase_to_task(
        db_session,
        phase_id=phases[0].id,
        expected_revision=phases[0].revision,
        actor_id=actor.id,
        idempotency_key="RECONCILED-DELEGATION",
    )
    assert same.id == execution.id


def test_terminal_phase_cannot_be_delegated(db_session: Session):
    actor, _, _, _, phases = foundation(db_session)
    transition_phase(
        db_session,
        phase_id=phases[0].id,
        expected_revision=1,
        target="active",
        actor_id=actor.id,
    )
    transition_phase(
        db_session,
        phase_id=phases[0].id,
        expected_revision=2,
        target="completed",
        actor_id=actor.id,
    )
    with pytest.raises(WorkflowError, match="cannot be delegated"):
        delegate_phase_to_task(
            db_session,
            phase_id=phases[0].id,
            expected_revision=3,
            actor_id=actor.id,
            idempotency_key="TERMINAL-DELEGATION",
        )


def test_sensitive_validation_requires_a_different_manager(db_session: Session):
    actor, validator, _, _, phases = foundation(db_session)
    sensitive = phases[1]
    transition_phase(
        db_session,
        phase_id=sensitive.id,
        expected_revision=1,
        target="active",
        actor_id=actor.id,
    )
    transition_phase(
        db_session,
        phase_id=sensitive.id,
        expected_revision=2,
        target="awaiting_validation",
        actor_id=actor.id,
    )
    with pytest.raises(WorkflowError, match="different validator"):
        transition_phase(
            db_session,
            phase_id=sensitive.id,
            expected_revision=3,
            target="completed",
            actor_id=actor.id,
        )
    transition_phase(
        db_session,
        phase_id=sensitive.id,
        expected_revision=3,
        target="completed",
        actor_id=validator.id,
    )
    assert sensitive.validated_by_id == validator.id


def test_process_and_case_closure_preserve_invariants(db_session: Session):
    actor, validator, case, process, phases = foundation(db_session)
    with pytest.raises(WorkflowError, match="active processes"):
        close_case(db_session, case_id=case.id, actor_id=actor.id)
    transition_phase(
        db_session,
        phase_id=phases[0].id,
        expected_revision=1,
        target="active",
        actor_id=actor.id,
    )
    transition_phase(
        db_session,
        phase_id=phases[0].id,
        expected_revision=2,
        target="completed",
        actor_id=actor.id,
    )
    transition_phase(
        db_session,
        phase_id=phases[1].id,
        expected_revision=1,
        target="active",
        actor_id=actor.id,
    )
    transition_phase(
        db_session,
        phase_id=phases[1].id,
        expected_revision=2,
        target="awaiting_validation",
        actor_id=actor.id,
    )
    transition_phase(
        db_session,
        phase_id=phases[1].id,
        expected_revision=3,
        target="completed",
        actor_id=validator.id,
    )
    transition_process(
        db_session,
        process_id=process.id,
        expected_revision=1,
        target="completed",
        actor_id=actor.id,
    )
    close_case(db_session, case_id=case.id, actor_id=actor.id)
    assert case.status == "closed"
    assert db_session.scalar(select(func.count()).select_from(WorkflowAuditEvent)) > 0


def test_published_process_model_is_immutable_in_orm(db_session: Session):
    _, _, _, process, _ = foundation(db_session)
    version = db_session.get(ProcessModelVersion, process.model_version_id)
    version.definition_json = {"phases": []}
    with pytest.raises(ValueError, match="immutable"):
        db_session.flush()
