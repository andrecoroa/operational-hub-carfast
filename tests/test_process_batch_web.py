import shutil
from datetime import UTC, datetime

from sqlalchemy import select

import app.web.router as web_router
from app.models import (
    Permission,
    ProcessBatch,
    ProcessBatchRow,
    ProcessModel,
    ProcessModelVersion,
    QuickRecord,
    Role,
    RolePermission,
    Task,
)
from app.services.users import create_user


def _operator(db):
    user = create_user(
        db,
        name="Operador Processos",
        email="processos.web@carfast.local",
        password="Secret123!",
        role_codes=["manager"],
        organizational_unit_codes=["carfast"],
    )
    role = db.scalar(select(Role).where(Role.code == "manager"))
    for code in (
        "management_center.read",
        "management_center.write",
        "tasks.management.create",
        "imports.run",
        "cases.read",
        "cases.create",
        "cases.update",
    ):
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
    model = db.scalar(select(ProcessModel).where(ProcessModel.code == "batch-data-treatment"))
    version = db.scalar(select(ProcessModelVersion).where(ProcessModelVersion.model_id == model.id))
    version.status = "published"
    version.published_at = datetime.now(UTC)
    db.commit()
    return user, version


def _login(client, user):
    assert (
        client.post(
            "/login",
            data={"email": user.email, "password": "Secret123!"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    client.post("/change-notice", data={"next_url": "/v2-clean"}, follow_redirects=False)


def test_process_inbox_converts_to_real_task(client, db_session):
    user, _ = _operator(db_session)
    _login(client, user)
    created = client.post(
        "/v2-clean/processes/inbox",
        data={"title": "Analisar necessidade", "record_type": "need"},
        follow_redirects=False,
    )
    assert created.status_code == 303
    record = db_session.scalar(select(QuickRecord).where(QuickRecord.workspace == "processes"))
    converted = client.post(
        f"/v2-clean/processes/inbox/{record.id}",
        data={
            "title": record.title,
            "record_type": "need",
            "priority": "normal",
            "status": "reviewing",
            "destination": "task",
            "description": "Detalhe progressivo",
        },
        follow_redirects=False,
    )
    assert converted.status_code == 303
    db_session.refresh(record)
    assert record.status == "converted"
    assert db_session.get(Task, record.converted_task_id).description == "Detalhe progressivo"


def test_process_center_only_projects_new_process_surfaces(client, db_session):
    user, _ = _operator(db_session)
    _login(client, user)

    response = client.get("/v2-clean/processes")

    assert response.status_code == 200
    assert "Notas, ideias e necessidades" in response.text
    assert '<details class="clean-panel process-create-panel process-inbox-panel" id="process-inbox">' in response.text
    assert '<details class="clean-panel process-create-panel process-inbox-panel" id="process-inbox" open>' not in response.text
    assert 'aria-controls="process-inbox-content"' in response.text
    assert "Novo tratamento de dados em lote" in response.text
    assert "Fila de processos" not in response.text
    assert "Criar novo processo" not in response.text
    assert "Indicadores do centro de processos" not in response.text


def test_batch_web_flow_uploads_maps_and_keeps_rows_unassigned(
    client, db_session, tmp_path, monkeypatch
):
    user, version = _operator(db_session)
    _login(client, user)
    started = client.post(
        "/v2-clean/processes/batches/start",
        data={"title": "Cobranças setembro", "model_version_id": version.id},
        follow_redirects=False,
    )
    assert started.status_code == 303
    detail_url = started.headers["location"]
    assert client.get(detail_url).status_code == 200

    stored = tmp_path / "lote.csv"

    def store(source, _name):
        shutil.copyfile(source, stored)
        return stored

    monkeypatch.setattr(web_router, "store_task_bulk_upload", store)
    uploaded = client.post(
        f"{detail_url}/upload",
        files={
            "file": (
                "lote.csv",
                "Acao,Matricula,Detalhe\nConfirmar pagamento,AA-21-XZ,Pedir comprovativo\n"
                "Validar fatura,38-ZP-10,Conferir valor\n",
                "text/csv",
            )
        },
    )
    assert uploaded.status_code == 200
    assert "Mapear campos do lote" in uploaded.text

    mapped = client.post(
        f"{detail_url}/map",
        data={
            "column_0": "title",
            "column_1": "description_1",
            "column_2": "description_2",
        },
        follow_redirects=False,
    )
    assert mapped.status_code == 303
    batch = db_session.scalar(select(ProcessBatch))
    rows = list(
        db_session.scalars(
            select(ProcessBatchRow)
            .where(ProcessBatchRow.batch_id == batch.id)
            .order_by(ProcessBatchRow.row_number)
        )
    )
    assert [row.title for row in rows] == ["Confirmar pagamento", "Validar fatura"]
    assert rows[0].description == "AA-21-XZ\n\nPedir comprovativo"
    assert all(row.status == "ready" for row in rows)
    assert db_session.scalar(select(Task).where(Task.entity_type == "process_batch")) is None
