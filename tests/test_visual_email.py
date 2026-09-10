from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "app" / "templates" / "clean_email_inbox.html"
THREAD = ROOT / "app" / "templates" / "_email_thread_content.html"
CSS = ROOT / "app" / "static" / "css" / "visual-v2.css"
CONTRACT_CSS = ROOT / "app" / "static" / "css" / "ui-contract-v1.css"
JS = ROOT / "app" / "static" / "js" / "email.js"
ROUTER = ROOT / "app" / "web" / "email.py"


def test_email_center_rebuilds_real_composition() -> None:
    source = TEMPLATE.read_text(encoding="utf-8")

    for contract in (
        "visual-email-center",
        "visual-email-heading",
        "visual-email-overview",
        "visual-email-metrics",
        "visual-email-workbench",
        "visual-email-workbench-header",
        "visual-email-filters",
        "visual-email-table-wrap",
        "visual-email-table",
        "email-mailbox-summary",
        "email-list-inline",
        "visual-email-compose",
        "Parametrizar caixas",
        "Aplicar filtros",
        "Inbox unificada",
    ):
        assert contract in source

    assert 'href="/v2-clean/admin/work-classification?view=channels"' in source
    assert 'data-email-thread-url="{{ thread_url }}"' in source
    assert 'return_context=' in source
    assert 'aria-label="Conversas de email"' in source


def test_email_center_keeps_triage_preview_and_actions() -> None:
    source = THREAD.read_text(encoding="utf-8")

    for contract in (
        "email-reader-grid",
        "email-conversation",
        "email-triage-pane",
        "Guardar gestão",
        "Responder",
        "Confirmar classificação",
        "Criar tarefa",
        "email-attachment-dialog",
    ):
        assert contract in source


def test_email_responsive_contract_uses_local_overflow_and_full_screen_preview() -> None:
    css = CSS.read_text(encoding="utf-8")

    for contract in (
        ".visual-email-metrics { display: grid;",
        ".visual-email-center { width: 100%; max-width: none; min-width: 0;",
        ".visual-email-overview,.visual-email-workbench { width: 100%; max-width: none; min-width: 0;",
        "grid-template-columns: repeat(5,minmax(0,1fr));",
        ".visual-email-table-wrap { width: 100%; max-width: none; min-width: 0; overflow-x: auto;",
        ".visual-email-table { width: 100%; min-width: 1180px; table-layout: fixed;",
        ".visual-email-table td { height: 64px; padding: 9px 10px; font-size: 13px;",
        ".visual-email-filters { grid-template-columns: repeat(2,minmax(0,1fr));",
        'content: "Deslize para ver todas as colunas →"',
        ".visual-email-preview,.visual-email-compose { width: 100vw;",
        "height: 100dvh; max-height: 100dvh;",
        ":is(.visual-email-preview,.visual-email-thread-page) .email-save-triage { color: #fff; background: var(--cf-blue-600);",
        ":is(.visual-email-preview,.visual-email-thread-page) .email-conclude { color: #fff; background: var(--cf-teal-700);",
        ".email-modal-footer .button-link { min-height: 48px;",
    ):
        assert contract in css


def test_email_full_page_keyboard_and_return_contract() -> None:
    source = JS.read_text(encoding="utf-8")

    for contract in (
        '[data-email-thread-url]',
        'event.key !== "Enter" && event.key !== " "',
        "window.location.assign(element.dataset.emailThreadUrl)",
    ):
        assert contract in source


def test_email_thread_uses_full_width_reader_drawer_navigation_and_spam() -> None:
    source = THREAD.read_text(encoding="utf-8")
    css = CONTRACT_CSS.read_text(encoding="utf-8")
    script = JS.read_text(encoding="utf-8")
    router = ROUTER.read_text(encoding="utf-8")

    for text in ("Voltar à caixa", "Anterior", "Próximo", "Confirmar classificação", "Guardar gestão", "Ligações", "Marcar email como tratado", "Aguardar conclusão da tarefa", "Abrir tarefa", "Spam"):
        assert text in source
    assert "email-treatment-drawer" in source
    assert ".email-treatment-drawer{position:fixed" in css
    assert 'window.confirm("Mover esta conversa para Spam?' in script
    assert 'destinationId": "junkemail"' in (ROOT / "app/services/microsoft365_oauth.py").read_text(encoding="utf-8")
    assert '@email_router.post("/v2-clean/email/{thread_id}/spam")' in router


def test_email_inline_mailboxes_and_mobile_overflow_contract() -> None:
    template = TEMPLATE.read_text(encoding="utf-8")
    css = CONTRACT_CSS.read_text(encoding="utf-8")
    script = JS.read_text(encoding="utf-8")

    assert "email-mailbox-summary" in template
    assert "Abrir caixa" in template
    assert "Recebido originalmente em:" not in template.split("{% block body %}", 1)[0]
    assert "email-inline-preview-row" not in script
    assert "sourceRow.after(inlinePreviewRow)" not in script
    assert "@media (max-width:900px)" in css
    assert ".email-inline-preview-body { max-height:none; overflow:visible; }" in css
    assert ".email-mailbox-summary { grid-template-columns:1fr; }" in css


def test_email_inline_preview_prioritizes_message_reading_space() -> None:
    css = CONTRACT_CSS.read_text(encoding="utf-8")
    source = THREAD.read_text(encoding="utf-8")

    assert ".email-list-inline .visual-email-table thead th { position:sticky" in css
    assert ".email-inline-preview-body .email-modal-header { height:64px; min-height:64px; }" in css
    assert ".email-inline-preview-body{min-height:520px" in css
    assert ".email-inline-preview-body .email-reader-grid{grid-template-columns:minmax(0,2.35fr)" in css
    assert ".email-inline-preview-body .email-body-frame{box-sizing:border-box" in css
    assert "height:clamp(280px,42vh,520px)" in css
    assert "Anexos para tratamento" in source
    assert "Tratar anexo" in source
    assert "Imagens incorporadas no email · não contam como anexos" in source


def test_email_compact_surface_keeps_views_actions_and_reader_priority() -> None:
    template = TEMPLATE.read_text(encoding="utf-8")
    css = CONTRACT_CSS.read_text(encoding="utf-8")

    header = template.split('<header class="email-header', 1)[1].split("</header>", 1)[0]
    assert "email-work-views" in header
    assert "Parametrizar caixas" in header
    assert "data-email-compose-open" in header
    assert "<h1>Email</h1>" not in header
    assert "Referência / atualização" in template
    assert "Email compact work surface" in css
    assert ".visual-email-heading{display:flex;height:42px" in css
    assert ".visual-email-table td{height:48px" in css
    assert "grid-template-columns:minmax(0,2.45fr) minmax(290px,.72fr)" in css
    assert ".email-modal-footer{display:flex;min-height:36px" in css


def test_email_operational_indicators_match_task_center_language_and_density() -> None:
    template = TEMPLATE.read_text(encoding="utf-8")
    css = CONTRACT_CSS.read_text(encoding="utf-8")

    for code, label in (
        ("to_treat", "Por tratar"),
        ("new", "Novos"),
        ("unassigned", "Por atribuir"),
        ("overdue", "Atrasados"),
        ("risk", "Em risco"),
    ):
        assert f"signal={code}" in template
        assert f"<span>{label}</span>" in template
    assert "border-radius:999px" in css
    assert ".visual-email-metrics>a.is-danger" in css
    assert ".visual-email-metrics>a.is-warning" in css


def test_email_reader_exposes_structured_headers_and_attachment_separation() -> None:
    source = THREAD.read_text(encoding="utf-8")

    for label in ("Assunto:", "De:", "Para:", "Data:"):
        assert label in source
    assert "Anexos para tratamento" in source
    assert "attachments_by_message[item.id]|length" in source
    assert "Imagens incorporadas no email · não contam como anexos" in source
    assert "embedded_images_by_message[item.id]|length" in source


def test_email_full_page_return_context_is_local_and_feature_gated() -> None:
    source = ROUTER.read_text(encoding="utf-8")

    assert 'return_context.startswith("/v2-clean/email")' in source
    assert 'return_context.startswith("//")' in source
    assert '"foundation_ui_enabled": settings.visual_foundation_enabled' in source
    assert '"return_context": return_context' in source


def test_email_full_page_reader_scroll_and_action_hierarchy_contract() -> None:
    css = CONTRACT_CSS.read_text(encoding="utf-8")
    source = THREAD.read_text(encoding="utf-8")
    script = JS.read_text(encoding="utf-8")

    base = (ROOT / "app/templates/base.html").read_text(encoding="utf-8")
    page = (ROOT / "app/templates/clean_email_thread.html").read_text(encoding="utf-8")

    assert 'class="ui-contract-v1"' in base
    assert "visual-email-thread-page" in page
    assert "body.ui-contract-v1 .visual-email-thread-page{height:100dvh!important;min-height:0!important;overflow:hidden!important" in css
    assert ".email-modal-shell-full{display:flex!important;flex-direction:column" in css
    assert "height:calc(100dvh - 84px)!important" in css
    assert ".email-reader-grid{display:grid!important" in css
    assert "overflow:auto!important;overscroll-behavior:contain" in css
    assert "body.ui-contract-v1 .visual-email-thread-page .email-modal-footer{position:relative!important" in css
    assert "min-height:52px;height:52px;padding:11px 18px" in css
    assert "font-size:14px;font-weight:700" in css
    assert "grid-template-columns:minmax(148px,.7fr)" in css
    assert "grid-template-columns:repeat(2,minmax(0,1fr));gap:10px" in css
    assert "@media(max-width:1100px)" in css
    assert "@media(max-width:600px)" in css
    assert 'class="email-reply-primary"' in source
    assert 'class="email-create-task-action"' in source
    assert "email-treatment-open" in source
    assert 'aria-expanded="false"' in source
    assert "data-email-drawer-close" in source
    assert "Triagem e classificação" in source
    assert "Responsável e prazo" in source
    assert "Estado do email" in source
    assert "Notas e conclusão" in source
    assert "Histórico recente" in source
    assert "email-spam-action" in source
    assert 'root.classList.toggle("is-treatment-open", open)' in script
    assert 'setOpen(!drawer.classList.contains("is-open"))' in script
    assert 'root.querySelectorAll("[data-email-open-composer]")' in script
    assert 'event.key === "Escape"' in script
    assert "frame.contentDocument?.documentElement?.scrollHeight" in script
    assert "frame.style.height" in script
    assert "ui-contract-v1.css?v=20260910-email-workspace" in base
    assert "email.js?v=20260910-email-workspace" in page


def test_email_classification_changes_keep_before_after_audit_contract() -> None:
    router = ROUTER.read_text(encoding="utf-8")

    assert '"classification_audit": classification_audit' in router
    assert '"classification_audit_users": classification_audit_users' in router
    assert '"classification_audit_rows": classification_audit_rows' in router
    assert "classification_before = {" in router
    assert "classification_after = {" in router
    assert '"before": classification_before' in router
    assert '"after": classification_after' in router
    assert '"classification_changed": classification_before' in router
