from pathlib import Path
import json
import re
from datetime import date, timedelta

from app.models.tasks import Task
from app.models.admin import User
from sqlalchemy import event, select
import app.web.router as task_router


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = "\n".join(
    (ROOT / path).read_text(encoding="utf-8")
    for path in (
        "app/templates/clean_task_center.html",
        "app/templates/_task_center_approved.html",
        "app/templates/_task_center_create.html",
        "app/templates/_task_classification_fields.html",
    )
)
CSS = (ROOT / "app/static/css/ui-contract-v1.css").read_text(encoding="utf-8")
ROUTER = (ROOT / "app/web/router.py").read_text(encoding="utf-8")
DETAIL = (ROOT / "app/templates/clean_task_detail.html").read_text(encoding="utf-8")


def test_approved_task_center_has_four_contractual_keyboard_counters() -> None:
    assert 'class="task-center-approved-metrics"' in TEMPLATE
    assert TEMPLATE.count('data-task-counter=') == 4
    for label in ("Por tratar", "Por assumir", "Atrasadas", "Em risco"):
        assert label in TEMPLATE
    assert '<button' in TEMPLATE


def test_recurrence_remains_a_permission_scoped_secondary_action() -> None:
    assert "can_manage_recurrence" in TEMPLATE
    assert 'href="/v2-clean/tasks/recurring">Recorrentes</a>' in TEMPLATE
    assert '@web_router.get("/v2-clean/tasks/recurring"' in ROUTER
    assert 'aria-label="Área do Centro de Tarefas"' in TEMPLATE
    assert 'href="/v2-clean/tasks" aria-current="page">Tarefas</a>' in TEMPLATE


def test_approved_safe_default_and_reset_are_explicit() -> None:
    assert '("mine","Minhas")' in TEMPLATE
    assert 'task_filter_status_labels' in ROUTER
    assert 'value="{{ code }}"' in TEMPLATE
    assert 'name="category"' in TEMPLATE
    assert 'data-task-safe-reset' in TEMPLATE
    assert 'Fechadas excluídas' in TEMPLATE
    assert 'default_task_category' in ROUTER


def test_primary_filters_use_operational_views_and_persisted_queues() -> None:
    for label in ("Minhas", "Por assumir", "Da equipa"):
        assert label in TEMPLATE
    assert 'aria-label="Vista de trabalho"' in TEMPLATE
    assert 'select name="task_scope_view" data-task-scope' in TEMPLATE
    assert "form.querySelector('[data-task-scope]')" in TEMPLATE
    assert 'data-task-queue' in TEMPLATE
    assert 'name="category" value="all"' in TEMPLATE
    assert 'Categoria de foco' not in TEMPLATE
    assert "grid-template-columns:minmax(0,62fr) minmax(360px,38fr)" in CSS


def test_creation_offers_case_in_the_same_progressive_selector() -> None:
    assert "data-create-case" in TEMPLATE
    assert "createDialog.close();openCaseFlow('new')" in TEMPLATE
    assert "Criar e abrir tarefa" in TEMPLATE


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
    assert "data-preview-origin" not in TEMPLATE
    assert "data-preview-relation" in TEMPLATE
    assert "task-preview-description" in TEMPLATE
    assert "data-preview-waiting" in TEMPLATE
    assert "data-preview-support" in TEMPLATE
    assert "data-task-more-toggle" in TEMPLATE
    assert "function mountPreview(row,groupButton=null)" in TEMPLATE
    assert "row.insertAdjacentElement('afterend',inlinePreviewRow)" in TEMPLATE
    assert "groupButton.insertAdjacentElement('afterend',preview)" in TEMPLATE


def test_inline_preview_toggles_single_selection_and_restores_keyboard_focus() -> None:
    assert "const toggleSelection=(row,groupButton=null)" in TEMPLATE
    assert "selectedRow===row&&!preview.classList.contains('is-empty')" in TEMPLATE
    assert "selectedTrigger=groupButton||row" in TEMPLATE
    assert "selectedRow=null;selectedTrigger=null" in TEMPLATE
    assert "trigger?.isConnected)trigger.focus()" in TEMPLATE
    assert "event.key!=='Escape'" in TEMPLATE
    assert "document.querySelector('dialog[open]')" in TEMPLATE
    assert "row.addEventListener('click',()=>toggleSelection(row))" in TEMPLATE
    assert "if(row)toggleSelection(row,button)" in TEMPLATE
    assert "groupButtons.find(button=>button.dataset.groupTask===id)" in TEMPLATE
    assert "if(!grouped||groupButton)select(row,groupButton||null)" in TEMPLATE
    assert ".task-center-approved-workspace{display:block" in CSS


def test_grouped_reload_restores_preview_only_under_a_visible_group_trigger() -> None:
    assert "const group=groupButton.closest('details.task-group');if(group)group.open=true" in TEMPLATE
    assert "const grouped=document.querySelector('[data-task-groups]')" in TEMPLATE
    assert "if(!grouped||groupButton)select(row,groupButton||null)" in TEMPLATE
    assert "groupButton.insertAdjacentElement('afterend',preview)" in TEMPLATE


def test_support_targets_are_scoped_server_side_and_not_globally_rendered() -> None:
    support_dialog = TEMPLATE[TEMPLATE.index("data-task-support-dialog") :]
    support_dialog = support_dialog[: support_dialog.index("{% include")]
    assert "task_support_available_by_id|tojson" in TEMPLATE
    assert "/support-targets`" in TEMPLATE
    assert 'def clean_task_support_targets(' in ROUTER
    assert "for user in all_users" not in support_dialog
    assert "for team in teams" not in support_dialog
    assert "target.replaceChildren" in TEMPLATE


def test_support_targets_fail_closed_without_update_permission(
    authenticated_client, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(task_router.settings, "visual_foundation_enabled", True)
    original_scope_check = task_router._task_hierarchy_scope_allows

    def scope_check(db, user_id, task, *, action):
        if action == "update":
            return False
        return original_scope_check(db, user_id, task, action=action)

    monkeypatch.setattr(task_router, "_task_hierarchy_scope_allows", scope_check)
    task = Task(
        title="Visível sem suporte autorizado",
        task_type="operational_task",
        category="Documentação",
        status="new",
        priority="normal",
    )
    db_session.add(task)
    db_session.commit()
    actor = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    task.created_by_id = actor.id
    db_session.commit()

    page = authenticated_client.get(
        "/v2-clean/tasks?workspace=mine&mine_kind=all&status=open&category=documentacao"
    )

    assert page.status_code == 200
    assert 'data-title="Visível sem suporte autorizado"' in page.text
    row = re.search(
        r'<tr[^>]+data-title="Visível sem suporte autorizado"[^>]+>', page.text
    ).group(0)
    assert 'data-can-update="0"' in row
    payload = json.loads(
        re.search(r"const supportAvailable=(\{.*?\});", page.text, re.S).group(1)
    )
    assert payload[str(task.id)] is False
    monkeypatch.setattr(
        task_router,
        "_task_hierarchy_scope_allows",
        lambda _db, _user_id, _task, *, action: action != "update",
    )
    denied_targets = authenticated_client.get(
        f"/v2-clean/tasks/{task.id}/support-targets"
    )
    assert denied_targets.status_code == 403
    assert denied_targets.json() == {"targets": []}


def test_approved_workbench_loads_on_demand_through_authorized_open_resolver() -> None:
    assert "window.openTaskWorkbench" in TEMPLATE
    assert "openTaskWorkbenchOnDemand" in TEMPLATE
    assert "`/v2-clean/tasks/${taskId}/open?return_url=${encodeURIComponent(returnUrl)}`" in TEMPLATE
    assert "{% if false %}{% for task in tasks %}" in TEMPLATE
    assert "Tarefa antiga" not in TEMPLATE
    assert "CF-TASK-" not in TEMPLATE
    assert 'name="status" value="{{ task.status }}"' not in TEMPLATE
    assert "/transition`;" in TEMPLATE
    assert 'action="/v2-clean/tasks/{{ task.id }}/update"' in DETAIL
    assert "data-assignment-exclusive" in DETAIL


def test_initial_list_does_not_render_one_workbench_per_task(
    authenticated_client, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(task_router.settings, "visual_foundation_enabled", True)
    actor = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    for index in range(10):
        db_session.add(
            Task(
                title=f"Tarefa leve {index}",
                task_type="operational_task",
                category="Documentação",
                status="new",
                priority="normal",
                assigned_to_id=actor.id,
            )
        )
    db_session.commit()
    queries = 0

    def count_query(*_args) -> None:
        nonlocal queries
        queries += 1

    event.listen(db_session.bind, "before_cursor_execute", count_query)
    try:
        page = authenticated_client.get(
            "/v2-clean/tasks?workspace=mine&mine_kind=all&status=open&category=all"
        )
    finally:
        event.remove(db_session.bind, "before_cursor_execute", count_query)

    assert page.status_code == 200
    assert page.text.count('class="clean-task-preview"') == 0
    assert page.text.count("<form") < 20
    assert page.text.count("<dialog") <= 7
    # Ten extra rows must not reintroduce the former per-row workbench and
    # support-target query fan-out (197 queries on the frozen base).
    assert queries <= 140, queries


def test_management_uses_the_same_comment_state_and_support_language() -> None:
    for marker in ('href="#task-edit"', '>Comentar</a>', '>Alterar estado</a>', '>Solicitar suporte</a>'):
        assert marker in DETAIL
    assert 'name="comment"' in DETAIL and "required maxlength=\"4000\"" in DETAIL
    assert 'name="requested_target" required' in DETAIL
    assert 'name="message" rows="3" required' in DETAIL
    assert "task_support_targets" in ROUTER


def test_management_clarifies_current_state_and_uses_minimal_disclosure() -> None:
    assert "Estado atual" in DETAIL
    assert "Sem transições legais disponíveis" in DETAIL
    assert "<details><summary>Mais opções</summary>" in DETAIL


def test_queue_and_state_controls_explain_their_distinct_contracts() -> None:
    assert "Única fila autorizada" in TEMPLATE
    assert 'data-task-queue aria-label="Fila ativa"' in TEMPLATE
    assert "Filtrar por estado" in TEMPLATE
    assert "Recorta a lista; não define transições." in TEMPLATE
    assert "Estado atual" in TEMPLATE
    assert "Transições disponíveis" in TEMPLATE
    assert "Destinos legais devolvidos pelo servidor" in TEMPLATE
    assert "Transições disponíveis" in DETAIL


def test_management_support_surface_fails_closed_without_update_scope(
    authenticated_client, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(task_router.settings, "visual_foundation_enabled", True)
    actor = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    task = Task(
        title="Gestão sem suporte autorizado",
        task_type="operational_task",
        category="Documentação",
        status="new",
        priority="normal",
        assigned_to_id=actor.id,
    )
    db_session.add(task)
    db_session.commit()
    original_scope_check = task_router._task_hierarchy_scope_allows

    def scope_check(db, user_id, candidate, *, action):
        if candidate.id == task.id and action == "update":
            return False
        return original_scope_check(db, user_id, candidate, action=action)

    monkeypatch.setattr(task_router, "_task_hierarchy_scope_allows", scope_check)
    page = authenticated_client.get(f"/v2-clean/tasks/{task.id}/detail")

    assert page.status_code == 200
    assert 'id="task-support"' not in page.text
    assert 'href="#task-support"' not in page.text


def test_approved_selection_preserves_return_context() -> None:
    assert 'data-task-row' in TEMPLATE
    assert 'data-return-context' in TEMPLATE
    assert 'history.replaceState' in TEMPLATE
    assert 'sessionStorage' in TEMPLATE
    assert 'data-task-scroll' in TEMPLATE
    assert 'scrollTop' in TEMPLATE
    assert 'carfast.taskScroll:' in TEMPLATE


def test_server_side_scope_is_shared_by_list_and_counters() -> None:
    assert "visibility_filter =" in ROUTER
    assert "task_visibility_filter" in ROUTER
    assert "task_counter_metrics" in ROUTER
    assert "counter_base_filters" in ROUTER


def test_initial_default_excludes_closed_and_shows_complete_authorized_workload(
    authenticated_client, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(task_router.settings, "visual_foundation_enabled", True)
    actor = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    db_session.add_all(
        [
            Task(title="Documento ativo aprovado", task_type="operational_task", category="Documentação", status="new", priority="normal", assigned_to_id=actor.id),
            Task(title="Oficina fora do foco inicial", task_type="workshop_task", category="Oficina", status="new", priority="normal", assigned_to_id=actor.id),
            Task(title="Documento fechado excluído", task_type="operational_task", category="Documentação", status="closed", priority="normal"),
            Task(title="Documento cancelado excluído", task_type="operational_task", category="Documentação", status="cancelled", priority="normal"),
            Task(title="Documento sem ação excluído", task_type="operational_task", category="Documentação", status="no_action_needed", priority="normal"),
        ]
    )
    db_session.commit()

    page = authenticated_client.get("/v2-clean/tasks")

    assert page.status_code == 200
    assert "Documento ativo aprovado" in page.text
    assert "Oficina fora do foco inicial" in page.text
    assert "Documento fechado excluído" not in page.text
    assert "Documento cancelado excluído" not in page.text
    assert "Documento sem ação excluído" not in page.text
    assert 'name="category" value="all"' in page.text
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
    actor = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    for task in db_session.scalars(select(Task).where(Task.created_by_id.is_(None))):
        task.created_by_id = actor.id
    db_session.commit()

    workshop = authenticated_client.get("/v2-clean/tasks?workspace=mine&mine_kind=all&status=open&category=oficina")
    closed = authenticated_client.get("/v2-clean/tasks?workspace=mine&mine_kind=all&status=closed&category=all")

    assert "Oficina ativa contratual" in workshop.text
    assert "Fechada contratual" not in workshop.text
    assert "Fechada contratual" in closed.text


def test_each_approved_status_filter_is_server_side(
    authenticated_client, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(task_router.settings, "visual_foundation_enabled", True)
    statuses = {
        "new": "Filtro Nova",
        "in_execution": "Filtro Em curso",
        "waiting": "Filtro Em espera",
        "support_requested": "Filtro Suporte",
        "resolved": "Filtro Resolvida",
        "cancelled": "Filtro Cancelada",
    }
    db_session.add_all(
        Task(
            title=title,
            task_type="operational_task",
            category="Documentação",
            status=status,
            priority="normal",
        )
        for status, title in statuses.items()
    )
    db_session.commit()
    actor = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    for task in db_session.scalars(select(Task).where(Task.created_by_id.is_(None))):
        task.created_by_id = actor.id
    db_session.commit()

    for status, title in statuses.items():
        page = authenticated_client.get(
            f"/v2-clean/tasks?workspace=mine&mine_kind=all&category=all&status={status}"
        )
        assert page.status_code == 200
        assert title in page.text
        for other_title in set(statuses.values()) - {title}:
            assert other_title not in page.text


def test_closed_and_risk_query_is_explicitly_normalized(
    authenticated_client, monkeypatch
) -> None:
    monkeypatch.setattr(task_router.settings, "visual_foundation_enabled", True)
    response = authenticated_client.get(
        "/v2-clean/tasks?status=closed&due=due_soon"
    )
    assert response.status_code == 200
    assert "incompatíveis" in response.text
    assert '<option value="due_soon" selected' not in response.text


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

    actor = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    personal = Task(
        title="Minha tarefa em risco",
        task_type="operational_task",
        category="Documentação",
        status="new",
        priority="high",
        assigned_to_id=actor.id,
        due_on=today + timedelta(days=1),
    )
    db_session.add(personal)
    db_session.commit()

    page = authenticated_client.get("/v2-clean/tasks?workspace=mine&status=open&category=all")
    unassigned = authenticated_client.get("/v2-clean/tasks?workspace=all&status=open&category=all&assignment=unassigned")
    destinations = {
        "active": authenticated_client.get("/v2-clean/tasks?workspace=mine&status=open&category=all"),
        "risk": authenticated_client.get("/v2-clean/tasks?workspace=mine&status=open&category=all&due=due_soon"),
        "late": authenticated_client.get("/v2-clean/tasks?workspace=mine&status=open&category=all&due=overdue"),
        "unassigned": unassigned,
    }
    for counter, destination in destinations.items():
        page_count = int(
            re.search(
                rf'data-task-counter="{counter}"[^>]+aria-label="Ver (\d+) tarefas',
                page.text,
            ).group(1)
        )
        result_count = int(
            re.search(
                r'<section class="task-center-approved-queue[^>]*>.*?<header>.*?<span>(\d+) tarefas?',
                destination.text,
                re.S,
            ).group(1)
        )
        assert page_count == result_count, counter


def test_legacy_focus_cookie_is_ignored_and_invalid_category_falls_back_to_all(
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
        assert "Documento fora do foco lembrado" in page.text
        assert 'name="category" value="all"' in page.text


def test_category_buckets_are_mutually_exclusive_under_adversarial_type(
    authenticated_client, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(task_router.settings, "visual_foundation_enabled", True)
    db_session.add(
        Task(title="Sinistro em fluxo de oficina", task_type="workshop_task", category="Sinistros", status="new", priority="high")
    )
    db_session.commit()
    actor = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    for task in db_session.scalars(select(Task).where(Task.created_by_id.is_(None))):
        task.created_by_id = actor.id
    db_session.commit()

    workshop = authenticated_client.get("/v2-clean/tasks?workspace=mine&mine_kind=all&status=open&category=oficina")
    claims = authenticated_client.get("/v2-clean/tasks?workspace=mine&mine_kind=all&status=open&category=sinistros")

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
    actor = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    for task in db_session.scalars(select(Task).where(Task.created_by_id.is_(None))):
        task.created_by_id = actor.id
    db_session.commit()

    workshop = authenticated_client.get("/v2-clean/tasks?workspace=mine&mine_kind=all&status=open&category=oficina")
    documents = authenticated_client.get("/v2-clean/tasks?workspace=mine&mine_kind=all&status=open&category=documentacao")

    assert "Oficina sem categoria" in workshop.text
    assert "Admin sem categoria" not in workshop.text
    assert "Admin sem categoria" not in documents.text
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
    actor = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    for task in db_session.scalars(select(Task).where(Task.created_by_id.is_(None))):
        task.created_by_id = actor.id
    db_session.commit()

    page = authenticated_client.get("/v2-clean/tasks?workspace=mine&mine_kind=all&status=open&category=documentacao")
    row = re.search(r'<tr[^>]+data-title="Atualiza sem responder"[^>]+>', page.text).group(0)

    assert 'data-can-update="1"' in row
    assert 'data-can-respond="0"' in row


def test_existing_relations_are_exposed_without_repeating_generic_origin(
    authenticated_client, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(task_router.settings, "visual_foundation_enabled", True)
    actor = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    parent = Task(title="Tarefa mãe", task_type="operational_task", category="Documentação", status="new", priority="normal", assigned_to_id=actor.id)
    db_session.add(parent)
    db_session.flush()
    child = Task(title="Subtarefa relacionada", task_type="operational_task", category="Documentação", status="new", priority="normal", parent_task_id=parent.id, assigned_to_id=actor.id)
    db_session.add(child)
    db_session.commit()

    page = authenticated_client.get("/v2-clean/tasks?workspace=mine&mine_kind=all&status=open&category=all")
    row = re.search(r'<tr[^>]+data-title="Subtarefa relacionada"[^>]+>', page.text).group(0)

    assert "data-origin=" not in row
    assert f'data-relation="Tarefa mãe CF-{parent.id:05d}"' in row
    assert "Origem" not in re.search(r'<thead>.*?</thead>', page.text, re.S).group(0)


def test_creation_options_and_post_share_the_same_capability_resolver() -> None:
    assert "TaskCreationCapabilityResolver(db).options(current_user)" in ROUTER
    service = (ROOT / "app/services/task_templates.py").read_text(encoding="utf-8")
    assert "TaskCreationCapabilityResolver(db).require(user, version)" in service
    assert 'data-task-create-open' in TEMPLATE
    assert 'data-task-create-future disabled' not in TEMPLATE
    assert "createForm.querySelector('[name=return_url]').value=location.pathname+location.search+location.hash" in TEMPLATE


def test_preview_actions_use_clean_canonical_routes_and_accessible_editors() -> None:
    assert "/task-board/${selectedRow.dataset.taskId}" not in TEMPLATE
    assert "prompt('Registar nota na tarefa')" not in TEMPLATE
    assert 'data-task-state-dialog' in TEMPLATE
    assert 'data-task-note-dialog' in TEMPLATE
    assert 'window.openTaskWorkbench' in TEMPLATE
    assert '/v2-clean/tasks/${selectedRow.dataset.taskId}/transition' in TEMPLATE
    assert '/v2-clean/tasks/${selectedRow.dataset.taskId}/comments' in TEMPLATE


def test_state_editor_separates_current_state_and_only_builds_legal_destinations() -> None:
    assert 'data-task-current-state' in TEMPLATE
    assert 'Transições disponíveis' in TEMPLATE
    assert 'taskStatusLabels={{ task_status_labels|tojson }}' in TEMPLATE
    assert "select.replaceChildren(...allowed.map" in TEMPLATE
    assert 'Novo estado<select' not in TEMPLATE


def test_workbench_keeps_primary_work_visible_and_hides_rare_fields_progressively() -> None:
    more = DETAIL.index("<details><summary>Mais opções</summary>")
    assert DETAIL.index('name="priority"') < more
    assert DETAIL.index('name="due_on"') < more
    assert DETAIL.index('data-work-hierarchy') > more
    assert "task-detail-status-line" in DETAIL
    assert "task-detail-quick-comment" in DETAIL
    assert "task-detail-document" in DETAIL
    assert "user_by_id.get(item.user_id).name" in DETAIL


def test_preview_presents_persisted_queue_and_canonical_classification() -> None:
    assert 'data-preview-category' in TEMPLATE
    assert 'data-preview-owner' in TEMPLATE
    assert 'data-preview-due' in TEMPLATE
    assert 'data-preview-sla-detail' in TEMPLATE
    assert 'data-task-preview-edit="classification"' in TEMPLATE
    assert 'data-preview-focus' not in TEMPLATE


def test_list_detail_visibility_uses_one_canonical_resolver() -> None:
    assert "user_can_view_task(db, user_id=user_id, task=task)" in ROUTER
    assert '@web_router.get("/v2-clean/tasks/{task_id}/open")' in ROUTER
    assert 'issue_return_context(' in ROUTER
    assert 'f"/v2-clean/tasks/{task_id}/detail?return_context={quote(return_token)}"' in ROUTER
    assert "task_return_url" in ROUTER
    assert 'href="{{ task_return_url }}"' in (ROOT / "app/templates/task_detail.html").read_text(encoding="utf-8")


def test_creation_uses_three_approved_models_and_never_labels_workspaces_as_queues() -> None:
    assert "Pedido simples" in TEMPLATE
    assert "Informação / Comunicação" in TEMPLATE
    assert "Tarefa completa" in TEMPLATE
    assert "Mais opções" in TEMPLATE
    assert "Fila autorizada" not in TEMPLATE
    creation_dialog = TEMPLATE[TEMPLATE.index('<dialog id="new-task"'):]
    assert 'action="/v2-clean/tasks"' in creation_dialog
    assert 'data-create-model="request"' in creation_dialog
    assert 'data-create-model="information"' in creation_dialog
    assert 'data-create-model="task"' in creation_dialog
    assert 'href="/task-board/new' not in creation_dialog
    assert 'name="classification_version" value="3"' in creation_dialog
    for level in ("queue", "department", "category", "subcategory"):
        assert f'data-work-level="{level}"' in creation_dialog
    assert 'name="entity_type"' in creation_dialog
    assert 'name="entity_id"' in creation_dialog
    assert 'name="attachments" multiple' in creation_dialog
    assert "more.hidden=model!=='task'" in TEMPLATE
    assert "filterChildren(department,queue.value)" in TEMPLATE
    css = (ROOT / "app/static/css/ui-contract-v1.css").read_text(encoding="utf-8")
    assert "[data-task-create-dialog]{width:min(720px,calc(100vw - 32px))" in css
    assert "[data-task-create-form]{display:grid;grid-template-columns:repeat(2" in css


def test_task_forms_use_scoped_team_resolver_and_legacy_defaults_are_explicit() -> None:
    assert "task_context_teams(" in ROUTER
    assert "LEGACY_WORKSPACE_TEAM_CODES" in ROUTER
    for code in ("operations", "workshop", "finance", "support"):
        assert f'"{code}"' in ROUTER
    form_route = ROUTER[ROUTER.index("def task_new_form("):ROUTER.index("def task_vehicle_search(")]
    assert "select(Team).where(Team.active.is_(True)).order_by(Team.name)" not in form_route
    update_route = ROUTER[ROUTER.index("def task_update("):ROUTER.index("def task_guided_flow_step_update(")]
    assert update_route.count("task_team_allowed_for_workspace(") >= 3


def test_terminal_action_visibility_matches_server_complete_scope() -> None:
    list_scope = ROUTER[ROUTER.index("task_close_allowed_by_id ="):ROUTER.index("task_respond_allowed_by_id =")]
    detail_scope = ROUTER[ROUTER.index("can_close_task ="):ROUTER.index("detail_transition_options =")]
    assert 'workspace_allowed(workspace_for_task_type(task.task_type), "close")' in list_scope
    assert 'action="complete"' in list_scope
    assert 'action="complete"' in detail_scope


def test_inline_transition_is_server_side_and_fail_closed() -> None:
    assert '@web_router.post("/v2-clean/tasks/{task_id}/transition"' in ROUTER
    assert "task_allowed_status_transitions" in ROUTER
    assert 'flag="invalid_transition"' in ROUTER


def test_guardrails_keep_owner_executor_support_and_sla_concepts_distinct() -> None:
    assert "task_assignment_labels" in ROUTER
    assert "TaskHelpRequest" in ROUTER
    assert "task_sla_by_id = {task.id: sla_snapshot(task)" in ROUTER
    assert "data-preview-owner" in TEMPLATE
    assert "data-preview-due" in TEMPLATE
    assert "task_sla_labels_by_id" in ROUTER
    assert "data-preview-sla" in TEMPLATE
    assert 'data-sla="{{ task_sla_labels_by_id.get' in TEMPLATE
