from sqlalchemy import delete, select

from app.models import Permission, Role, RolePermission
from app.services.bootstrap import seed_initial_data
from app.services.navigation import NAVIGATION_PERMISSIONS
from app.services.users import create_user


def _login(client, email: str, password: str = "Secret123!") -> None:
    client.post("/logout", follow_redirects=False)
    response = client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303
    notice = client.post(
        "/change-notice", data={"next_url": "/v2-clean"}, follow_redirects=False
    )
    assert notice.status_code == 303


def _role_with_permissions(db_session, code: str, permission_codes: set[str]) -> Role:
    role = Role(code=code, name=code.replace("_", " ").title(), active=True)
    db_session.add(role)
    db_session.flush()
    permissions = list(
        db_session.scalars(
            select(Permission).where(Permission.code.in_(permission_codes))
        )
    )
    assert {item.code for item in permissions} == permission_codes
    db_session.add_all(
        RolePermission(role_id=role.id, permission_id=item.id)
        for item in permissions
    )
    return role


def test_menu_and_server_guard_require_navigation_and_functional_access(
    client, db_session
):
    role = _role_with_permissions(
        db_session,
        "fleet_reader_without_menu",
        {"dashboard.read", "navigation.home.access", "vehicles.read"},
    )
    user = create_user(
        db_session,
        name="Leitor sem menu Frota",
        email="fleet.no.menu@carfast.local",
        password="Secret123!",
        role_codes=[role.code],
    )
    db_session.commit()

    _login(client, user.email)
    home = client.get("/v2-clean")
    assert home.status_code == 200
    assert 'href="/v2-clean/fleet"' not in home.text
    assert 'href="/v2-clean/tasks"' not in home.text

    denied = client.get("/v2-clean/fleet", follow_redirects=False)
    assert denied.status_code == 403
    assert "não autorizado" in denied.text


def test_module_access_allows_read_but_never_grants_write(client, db_session):
    role = _role_with_permissions(
        db_session,
        "fleet_navigation_reader",
        {
            "dashboard.read",
            "navigation.home.access",
            "navigation.fleet.access",
            "vehicles.read",
        },
    )
    user = create_user(
        db_session,
        name="Leitor Frota",
        email="fleet.read.only@carfast.local",
        password="Secret123!",
        role_codes=[role.code],
    )
    db_session.commit()

    _login(client, user.email)
    fleet = client.get("/v2-clean/fleet")
    assert fleet.status_code == 200
    assert 'href="/v2-clean/fleet"' in fleet.text
    assert "Novo processo" not in fleet.text

    denied_write = client.post(
        "/v2-clean/fleet/999/real-start", follow_redirects=False
    )
    assert denied_write.status_code == 303
    assert denied_write.headers["location"] == "/v2-clean?error=forbidden"


def test_super_admin_keeps_all_navigation_and_protected_access(authenticated_client):
    page = authenticated_client.get("/v2-clean")
    assert page.status_code == 200
    for href in (
        "/v2-clean/tasks",
        "/v2-clean/processes",
        "/v2-clean/workshop",
        "/v2-clean/fleet",
        "/v2-clean/stock",
        "/v2-clean/email",
        "/v2-clean/documentation/triage",
        "/v2-clean/admin",
    ):
        assert f'href="{href}"' in page.text
    assert authenticated_client.get("/v2-clean/admin/roles").status_code == 200


def test_navigation_seed_is_idempotent_and_does_not_restore_admin_choices(
    db_session,
):
    operator = db_session.scalar(select(Role).where(Role.code == "operator"))
    tasks_navigation = db_session.scalar(
        select(Permission).where(Permission.code == "navigation.tasks.access")
    )
    existing = db_session.scalar(
        select(RolePermission).where(
            RolePermission.role_id == operator.id,
            RolePermission.permission_id == tasks_navigation.id,
        )
    )
    assert existing is not None
    db_session.delete(existing)
    db_session.commit()

    seed_initial_data(db_session)

    assert (
        db_session.scalar(
            select(RolePermission).where(
                RolePermission.role_id == operator.id,
                RolePermission.permission_id == tasks_navigation.id,
            )
        )
        is None
    )


def test_builtin_profiles_receive_compatible_initial_module_access(db_session):
    rows = db_session.execute(
        select(Role.code, Permission.code)
        .join(RolePermission, RolePermission.role_id == Role.id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(Permission.code.in_(set(NAVIGATION_PERMISSIONS)))
    ).all()
    by_role: dict[str, set[str]] = {}
    for role_code, permission_code in rows:
        by_role.setdefault(role_code, set()).add(permission_code)

    assert by_role["admin"] == set(NAVIGATION_PERMISSIONS)
    assert "navigation.tasks.access" in by_role["operator"]
    assert "navigation.workshop.access" in by_role["viewer"]
    assert "navigation.admin.access" in by_role["user_admin"]


def test_role_admin_presents_friendly_navigation_section(authenticated_client):
    page = authenticated_client.get("/v2-clean/admin/roles")
    assert page.status_code == 200
    assert "Navegação e módulos" in page.text
    assert "navigation.tasks.access" in page.text
