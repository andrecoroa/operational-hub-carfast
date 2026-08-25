from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "app" / "templates" / "clean_task_center.html"
CSS = ROOT / "app" / "static" / "css" / "visual-v2.css"
VISUAL_JS = ROOT / "app" / "static" / "js" / "visual-v2.js"
ROUTER = ROOT / "app" / "web" / "router.py"


def test_service_desk_uses_approved_visual_components_and_real_markup() -> None:
    source = TEMPLATE.read_text(encoding="utf-8")

    for contract in (
        "visual-service-desk",
        "visual-service-heading",
        "visual-service-metrics",
        "visual-task-workbench",
        "visual-task-workbench-header",
        "visual-task-filters",
        "visual-task-drawer",
        "visual-task-save-actions",
        'aria-label="Filtros da fila de trabalho"',
        "Guardar e fechar",
        "Voltar à fila",
    ):
        assert contract in source
    assert source.count('class="visual-service-kpi-icon') == 5
    assert 'name="post_action" value="stay"' in source
    assert 'name="post_action" value="close"' in source
    assert "{% else %}<button type=\"submit\">Guardar</button>{% endif %}" in source
    assert '<span>Notificações</span>' in source
    assert "Coordenador de Equipa" in source
    assert '<span>Equipa fica por assumir</span>' in source
    assert source.count("clean-task-collaboration-state") == 1


def test_service_desk_drawer_traps_and_restores_focus() -> None:
    source = TEMPLATE.read_text(encoding="utf-8")

    for contract in (
        'role="dialog" aria-modal="true" tabindex="-1"',
        "taskPreviewTrigger = trigger || document.activeElement",
        "taskPreviewTrigger.focus()",
        'if (event.key !== "Tab") return;',
        "item.closest('[hidden],[inert],[aria-hidden=\"true\"]')",
        "item.getClientRects().length > 0",
        "summary,iframe,object,embed",
        "last.focus()",
        "first.focus()",
    ):
        assert contract in source


def test_closed_navigation_does_not_steal_drawer_escape_focus() -> None:
    source = VISUAL_JS.read_text(encoding="utf-8")

    assert 'event.key === "Escape" && document.body.classList.contains("visual-nav-open")' in source


def test_service_desk_responsive_contract_has_local_not_global_overflow() -> None:
    css = CSS.read_text(encoding="utf-8")

    for contract in (
        ".visual-service-metrics { display: grid; grid-template-columns: repeat(5,minmax(0,1fr));",
        ".visual-task-workbench .clean-task-table-wrap { overflow-x: auto;",
        ".visual-task-drawer { width: min(1040px,calc(100vw - 32px));",
        ".visual-task-filters { grid-template-columns: repeat(2,minmax(0,1fr));",
        'content: "Deslize para ver todas as colunas →"',
        ".visual-task-drawer { width: 100vw; max-width: 100vw; }",
        ".visual-task-filters input,.visual-task-filters select,.visual-task-filters button { height: 48px; min-height: 48px; }",
        ".visual-task-open { min-width: 48px; height: 48px; }",
        ".visual-service-desk .clean-task-notification-title { display: inline-flex;",
        ".visual-service-desk .clean-task-side-form button.secondary { color: var(--cf-blue-600);",
        ".visual-task-drawer .clean-task-collaboration-state > span { display: grid;",
        ".visual-task-open { display: inline-flex; min-width: 72px;",
    ):
        assert contract in css


def test_task_update_post_action_is_fail_closed_to_close() -> None:
    router = ROUTER.read_text(encoding="utf-8")
    block = router[router.index("def clean_tasks_update(") : router.index("def clean_tasks_update_context(")]

    assert 'post_action: str = Form("close")' in block
    assert 'if post_action == "stay":' in block
    assert 'clean_task_action_redirect(return_url, task_id=task_id, flag="updated")' in block
