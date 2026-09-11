import json
from hashlib import sha256

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    OrganizationalUnit,
    Permission,
    ProcessBatchRow,
    ProcessBatchRowComment,
    ProcessBatchTaskRow,
    ProcessModel,
    ProcessModelVersion,
    Role,
    RolePermission,
    Task,
    TaskComment,
)
from app.services.process_batches import (
    BATCH_PROCESS_DEFINITION,
    add_batch,
    add_row_comment,
    compose_description,
    create_batch_process,
    create_task_for_rows,
    mirror_task_comment_to_rows,
    update_batch_row,
)
from app.services.users import create_user


def batch_foundation(db: Session):
    actor = create_user(
        db,
        name="batch operator",
        email="batch.operator@carfast.local",
        password="Temporary123!",
        role_codes=["manager"],
        organizational_unit_codes=["carfast"],
    )
    db.flush()
    role = db.scalar(select(Role).where(Role.code == "manager"))
    for code in ("cases.create", "cases.read", "cases.update"):
        permission = db.scalar(select(Permission).where(Permission.code == code))
        if permission is None:
            permission = Permission(code=code, name=code)
            db.add(permission)
            db.flush()
        if not db.scalar(
            select(RolePermission).where(
                RolePermission.role_id == role.id,
                RolePermission.permission_id == permission.id,
            )
        ):
            db.add(RolePermission(role_id=role.id, permission_id=permission.id))
    db.flush()
    unit = db.scalar(select(OrganizationalUnit).where(OrganizationalUnit.code == "carfast"))
    model = ProcessModel(code="batch-data-treatment-test", name="Tratamento em lote")
    db.add(model)
    db.flush()
    encoded = json.dumps(BATCH_PROCESS_DEFINITION, sort_keys=True, separators=(",", ":")).encode()
    version = ProcessModelVersion(
        model_id=model.id,
        version=1,
        status="published",
        definition_json=BATCH_PROCESS_DEFINITION,
        definition_digest=sha256(encoded).hexdigest(),
        created_by_id=actor.id,
    )
    db.add(version)
    db.flush()
    case, process = create_batch_process(
        db,
        model_version=version,
        title="Pendentes de setembro",
        organizational_unit_id=unit.id,
        actor_id=actor.id,
    )
    return actor, case, process


def test_numbered_descriptions_follow_mapping_order_and_skip_blanks():
    source = {"matricula": "AA-21-XZ", "situacao": "", "acao": "Pedir comprovativo"}
    mapping = {"acao": "description_3", "matricula": "description_1", "situacao": "description_2"}
    assert compose_description(source, mapping) == "AA-21-XZ\n\nPedir comprovativo"


def test_batch_process_keeps_rows_unassigned_until_selected(db_session: Session):
    actor, case, process = batch_foundation(db_session)
    batch = add_batch(
        db_session,
        process=process,
        name="pendentes.xlsx",
        mapping={"acao": "title", "matricula": "description_1", "detalhe": "description_2"},
        rows=[
            {
                "acao": "Confirmar pagamento",
                "matricula": "AA-21-XZ",
                "detalhe": "Pedir comprovativo",
            },
            {"acao": "Validar fatura", "matricula": "38-ZP-10", "detalhe": ""},
            {"acao": "Arquivar recibo", "matricula": "74-TR-82", "detalhe": "Após validação"},
        ],
        actor_id=actor.id,
    )
    db_session.flush()
    rows = db_session.scalars(
        select(ProcessBatchRow)
        .where(ProcessBatchRow.batch_id == batch.id)
        .order_by(ProcessBatchRow.row_number)
    ).all()
    task = create_task_for_rows(
        db_session,
        batch_id=batch.id,
        row_ids=[rows[0].id, rows[2].id],
        title="Confirmar e arquivar",
        actor_id=actor.id,
    )
    db_session.flush()
    assert task.case_id == case.id
    assert task.process_instance_id == process.id
    assert db_session.scalars(
        select(ProcessBatchTaskRow).where(ProcessBatchTaskRow.task_id == task.id)
    ).all()
    assert rows[1].status == "ready"
    assert (
        db_session.scalar(
            select(ProcessBatchTaskRow).where(ProcessBatchTaskRow.batch_row_id == rows[1].id)
        )
        is None
    )


def test_task_groups_rows_and_row_comments_are_visible_on_task(db_session: Session):
    actor, _, process = batch_foundation(db_session)
    batch = add_batch(
        db_session,
        process=process,
        name="grupo.xlsx",
        mapping={"acao": "title", "nota": "description_1"},
        rows=[{"acao": "Linha A", "nota": "Detalhe A"}, {"acao": "Linha B", "nota": "Detalhe B"}],
        actor_id=actor.id,
    )
    db_session.flush()
    rows = db_session.scalars(
        select(ProcessBatchRow).where(ProcessBatchRow.batch_id == batch.id)
    ).all()
    task = create_task_for_rows(
        db_session,
        batch_id=batch.id,
        row_ids=[row.id for row in rows],
        title="Tratar grupo",
        actor_id=actor.id,
    )
    comment = add_row_comment(
        db_session, row_id=rows[0].id, actor_id=actor.id, comment="Confirmado"
    )
    db_session.flush()
    assert comment.task_id == task.id
    assert (
        db_session.scalar(select(TaskComment).where(TaskComment.task_id == task.id)).comment
        == "[Linha A] Confirmado"
    )
    update_batch_row(
        db_session,
        row_id=rows[0].id,
        expected_revision=rows[0].revision,
        actor_id=actor.id,
        status="completed",
    )
    update_batch_row(
        db_session,
        row_id=rows[1].id,
        expected_revision=rows[1].revision,
        actor_id=actor.id,
        status="completed",
    )
    db_session.flush()
    assert db_session.get(Task, task.id).status == "completed"
    assert db_session.scalar(
        select(ProcessBatchRowComment).where(ProcessBatchRowComment.task_id == task.id)
    )

    mirrored = mirror_task_comment_to_rows(
        db_session, task_id=task.id, actor_id=actor.id, comment="Comentário geral"
    )
    db_session.flush()
    assert len(mirrored) == 2
    assert {item.batch_row_id for item in mirrored} == {row.id for row in rows}


def test_row_cannot_be_assigned_to_two_tasks(db_session: Session):
    actor, _, process = batch_foundation(db_session)
    batch = add_batch(
        db_session,
        process=process,
        name="single.xlsx",
        mapping={"acao": "title"},
        rows=[{"acao": "Única"}],
        actor_id=actor.id,
    )
    db_session.flush()
    row = db_session.scalar(select(ProcessBatchRow).where(ProcessBatchRow.batch_id == batch.id))
    create_task_for_rows(
        db_session, batch_id=batch.id, row_ids=[row.id], title="Primeira", actor_id=actor.id
    )
    db_session.flush()
    with pytest.raises(ValueError, match="already belong"):
        create_task_for_rows(
            db_session, batch_id=batch.id, row_ids=[row.id], title="Segunda", actor_id=actor.id
        )
