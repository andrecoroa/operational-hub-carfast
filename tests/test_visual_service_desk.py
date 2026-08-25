from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "app" / "templates" / "clean_task_center.html"
CSS = ROOT / "app" / "static" / "css" / "visual-v2.css"
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


def test_service_desk_responsive_contract_has_local_not_global_overflow() -> None:
    css = CSS.read_text(encoding="utf-8")

    for contract in (
        ".visual-service-metrics { display: grid; grid-template-columns: repeat(5,minmax(0,1fr));",
        ".visual-task-workbench .clean-task-table-wrap { overflow-x: auto;",
        ".visual-task-drawer { width: min(1040px,calc(100vw - 32px));",
        ".visual-task-filters { grid-template-columns: repeat(2,minmax(0,1fr));",
        'content: "Deslize para ver todas as colunas →"',
        ".visual-task-drawer { width: 100vw; max-width: 100vw; }",
    ):
        assert contract in css


def test_task_update_post_action_is_fail_closed_to_close() -> None:
    router = ROUTER.read_text(encoding="utf-8")
    block = router[router.index("def clean_tasks_update(") : router.index("def clean_tasks_update_context(")]

    assert 'post_action: str = Form("close")' in block
    assert 'if post_action == "stay":' in block
    assert 'clean_task_action_redirect(return_url, task_id=task_id, flag="updated")' in block
