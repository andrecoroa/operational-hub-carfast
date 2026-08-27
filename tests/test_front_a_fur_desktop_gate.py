from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_fur_sidebar_has_direct_short_destinations_without_workshop_configuration():
    sidebar = _read("app/templates/_sidebar.html")
    assert '>Oficina</a>' in sidebar
    assert '>Stock</a>' in sidebar
    assert '>Tarefas<span class="sr-only">Centro de Tarefas</span></a>' in sidebar
    assert '>Processos<span class="sr-only">Centro de Processos</span></a>' in sidebar
    business = sidebar.index('data-nav-section="business"')
    fleet = sidebar.index('{% set fleet_menu_open', business)
    workshop_segment = sidebar[business:fleet]
    assert "sidebar-nav-children" not in workshop_segment
    assert "Modelos / Configuração" not in workshop_segment
    assert "Stock e Compras" not in workshop_segment


def test_fur_sidebar_and_actions_encode_stable_geometry():
    css = _read("app/static/css/ui-contract-v1.css")
    assert "scrollbar-gutter: stable" in css
    assert "text-overflow: ellipsis" in css
    assert "white-space: nowrap" in css
    assert ":is(button,.button-link,.visual-button,.clean-action-button)" in css


def test_fur_headers_and_document_states_are_explicit_and_compact():
    css = _read("app/static/css/ui-contract-v1.css")
    documents = _read("app/templates/clean_documentation_triage.html")
    assert ".visual-breadcrumbs { display: none; }" in css
    assert ".clean-content > header .eyebrow { display: none; }" in css
    assert "Validação" in documents
    assert "Validado" in documents
    assert "Bloqueado" in documents
    assert "Baixa confiança" in documents


def test_fur_geometry_probe_checks_visible_descendants_not_only_body_width():
    probe = _read("scripts/front_a_geometry_probe.js")
    assert 'document.querySelectorAll("body *")' in probe
    assert "getBoundingClientRect" in probe
    assert "hasClippingAncestor" in probe
    assert "uncontainedDescendantOverflow" in probe
    assert "actionBar" in probe
    assert "fullyVisible" in probe
    assert "isFullyPaintable" in probe
    assert "actionControls.every" in probe


def test_fur_email_and_documents_preserve_queue_until_explicit_selection():
    email_js = _read("app/static/js/email.js")
    documents = _read("app/templates/clean_documentation_triage.html")
    router = _read("app/web/router.py")
    assert 'classList.add("is-preview-open")' in email_js
    assert 'classList.remove("is-preview-open")' in email_js
    assert 'visual-document-grid{% if selected_row %} is-preview-open{% endif %}' in documents
    selected_block = router[router.index("selected_row = next(", router.index("def clean_documentation_triage")):]
    assert "None," in selected_block[:240]


def test_fur_workshop_first_fold_contract_is_compact_and_keeps_one_primary_action():
    template = _read("app/templates/clean_workshop_dashboard.html")
    css = _read("app/static/css/ui-contract-v1.css")
    assert 'class="clean-header-shell clean-card-wide clean-header-shell-dashboard fur-workshop-header"' in template
    assert template.count('class="button-link" href="/v2-clean/workshop-entry"') == 1
    assert 'class="fur-secondary-actions"' in template
    assert "clean-workshop-filter-title" not in template
    for marker in (
        ".fur-workshop-header",
        ".fur-workshop-list-title",
        ".clean-workshop-dashboard-filters",
        ".clean-workshop-process-item",
    ):
        assert marker in css


def test_fur_admin_uses_one_local_navigation_per_route_family():
    template = _read("app/templates/clean_admin.html")
    directory = _read("app/templates/_clean_admin_directory.html")
    assert '_supplier_context_nav.html' not in template
    assert template.count('_clean_admin_directory.html') == 1
    assert '_clean_admin_residual_nav.html' not in template
    assert 'clean-admin-master-detail' in template
    for label in ('Setup', 'Organização', 'Utilizadores', 'Perfis / Permissões', 'Categorias', 'Email', 'Modelos', 'Integrações', 'Segurança / Auditoria'):
        assert label in directory
    assert '/v2-clean/tasks' not in directory
    assert '/v2-clean/processes' not in directory


def test_fur_does_not_enable_external_effects_or_client_only_authority():
    config = _read("app/core/config.py")
    task_resolver = _read("app/services/task_templates.py")
    assert "email_outbound_enabled" in config
    assert "email_outbound_enabled: bool = False" in config
    assert "TaskCreationCapabilityResolver" in task_resolver
