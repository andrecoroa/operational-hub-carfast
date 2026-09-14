from pathlib import Path

from sqlalchemy import select

from app.models.admin import User
from app.models.tasks import Task


ROOT = Path(__file__).resolve().parents[1]
DRAWER = (ROOT / "app/templates/_clean_task_drawer.html").read_text(encoding="utf-8")
CENTER = (ROOT / "app/templates/clean_task_center.html").read_text(encoding="utf-8")
APPROVED = (ROOT / "app/templates/_task_center_approved.html").read_text(encoding="utf-8")
CSS = (ROOT / "app/static/css/ui-contract-v1.css").read_text(encoding="utf-8")


def test_task_drawer_keeps_preview_lateral_and_opens_edit_on_full_page() -> None:
    assert 'data-task-drawer-mode="preview"' in DRAWER
    assert 'data-task-drawer-mode="edit"' not in DRAWER
    assert "data-task-full-page-edit" in DRAWER
    assert "/detail{% if return_context %}?return_context=" in DRAWER
    assert "#task-edit" in DRAWER
    assert "showEdit" not in CENTER
    assert "restoredTask = location.hash.match" in CENTER
    assert "openTaskWorkbenchOnDemand(requested || restoredTask)" in CENTER


def test_creation_and_full_page_edit_keep_independent_reference_fields() -> None:
    creation = (ROOT / "app/templates/_task_center_create.html").read_text(
        encoding="utf-8"
    )
    detail = (ROOT / "app/templates/clean_task_detail.html").read_text(encoding="utf-8")
    for name in ("plate", "contract_number", "reservation_number"):
        assert f'name="{name}"' in creation
        assert f'name="{name}"' in detail


def test_task_drawer_actions_reuse_authorized_task_endpoints() -> None:
    for endpoint in (
        "/comments",
        "/transition",
        "/help",
        "/close",
    ):
        assert endpoint in DRAWER
    assert "data-task-drawer-case" in DRAWER
    assert "data-task-drawer-decision" in DRAWER
    assert "data-task-copy-link" in DRAWER
    assert "prefillParams.get('title')" in APPROVED
    assert "prefillParams.get('description')" in APPROVED
    assert "Eliminar tarefa" not in DRAWER


def test_task_drawer_is_lateral_on_desktop_and_full_width_on_mobile() -> None:
    assert ".task-drawer-mount{position:relative;width:min(620px,44vw)" in CSS
    assert "@media(max-width:700px){.task-drawer-mount{width:100vw}" in CSS
    assert ".task-drawer-backdrop{background:transparent}" in CSS


def test_authorized_drawer_response_is_a_fragment(authenticated_client, db_session) -> None:
    user = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    task = Task(
        title="Tarefa no painel lateral",
        description="Contexto verificável do preview.",
        task_type="operational_task",
        status="new",
        priority="normal",
        created_by_id=user.id,
        assigned_to_id=user.id,
    )
    db_session.add(task)
    db_session.commit()

    response = authenticated_client.get(
        f"/v2-clean/tasks/{task.id}/detail?panel=drawer"
    )

    assert response.status_code == 200
    assert "Tarefa no painel lateral" in response.text
    assert 'data-task-drawer-mode="preview"' in response.text
    assert 'data-task-drawer-mode="edit"' not in response.text
    assert 'data-task-full-page-edit' in response.text
    assert "<html" not in response.text.lower()


def test_reference_fields_persist_and_return_in_drawer(
    authenticated_client, db_session
) -> None:
    user = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    task = Task(
        title="Persistir referências no drawer",
        task_type="operational_task",
        status="new",
        priority="normal",
        created_by_id=user.id,
        assigned_to_id=user.id,
    )
    db_session.add(task)
    db_session.commit()

    response = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/update",
        data={
            "title": task.title,
            "description": "Referências preenchidas.",
            "priority": "normal",
            "plate": "AA-12-BB",
            "contract_number": "CONT-2026-42",
            "reservation_number": "RES-9001",
            "return_url": "/v2-clean/tasks",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    db_session.refresh(task)
    assert task.plate == "AA-12-BB"
    assert task.contract_number == "CONT-2026-42"
    assert task.reservation_number == "RES-9001"

    drawer = authenticated_client.get(
        f"/v2-clean/tasks/{task.id}/detail?panel=drawer"
    )
    assert drawer.status_code == 200
    assert "Matrícula · AA-12-BB" in drawer.text
    assert "Contrato · CONT-2026-42" in drawer.text
    assert "Reserva · RES-9001" in drawer.text
