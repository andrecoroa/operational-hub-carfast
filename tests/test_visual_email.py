from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "app" / "templates" / "clean_email_inbox.html"
THREAD = ROOT / "app" / "templates" / "_email_thread_content.html"
CSS = ROOT / "app" / "static" / "css" / "visual-v2.css"
JS = ROOT / "app" / "static" / "js" / "email.js"
ROUTER = ROOT / "app" / "web" / "email.py"


def test_email_center_rebuilds_real_composition() -> None:
    source = TEMPLATE.read_text(encoding="utf-8")

    for contract in (
        "visual-email-center",
        "visual-email-heading",
        "visual-email-overview",
        "visual-email-mailboxes",
        "visual-email-metrics",
        "visual-email-statuses",
        "visual-email-workbench",
        "visual-email-workbench-header",
        "visual-email-filters",
        "visual-email-table-wrap",
        "visual-email-table",
        "visual-email-preview",
        "visual-email-compose",
        "Parametrizar caixas",
        "Aplicar filtros",
        "Inbox unificada",
    ):
        assert contract in source

    assert 'href="/v2-clean/admin/work-classification?view=channels"' in source
    assert 'data-email-preview-trigger="{{ thread.id }}"' in source
    assert 'aria-label="Conversas de email"' in source


def test_email_center_keeps_triage_preview_and_actions() -> None:
    source = THREAD.read_text(encoding="utf-8")

    for contract in (
        "email-reader-grid",
        "email-conversation",
        "email-triage-pane",
        "Guardar triagem",
        "Responder",
        "Concluir triagem",
        "Criar tarefa",
        "email-attachment-dialog",
    ):
        assert contract in source


def test_email_responsive_contract_uses_local_overflow_and_full_screen_preview() -> None:
    css = CSS.read_text(encoding="utf-8")

    for contract in (
        ".visual-email-metrics { display: grid;",
        "grid-template-columns: repeat(5,minmax(0,1fr));",
        ".visual-email-table-wrap { overflow-x: auto;",
        ".visual-email-table { min-width: 1180px; table-layout: fixed;",
        ".visual-email-filters { grid-template-columns: repeat(2,minmax(0,1fr));",
        'content: "Deslize para ver todas as colunas →"',
        ".visual-email-preview,.visual-email-compose { width: 100vw;",
        "height: 100dvh; max-height: 100dvh;",
        ":is(.visual-email-preview,.visual-email-thread-page) .email-save-triage { color: #fff; background: var(--cf-blue-600);",
        ":is(.visual-email-preview,.visual-email-thread-page) .email-conclude { color: #fff; background: var(--cf-teal-700);",
        ".email-modal-footer .button-link { min-height: 48px;",
    ):
        assert contract in css


def test_email_preview_keyboard_and_focus_return_contract() -> None:
    source = JS.read_text(encoding="utf-8")

    for contract in (
        "let previewTrigger = null",
        "previewTrigger = trigger || document.activeElement",
        'event.key !== "Enter" && event.key !== " "',
        "openPreview(element.dataset.emailPreview, element)",
        "openPreview(button.dataset.emailPreviewTrigger, button)",
        "previewTrigger.focus()",
        "return_context=${encodeURIComponent(location.pathname + location.search)}",
    ):
        assert contract in source


def test_email_full_page_return_context_is_local_and_feature_gated() -> None:
    source = ROUTER.read_text(encoding="utf-8")

    assert 'return_context.startswith("/v2-clean/email")' in source
    assert 'return_context.startswith("//")' in source
    assert '"foundation_ui_enabled": settings.visual_foundation_enabled' in source
    assert '"return_context": return_context' in source
