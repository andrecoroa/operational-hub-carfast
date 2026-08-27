from pathlib import Path
import re
from datetime import date, timedelta

from app.models.tasks import Task
from app.models.admin import User
from sqlalchemy import select
import app.web.router as task_router


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = "\n".join(
    (ROOT / path).read_text(encoding="utf-8")
    for path in (
        "app/templates/clean_task_center.html",
        "app/templates/_task_center_approved.html",
    )
)
CSS = (ROOT / "app/static/css/ui-contract-v1.css").read_text(encoding="utf-8")
ROUTER = (ROOT / "app/web/router.py").read_text(encoding="utf-8")


def test_approved_task_center_has_five_independent_keyboard_counters() -> None:
    assert 'class="task-center-approved-metrics"' in TEMPLATE
    assert TEMPLATE.count('data-task-counter=') == 5
    assert '<button' in TEMPLATE


def test_approved_safe_default_and_reset_are_explicit() -> None:
    assert '("mine","Minhas")' in TEMPLATE
    assert 'value="open"' in TEMPLATE
    assert 'name="category"' in TEMPLATE
    assert 'data-task-safe-reset' in TEMPLATE
    assert 'Fechadas excluídas' in TEMPLATE
    assert 'default_task_category' in ROUTER


def test_approved_categories_are_exclusive_and_workspace_is_62_38() -> None:
    for label in ("Documentação", "Oficina", "Sinistros", "Todas"):
        assert label in TEMPLATE
    assert 'role="radiogroup"' in TEMPLATE
    assert 'name="category"' in TEMPLATE
    assert "grid-template-columns:minmax(0,62fr) minmax(360px,38fr)" in CSS


def test_approved_queue_has_exactly_seven_fields_and_42px_rows() -> None:
    expected = ("Prior.", "Referência", "Assunto", "Categoria", "Responsável", "Prazo", "Estado")
    for label in expected:
        assert f"<th>{label}</th>" in TEMPLATE
    assert 'data-task-field-count="7"' in TEMPLATE
    assert "height:42px" in CSS


def test_approved_preview_is_inline_and_has_at_most_four_rbac_actions() -> None:
    assert 'class="task-center-approved-preview ' in TEMPLATE
    assert 'aria-live="polite"' in TEMPLATE
    assert 'data-task-preview-close' in TEMPLATE
    assert 'data-task-preview-action' in TEMPLATE
    assert len(re.findall(r"<button[^>]+data-task-preview-action=", TEMPLATE)) <= 4
    assert "task_update_allowed_by_id" in TEMPLATE
    assert "task_close_allowed_by_id" in TEMPLATE


def test_approved_selection_preserves_return_context() -> None:
    assert 'data-task-row' in TEMPLATE
    assert 'data-return-context' in TEMPLATE
    assert 'history.replaceState' in TEMPLATE
    assert 'sessionStorage' in TEMPLATE


def test_server_side_scope_is_shared_by_list_and_counters() -> None:
    assert "visibility_filter =" in ROUTER
    assert "task_visibility_filter" in ROUTER
    assert "task_counter_metrics" in ROUTER
    assert "counter_base_filters" in ROUTER


def test_initial_default_excludes_closed_and_uses_documentation_focus(
    authenticated_client, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(task_router.settings, "visual_foundation_enabled", True)
    actor = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    db_session.add_all(
        [
            Task(title="Documento ativo aprovado", task_type="operational_task", category="Documentação", status="new", priority="normal", assigned_to_id=actor.id),
            Task(title="Oficina fora do foco inicial", task_type="workshop_task", category="Oficina", status="new", priority="normal"),
            Task(title="Documento fechado excluído", task_type="operational_task", category="Documentação", status="closed", priority="normal"),
        ]
    )
    db_session.commit()

    page = authenticated_client.get("/v2-clean/tasks")

    assert page.status_code == 200
    assert "Documento ativo aprovado" in page.text
    assert "Oficina fora do foco inicial" not in page.text
    assert "Documento fechado excluído" not in page.text
    assert 'value="documentacao" checked' in page.text
    assert 'value="open" selected' in page.text


def test_explicit_closed_and_category_filters_are_server_side(
    authenticated_client, db_session
) -> None:
    db_session.add_all(
        [
            Task(title="Oficina ativa contratual", task_type="workshop_task", category="Oficina", status="new", priority="normal"),
            Task(title="Fechada contratual", task_type="operational_task", category="Documentação", status="closed", priority="normal"),
        ]
    )
    db_session.commit()

    workshop = authenticated_client.get("/v2-clean/tasks?workspace=all&status=open&category=oficina")
    closed = authenticated_client.get("/v2-clean/tasks?workspace=all&status=closed&category=all")

    assert "Oficina ativa contratual" in workshop.text
    assert "Fechada contratual" not in workshop.text
    assert "Fechada contratual" in closed.text


def test_counter_values_reconcile_with_authorized_server_filters(
    authenticated_client, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(task_router.settings, "visual_foundation_enabled", True)
    today = date.today()
    db_session.add_all(
        [
            Task(title="Sem executor", task_type="operational_task", category="Documentação", status="new", priority="normal", due_on=today),
            Task(title="Atrasada", task_type="operational_task", category="Documentação", status="new", priority="high", due_on=today - timedelta(days=1)),
        ]
    )
    db_session.commit()

    page = authenticated_client.get("/v2-clean/tasks?workspace=all&status=open&category=all")
    unassigned = authenticated_client.get("/v2-clean/tasks?workspace=all&status=open&category=all&assignment=unassigned")

    page_count = int(re.search(r'data-task-counter="unassigned"[^>]+aria-label="Ver (\d+) tarefas', page.text).group(1))
    result_count = int(re.search(r'<section class="task-center-approved-queue[^>]*>.*?<header>.*?<span>(\d+) tarefas', unassigned.text, re.S).group(1))
    assert page_count == result_count


def test_last_focus_cookie_and_invalid_category_fail_closed(
    authenticated_client, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(task_router.settings, "visual_foundation_enabled", True)
    actor = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    db_session.add_all(
        [
            Task(title="Oficina lembrada", task_type="workshop_task", category="Oficina", status="new", priority="normal", assigned_to_id=actor.id),
            Task(title="Documento fora do foco lembrado", task_type="operational_task", category="Documentação", status="new", priority="normal", assigned_to_id=actor.id),
        ]
    )
    db_session.commit()
    authenticated_client.cookies.set("carfast_task_category", "oficina")

    remembered = authenticated_client.get("/v2-clean/tasks")
    invalid = authenticated_client.get("/v2-clean/tasks?category=valor-invalido")

    for page in (remembered, invalid):
        assert "Oficina lembrada" in page.text
        assert "Documento fora do foco lembrado" not in page.text
        assert 'value="oficina" checked' in page.text


def test_category_buckets_are_mutually_exclusive_under_adversarial_type(
    authenticated_client, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(task_router.settings, "visual_foundation_enabled", True)
    db_session.add(
        Task(title="Sinistro em fluxo de oficina", task_type="workshop_task", category="Sinistros", status="new", priority="high")
    )
    db_session.commit()

    workshop = authenticated_client.get("/v2-clean/tasks?workspace=all&status=open&category=oficina")
    claims = authenticated_client.get("/v2-clean/tasks?workspace=all&status=open&category=sinistros")

    assert "Sinistro em fluxo de oficina" not in workshop.text
    assert "Sinistro em fluxo de oficina" in claims.text


def test_null_category_uses_authorized_task_type_bucket(
    authenticated_client, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(task_router.settings, "visual_foundation_enabled", True)
    db_session.add_all(
        [
            Task(title="Oficina sem categoria", task_type="workshop_task", category=None, status="new", priority="normal"),
            Task(title="Admin sem categoria", task_type="administration_task", category=None, status="new", priority="normal"),
        ]
    )
    db_session.commit()

    workshop = authenticated_client.get("/v2-clean/tasks?workspace=all&status=open&category=oficina")
    documents = authenticated_client.get("/v2-clean/tasks?workspace=all&status=open&category=documentacao")

    assert "Oficina sem categoria" in workshop.text
    assert "Admin sem categoria" not in workshop.text
    assert "Admin sem categoria" in documents.text
    assert "Oficina sem categoria" not in documents.text


def test_note_action_visibility_uses_distinct_server_respond_scope(
    authenticated_client, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(task_router.settings, "visual_foundation_enabled", True)
    original_scope_check = task_router._task_hierarchy_scope_allows

    def scope_check(db, user_id, task, *, action):
        if action == "respond":
            return False
        return original_scope_check(db, user_id, task, action=action)

    monkeypatch.setattr(task_router, "_task_hierarchy_scope_allows", scope_check)
    db_session.add(
        Task(title="Atualiza sem responder", task_type="operational_task", category="Documentação", status="new", priority="normal")
    )
    db_session.commit()

    page = authenticated_client.get("/v2-clean/tasks?workspace=all&status=open&category=documentacao")
    row = re.search(r'<tr[^>]+data-title="Atualiza sem responder"[^>]+>', page.text).group(0)

    assert 'data-can-update="1"' in row
    assert 'data-can-respond="0"' in row
