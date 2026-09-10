from tests.conftest import TEST_ADMIN_EMAIL, TEST_ADMIN_PASSWORD


def test_clean_process_center_keeps_admin_outside_operational_content(client):
    login = client.post(
        "/login",
        data={"email": TEST_ADMIN_EMAIL, "password": TEST_ADMIN_PASSWORD},
        follow_redirects=False,
    )
    assert login.status_code == 303

    notice = client.post("/change-notice", data={"next_url": "/"}, follow_redirects=False)
    assert notice.status_code == 303

    response = client.get("/v2-clean/processes")

    assert response.status_code == 200
    assert "Centro de Processos" in response.text
    assert "Sem acesso operacional" in response.text
    assert "Administrador não recebe acesso implícito" in response.text
    assert "Em acompanhamento" not in response.text
    assert "Criar processo" not in response.text
