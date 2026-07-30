from sqlalchemy import select

from app.models.audit import AuditLog
from app.services.users import create_user


def _create_user(db_session, *, email: str, role: str):
    user = create_user(
        db_session,
        name=email.split("@", 1)[0],
        email=email,
        password="Secret12345!",
        role_codes=[role],
        organizational_unit_codes=["carfast"],
    )
    db_session.commit()
    return user


def _login_and_acknowledge(client, email: str) -> None:
    response = client.post(
        "/login",
        data={"email": email, "password": "Secret12345!"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/v2-clean"
    notice = client.post(
        "/change-notice",
        data={"next_url": "/v2-clean"},
        follow_redirects=False,
    )
    assert notice.status_code == 303
    assert notice.headers["location"] == "/v2-clean"


def test_login_and_legacy_chooser_default_to_clean(client):
    response = client.post(
        "/login",
        data={
            "email": "admin.tests@carfast.local",
            "password": "Secret123!",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/v2-clean"

    notice = client.post(
        "/change-notice",
        data={"next_url": "/v2-clean"},
        follow_redirects=False,
    )
    assert notice.status_code == 303
    chooser = client.get("/choose-experience", follow_redirects=False)
    assert chooser.status_code == 303
    assert chooser.headers["location"] == "/v2-clean"


def test_admin_sidebar_uses_discreet_legacy_icon(authenticated_client):
    response = authenticated_client.get("/v2-clean")

    assert response.status_code == 200
    assert 'class="sidebar-legacy-link"' in response.text
    assert 'title="Abrir versão anterior"' in response.text
    assert 'target="_blank"' in response.text
    assert ">CarFast atual<" not in response.text
    assert 'class="sidebar-collapse-toggle"' in response.text


def test_functional_admin_can_open_legacy_and_entry_is_audited(
    client,
    db_session,
):
    email = "functional.legacy@carfast.local"
    _create_user(db_session, email=email, role="functional_admin")
    _login_and_acknowledge(client, email)

    clean_page = client.get("/v2-clean")
    assert clean_page.status_code == 200
    assert 'title="Abrir versão anterior"' in clean_page.text

    response = client.get(
        "/switch-experience/current",
        params={
            "origin": "/v2-clean/admin/settings?tab=catalogs",
            "destination": "/",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    audit = db_session.scalar(
        select(AuditLog)
        .where(AuditLog.action == "web.legacy_experience.open")
        .order_by(AuditLog.id.desc())
    )
    assert audit is not None
    assert audit.user_id is not None
    assert audit.created_at is not None
    assert audit.after_json == {
        "origin": "/v2-clean/admin/settings?tab=catalogs",
        "destination_route": "/",
    }


def test_operator_cannot_see_or_open_legacy_experience(client, db_session):
    email = "operator.legacy@carfast.local"
    operator = _create_user(db_session, email=email, role="operator")
    _login_and_acknowledge(client, email)

    clean_page = client.get("/v2-clean")
    assert clean_page.status_code == 200
    assert 'title="Abrir versão anterior"' not in clean_page.text

    switch = client.get(
        "/switch-experience/current",
        params={"origin": "/v2-clean", "destination": "/"},
        follow_redirects=False,
    )
    assert switch.status_code == 303
    assert switch.headers["location"] == "/v2-clean?error=legacy_access_denied"

    direct = client.get("/", follow_redirects=False)
    assert direct.status_code == 303
    assert direct.headers["location"] == "/v2-clean?error=legacy_access_denied"
    assert (
        db_session.scalar(
            select(AuditLog).where(
                AuditLog.action == "web.legacy_experience.open",
                AuditLog.user_id == operator.id,
            )
        )
        is None
    )


def test_direct_legacy_entry_for_admin_is_audited(
    authenticated_client,
    db_session,
):
    direct = authenticated_client.get(
        "/fleet?scope=active",
        headers={"referer": "http://testserver/v2-clean/fleet"},
        follow_redirects=False,
    )

    assert direct.status_code == 200
    audit = db_session.scalar(
        select(AuditLog)
        .where(AuditLog.action == "web.legacy_experience.open")
        .order_by(AuditLog.id.desc())
    )
    assert audit is not None
    assert audit.after_json["origin"] == "/v2-clean/fleet"
    assert audit.after_json["destination_route"] == "/fleet?scope=active"


def test_clean_return_urls_cannot_escape_to_previous_experience(
    authenticated_client,
    db_session,
):
    from app.models.tasks import Task

    task = Task(
        title="Regresso Clean",
        status="new",
        priority="normal",
        task_type="operational_task",
        source="v2_clean",
    )
    db_session.add(task)
    db_session.commit()

    response = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/close",
        data={"return_url": "/task-board"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/v2-clean/tasks?")
