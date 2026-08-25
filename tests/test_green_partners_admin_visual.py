from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_partners_directory_uses_shared_visual_composition(authenticated_client):
    response = authenticated_client.get("/v2-clean/suppliers?state=inactive&q=missing-record")

    assert response.status_code == 200
    assert 'class="partner-context-nav"' in response.text
    assert 'aria-current="page">Parceiros</a>' in response.text
    assert "Parceiros e fornecedores" in response.text
    assert "Sem fornecedores neste filtro." in response.text
    assert 'role="region" aria-label="Parceiros e fornecedores"' in response.text
    assert 'data-dialog-open="supplier-create"' in response.text


def test_partners_error_state_and_dialog_controls_are_explicit(authenticated_client):
    response = authenticated_client.get("/v2-clean/suppliers?error=invalid")

    assert response.status_code == 200
    assert "Não foi possível concluir: invalid." in response.text
    assert '<dialog id="supplier-create"' in response.text
    assert 'type="button" class="secondary" data-dialog-close' in response.text
    assert "showModal()" in response.text
    assert ".close()" in response.text


def test_admin_context_selects_roles_categories_and_email(authenticated_client):
    roles = authenticated_client.get("/v2-clean/admin/roles")
    categories = authenticated_client.get(
        "/v2-clean/admin/work-classification?view=structure"
    )
    email = authenticated_client.get(
        "/v2-clean/admin/work-classification?view=channels"
    )

    assert roles.status_code == categories.status_code == email.status_code == 200
    assert 'aria-current="page">Perfis e permissões</a>' in roles.text
    assert 'aria-current="page">Categorias</a>' in categories.text
    assert 'data-work-admin-view="structure"' in categories.text
    assert 'aria-current="page">Email</a>' in email.text
    assert 'data-work-admin-view="channels"' in email.text


def test_partner_context_nav_is_rbac_gated_and_keyboard_native():
    template = (ROOT / "app/templates/_supplier_context_nav.html").read_text(
        encoding="utf-8"
    )
    suppliers = (ROOT / "app/templates/clean_suppliers.html").read_text(
        encoding="utf-8"
    )
    styles = (ROOT / "app/static/css/visual-v2.css").read_text(encoding="utf-8")

    assert "nav_has_permission(request" in template
    assert "nav_can" not in template
    assert 'href="/v2-clean/admin/work-classification?view=channels"' in template
    assert "tabindex=\"0\"" in suppliers
    assert "scrollbar-width:none" in styles
    assert ".partner-context-nav a{display:inline-flex" in styles
    assert "min-height:44px" in styles


def test_native_dialogs_keep_escape_behavior_without_custom_key_traps():
    for relative in (
        "app/templates/clean_suppliers.html",
        "app/templates/clean_supplier_detail.html",
        "app/templates/clean_suppliers_admin.html",
    ):
        template = (ROOT / relative).read_text(encoding="utf-8")
        assert "<dialog" in template
        assert "showModal()" in template
        assert "keydown" not in template
        assert "preventDefault" not in template
