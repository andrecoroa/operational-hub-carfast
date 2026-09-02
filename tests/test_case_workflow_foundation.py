import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.admin import User
from app.models.cases import (
    OperationalCase,
    PhaseDefinition,
    PhaseExecution,
    PhaseInstance,
    ProcessDefinition,
    ProcessDefinitionVersion,
    ProcessInstance,
    ProcessProposalAcceptance,
    WorkflowAuditEvent,
    WorkflowOutboxEvent,
)
from app.models.organization import OrganizationalUnit
from app.models.vehicles import Vehicle
from app.services.case_authorization import can_access_case, can_access_link
from app.services.case_workflow import (
    InvalidTransitionError,
    StaleRevisionError,
    WorkflowError,
    accept_new_proposal_version,
    close_case,
    create_case,
    create_sale_process,
    delegate_phase_to_task,
    ensure_definition_mutable,
    publish_definition_version,
    soft_delete_case,
    transition_phase,
    transition_process,
)
from app.services.users import create_user


def admin_id(db: Session) -> int:
    return db.scalar(select(User.id).where(User.email == "admin.tests@carfast.local"))


def foundation(db: Session):
    unit = db.scalar(select(OrganizationalUnit).limit(1))
    vehicle = Vehicle(plate="BC-58-CU", lifecycle_status="sold")
    definition = ProcessDefinition(key="sale_settlement", name="Venda e liquidação")
    db.add_all([vehicle, definition])
    db.flush()
    version = ProcessDefinitionVersion(definition_id=definition.id, version=1, status="draft")
    db.add(version)
    db.flush()
    db.add_all(
        [
            PhaseDefinition(
                definition_version_id=version.id,
                key="delivery",
                title="Confirmar entrega",
                sort_order=1,
            ),
            PhaseDefinition(
                definition_version_id=version.id,
                key="settlement",
                title="Confirmar liquidação",
                sort_order=2,
                sensitive_validation=True,
            ),
        ]
    )
    publish_definition_version(db, version, admin_id(db))
    case = create_case(
        db, title="Venda do lote", organizational_unit_id=unit.id, actor_id=admin_id(db)
    )
    process = create_sale_process(
        db,
        case=case,
        definition_version=version,
        proposal_logical_id="PROP-28",
        proposal_version=1,
        vehicle_id=vehicle.id,
        title="BC-58-CU",
        actor_id=admin_id(db),
    )
    db.flush()
    phase = db.scalar(
        select(PhaseInstance)
        .where(PhaseInstance.process_id == process.id)
        .order_by(PhaseInstance.id)
    )
    return unit, vehicle, version, case, process, phase


def test_feature_flag_is_off_by_default():
    assert Settings(_env_file=None).cases_v1_enabled is False


def test_definition_is_versioned_and_published_versions_are_immutable(db_session: Session):
    _, _, version, _, _, _ = foundation(db_session)
    with pytest.raises(WorkflowError, match="immutable"):
        ensure_definition_mutable(version)
    with pytest.raises(InvalidTransitionError):
        publish_definition_version(db_session, version, admin_id(db_session))


def test_published_definition_rejects_direct_orm_mutation(db_session: Session):
    _, _, version, _, _, _ = foundation(db_session)
    version.change_note = "tentativa de alteração direta"
    with pytest.raises(ValueError, match="immutable"):
        db_session.flush()


def test_published_definition_rejects_new_phase(db_session: Session):
    _, _, version, _, _, _ = foundation(db_session)
    db_session.add(
        PhaseDefinition(
            definition_version_id=version.id,
            key="late-phase",
            title="Fase tardia",
            sort_order=99,
        )
    )
    with pytest.raises(ValueError, match="immutable"):
        db_session.flush()


def test_sale_creation_is_idempotent_and_versions_are_audited(db_session: Session):
    _, vehicle, version, case, process, _ = foundation(db_session)
    duplicate = create_sale_process(
        db_session,
        case=case,
        definition_version=version,
        proposal_logical_id="PROP-28",
        proposal_version=1,
        vehicle_id=vehicle.id,
        title="duplicado",
        actor_id=admin_id(db_session),
    )
    assert duplicate.id == process.id
    assert db_session.scalars(select(ProcessInstance)).all() == [process]
    accept_new_proposal_version(
        db_session,
        process=process,
        proposal_version=2,
        expected_revision=process.revision,
        actor_id=admin_id(db_session),
        source_reference="accepted-v2",
    )
    db_session.flush()
    assert process.accepted_proposal_version == 2
    assert (
        len(
            db_session.scalars(
                select(ProcessProposalAcceptance).where(
                    ProcessProposalAcceptance.process_id == process.id
                )
            ).all()
        )
        == 2
    )
    process.status = "completed"
    with pytest.raises(WorkflowError, match="cannot be rewritten"):
        accept_new_proposal_version(
            db_session,
            process=process,
            proposal_version=3,
            expected_revision=process.revision,
            actor_id=admin_id(db_session),
        )


def test_invalid_and_stale_transitions_are_rejected(db_session: Session):
    _, _, _, _, process, phase = foundation(db_session)
    with pytest.raises(InvalidTransitionError):
        transition_phase(
            db_session,
            phase_id=phase.id,
            expected_revision=1,
            target="completed",
            actor_id=admin_id(db_session),
        )
    transition_phase(
        db_session,
        phase_id=phase.id,
        expected_revision=1,
        target="active",
        actor_id=admin_id(db_session),
    )
    with pytest.raises(StaleRevisionError):
        transition_phase(
            db_session,
            phase_id=phase.id,
            expected_revision=1,
            target="blocked",
            actor_id=admin_id(db_session),
        )
    with pytest.raises(InvalidTransitionError):
        transition_process(
            db_session,
            process_id=process.id,
            expected_revision=1,
            target="draft",
            actor_id=admin_id(db_session),
        )


def test_delegation_is_idempotent_and_uses_outbox(db_session: Session):
    _, _, _, _, _, phase = foundation(db_session)
    execution = delegate_phase_to_task(
        db_session,
        phase=phase,
        expected_revision=1,
        actor_id=admin_id(db_session),
        idempotency_key="delegate-1",
    )
    same = delegate_phase_to_task(
        db_session,
        phase=phase,
        expected_revision=2,
        actor_id=admin_id(db_session),
        idempotency_key="delegate-1",
    )
    assert same.id == execution.id
    db_session.flush()
    assert db_session.scalar(
        select(WorkflowOutboxEvent).where(WorkflowOutboxEvent.event_key == "create-task:delegate-1")
    )
    with pytest.raises(WorkflowError, match="active execution"):
        delegate_phase_to_task(
            db_session,
            phase=phase,
            expected_revision=2,
            actor_id=admin_id(db_session),
            idempotency_key="delegate-2",
        )


def test_database_constraint_allows_only_one_active_execution(db_session: Session):
    _, _, _, _, _, phase = foundation(db_session)
    db_session.add_all(
        [
            PhaseExecution(
                phase_id=phase.id,
                kind="direct",
                status="active",
                active=True,
                idempotency_key="one",
            ),
            PhaseExecution(
                phase_id=phase.id,
                kind="direct",
                status="active",
                active=True,
                idempotency_key="two",
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_case_close_requires_no_active_process_or_audited_override(db_session: Session):
    _, _, _, case, process, _ = foundation(db_session)
    with pytest.raises(WorkflowError, match="active processes"):
        close_case(db_session, case=case, actor_id=admin_id(db_session))
    with pytest.raises(WorkflowError, match="requires a reason"):
        close_case(db_session, case=case, actor_id=admin_id(db_session), override=True)
    close_case(
        db_session,
        case=case,
        actor_id=admin_id(db_session),
        override=True,
        reason="Decisão autorizada",
    )
    assert case.status == "closed"
    db_session.flush()
    event = db_session.scalar(
        select(WorkflowAuditEvent).where(WorkflowAuditEvent.action == "case.closed.override")
    )
    assert event.reason == "Decisão autorizada"


def test_rbac_is_fail_closed_for_unknown_scope_and_link_type(db_session: Session):
    user = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    _, _, _, case, _, _ = foundation(db_session)
    assert can_access_case(db_session, user, case, "read") is True  # explicit admin capability
    assert can_access_link(db_session, user, case, "read", "unknown", None) is False
    non_scoped = OperationalCase(title="Sem scope", status="open", organizational_unit_id=None)
    db_session.add(non_scoped)
    db_session.flush()
    user.active = False
    assert can_access_case(db_session, user, non_scoped, "read") is False


def test_soft_delete_is_logical_and_audited(db_session: Session):
    _, _, _, case, _, _ = foundation(db_session)
    soft_delete_case(db_session, case, admin_id(db_session), "Retenção operacional")
    db_session.flush()
    assert case.deleted_at is not None
    assert db_session.get(OperationalCase, case.id) is case
    assert (
        db_session.scalar(
            select(WorkflowAuditEvent).where(WorkflowAuditEvent.action == "case.soft_deleted")
        ).reason
        == "Retenção operacional"
    )


def test_mutations_require_an_authorized_actor(db_session: Session):
    _, _, _, case, process, phase = foundation(db_session)
    with pytest.raises(WorkflowError, match="access denied"):
        transition_phase(
            db_session,
            phase_id=phase.id,
            expected_revision=1,
            target="active",
            actor_id=None,
        )
    with pytest.raises(WorkflowError, match="access denied"):
        close_case(
            db_session,
            case=case,
            actor_id=None,
            override=True,
            reason="sem autorização",
        )
    process.status = "completed"
    with pytest.raises(WorkflowError, match="access denied"):
        transition_process(
            db_session,
            process_id=process.id,
            expected_revision=process.revision,
            target="active",
            actor_id=None,
            reason="teste",
        )


def test_sensitive_phase_requires_validation_and_process_requires_complete_phases(
    db_session: Session,
):
    _, _, _, _, process, _ = foundation(db_session)
    phases = db_session.scalars(
        select(PhaseInstance)
        .where(PhaseInstance.process_id == process.id)
        .order_by(PhaseInstance.id)
    ).all()
    sensitive = phases[1]
    transition_phase(
        db_session,
        phase_id=sensitive.id,
        expected_revision=1,
        target="active",
        actor_id=admin_id(db_session),
    )
    with pytest.raises(WorkflowError, match="requires validation"):
        transition_phase(
            db_session,
            phase_id=sensitive.id,
            expected_revision=2,
            target="completed",
            actor_id=admin_id(db_session),
        )
    with pytest.raises(WorkflowError, match="incomplete phases"):
        transition_process(
            db_session,
            process_id=process.id,
            expected_revision=1,
            target="completed",
            actor_id=admin_id(db_session),
        )


def test_idempotency_key_cannot_be_reused_for_another_phase(db_session: Session):
    _, _, _, _, process, phase = foundation(db_session)
    other = db_session.scalars(
        select(PhaseInstance)
        .where(PhaseInstance.process_id == process.id)
        .order_by(PhaseInstance.id)
    ).all()[1]
    delegate_phase_to_task(
        db_session,
        phase=phase,
        expected_revision=1,
        actor_id=admin_id(db_session),
        idempotency_key="same-key",
    )
    with pytest.raises(WorkflowError, match="different intent"):
        delegate_phase_to_task(
            db_session,
            phase=other,
            expected_revision=1,
            actor_id=admin_id(db_session),
            idempotency_key="same-key",
        )


def test_new_proposal_version_uses_optimistic_locking(db_session: Session):
    _, _, _, _, process, _ = foundation(db_session)
    with pytest.raises(StaleRevisionError):
        accept_new_proposal_version(
            db_session,
            process=process,
            proposal_version=2,
            expected_revision=99,
            actor_id=admin_id(db_session),
        )


def test_sensitive_validation_requires_a_different_authorized_user(db_session: Session):
    _, _, _, _, process, _ = foundation(db_session)
    validator = create_user(
        db_session,
        name="Validador T1",
        email="validator-t1@carfast.local",
        password="Temporary123!",
        role_codes=["admin"],
        organizational_unit_codes=["carfast"],
    )
    db_session.flush()
    sensitive = db_session.scalars(
        select(PhaseInstance)
        .where(PhaseInstance.process_id == process.id)
        .order_by(PhaseInstance.id)
    ).all()[1]
    executor_id = admin_id(db_session)
    transition_phase(
        db_session,
        phase_id=sensitive.id,
        expected_revision=1,
        target="active",
        actor_id=executor_id,
    )
    transition_phase(
        db_session,
        phase_id=sensitive.id,
        expected_revision=2,
        target="awaiting_validation",
        actor_id=executor_id,
    )
    with pytest.raises(WorkflowError, match="different validator"):
        transition_phase(
            db_session,
            phase_id=sensitive.id,
            expected_revision=3,
            target="completed",
            actor_id=executor_id,
        )
    transition_phase(
        db_session,
        phase_id=sensitive.id,
        expected_revision=3,
        target="completed",
        actor_id=validator.id,
    )
    db_session.refresh(sensitive)
    assert sensitive.submitted_by_id == executor_id
    assert sensitive.validated_by_id == validator.id
