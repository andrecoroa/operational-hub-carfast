import pytest

from app.services.users import create_user


ADMIN_RESIDUAL_ROUTES = (
    ("/v2-clean/admin/operations", "Operações e Service Desk"),
    ("/v2-clean/admin/organization", "Organização e equipas"),
    ("/v2-clean/admin/settings", "Parametrizações"),
    ("/v2-clean/admin/evolution", "Evolução da aplicação"),
    ("/v2-clean/admin/audit", "Auditoria"),
    ("/v2-clean/admin/integrations", "Integrações"),
    ("/v2-clean/admin/security", "Segurança e acessos"),
    ("/v2-clean/admin/workshop-models", "Modelos da Oficina"),
)


@pytest.mark.parametrize(("route", "heading"), ADMIN_RESIDUAL_ROUTES)
def test_admin_residual_routes_share_canonical_composition(authenticated_client, route, heading):
    response = authenticated_client.get(route)

    assert response.status_code == 200
    assert 'aria-label="Administração operacional"' in response.text
    assert 'aria-label="Conteúdos residuais da Administração"' in response.text
    assert f"<h1>{heading}</h1>" in response.text
    for expected_route, _ in ADMIN_RESIDUAL_ROUTES:
        assert f'href="{expected_route}"' in response.text
    assert 'href="/v2-clean/admin/setup"' in response.text


def test_admin_residual_navigation_has_one_current_page(authenticated_client):
    for route, _ in ADMIN_RESIDUAL_ROUTES:
        response = authenticated_client.get(route)
        assert f'href="{route}" aria-current="page" class="is-active"' in response.text


def test_admin_residual_routes_remain_fail_closed_for_anonymous_user(client):
    for route, _ in ADMIN_RESIDUAL_ROUTES:
        response = client.get(route, follow_redirects=False)
        assert response.status_code in {302, 303}
        assert "/login" in response.headers["location"]


def test_admin_residual_routes_remain_fail_closed_without_admin_manage(client, db_session):
    user = create_user(
        db_session,
        name="Operador sem administração",
        email="operator.admin-residual@carfast.local",
        password="Secret123!",
        role_codes=["operator"],
        organizational_unit_codes=["carfast"],
    )
    db_session.commit()
    assert client.post(
        "/login",
        data={"email": user.email, "password": "Secret123!"},
        follow_redirects=False,
    ).status_code == 303
    client.post("/change-notice", data={"next_url": "/v2-clean"}, follow_redirects=False)

    for route, _ in ADMIN_RESIDUAL_ROUTES:
        response = client.get(route, follow_redirects=False)
        assert response.status_code in {303, 403}


def test_admin_dialog_contract_moves_and_restores_focus():
    template = open("app/templates/clean_admin.html", encoding="utf-8").read()

    assert "lastAdminDialogTrigger = button" in template
    assert 'dialog.querySelector("input:not([type=\'hidden\']), select, textarea, button")?.focus()' in template
    assert 'dialog.addEventListener("close"' in template
    assert "lastAdminDialogTrigger?.focus()" in template


def test_admin_residual_empty_error_and_overflow_states_are_explicit():
    admin_template = open("app/templates/clean_admin.html", encoding="utf-8").read()
    models_template = open("app/templates/clean_workshop_models_admin.html", encoding="utf-8").read()
    stylesheet = open("app/static/css/app.css", encoding="utf-8").read()

    for marker in (
        "Sem áreas configuradas",
        "Sem equipas configuradas",
        "Sem catálogos configurados",
        "Sem modelos de Oficina",
        "Sem diagnósticos configurados",
    ):
        assert marker in admin_template + models_template
    assert 'request.query_params.get("error")' in admin_template
    assert ".clean-admin-content .table-wrap" in stylesheet
    assert "overflow-x: auto" in stylesheet
