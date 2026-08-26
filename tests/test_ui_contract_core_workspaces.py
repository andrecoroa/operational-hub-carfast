from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "app/static/css/ui-contract-v1.css").read_text(encoding="utf-8")
EMAIL = (ROOT / "app/templates/clean_email_inbox.html").read_text(encoding="utf-8")
EMAIL_JS = (ROOT / "app/static/js/email.js").read_text(encoding="utf-8")
DOCUMENTS = (ROOT / "app/templates/clean_documentation_center.html").read_text(encoding="utf-8")
ADMIN = (ROOT / "app/templates/clean_admin.html").read_text(encoding="utf-8")
PARTNERS = (ROOT / "app/templates/clean_suppliers.html").read_text(encoding="utf-8")


def test_email_uses_same_page_list_preview_contract() -> None:
    assert "ui-email-list-preview" in EMAIL
    assert "ui-context-preview" in EMAIL
    assert "id=\"email-preview-dialog\"" in EMAIL
    assert "dialog.showModal();" in EMAIL_JS
    assert "const previewRoot = usePanel ? previewPanel : dialog" in EMAIL_JS
    assert "<dialog" in EMAIL and "<dialog" not in EMAIL.split("ui-email-list-preview", 1)[1].split("</div>{% if foundation_ui_enabled %}</section>", 1)[0]
    assert ".ui-email-list-preview { display: grid;" in CSS


def test_documents_keep_canonical_workbench_and_topbar() -> None:
    assert 'visual_page = "Documentação"' in DOCUMENTS
    assert "ui-list-preview-workbench" in DOCUMENTS
    assert "doc-arch-table" in DOCUMENTS
    assert "Filas de trabalho" in DOCUMENTS


def test_admin_uses_master_detail_system_context() -> None:
    assert "ui-admin-master-detail" in ADMIN
    assert "admin-model-columns" in ADMIN
    assert "clean-admin-role-workspace" in ADMIN


def test_dashboard_and_partner_density_are_shared_not_route_local() -> None:
    assert "ui-partner-directory" in PARTNERS
    assert ".visual-dashboard-metrics .visual-metric-card" in CSS
    assert ".supplier-table :is(th,td)" in CSS
    assert ".supplier-filter :is(input,select,button)" in CSS


def test_responsive_preview_and_master_detail_collapse() -> None:
    assert ".ui-context-preview { display: none; }" in CSS
    assert ".ui-context-preview[open]" not in CSS
    assert ".admin-model-columns { grid-template-columns: repeat(2,minmax(0,1fr)); }" in CSS
    assert ".clean-admin-role-workspace { grid-template-columns: minmax(0,1fr); }" in CSS
