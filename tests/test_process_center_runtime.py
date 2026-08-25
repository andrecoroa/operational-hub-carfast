import html
import re

from sqlalchemy import select

from app.models.admin import Permission, Role, RolePermission
from app.models.management_center import (
    ManagementAction,
    ManagementHistory,
    ManagementProcess,
    ManagementProcessAssociation,
    ManagementProcessType,
)
from app.models.organization import Team, TeamMember
from app.models.tasks import Task
from app.services.users import create_user


def _login(client, email: str) -> None:
    response = client.post(
        "/login",
        data={"email": email, "password": "Secret123!"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    notice = client.post(
        "/change-notice", data={"next_url": "/v2-clean/processes"}, follow_redirects=False
    )
    assert notice.status_code == 303


def _seed_process(db_session):
    process_type = ManagementProcessType(
        code="claims", name="Sinistros", description="Processos de sinistro", active=True
    )
    db_session.add(process_type)
    db_session.flush()
    process = ManagementProcess(
        process_type_id=process_type.id,
        internal_reference="SIN-TEST-001",
        title="Sinistro operacional de teste",
        status="open",
        phase="information_request",
        priority="critical",
        plate="AA-00-AA",
    )
    db_session.add(process)
    db_session.flush()
    return process_type, process


def _link_process_task(db_session, process, *, user_id=None, team_id=None):
    task = Task(
        title=f"Acompanhar {process.internal_reference}",
        task_type="management_task",
        status="open",
        priority="normal",
        assigned_to_id=user_id,
        team_id=team_id,
        created_by_id=user_id,
        assignment_mode="manual",
        assignment_state="assigned_user" if user_id else "assigned_team",
    )
    db_session.add(task)
    db_session.flush()
    db_session.add(
        ManagementProcessAssociation(
            process_id=process.id,
            entity_type="task",
            entity_id=task.id,
            association_role="execution",
            active=True,
            created_by_id=user_id,
        )
    )
    return task


def _create_capability_role(db_session, code: str, permission_codes: set[str]) -> None:
    role = Role(code=code, name=code.replace("_", " ").title(), active=True)
    db_session.add(role)
    db_session.flush()
    permissions = list(
        db_session.scalars(select(Permission).where(Permission.code.in_(permission_codes)))
    )
    assert {item.code for item in permissions} == permission_codes
    db_session.add_all(
        [RolePermission(role_id=role.id, permission_id=item.id) for item in permissions]
    )


def test_administrator_has_no_implicit_operational_process_access(
    authenticated_client,
):
    response = authenticated_client.get("/v2-clean/processes")

    assert response.status_code == 200
    assert "Sem acesso operacional" in response.text
    assert "Administrador não recebe acesso implícito" in response.text
    assert "Criar processo" not in response.text
    legacy = authenticated_client.get("/management-center", follow_redirects=False)
    assert legacy.status_code == 303
    assert legacy.headers["location"] == "/v2-clean"
    assert "Em acompanhamento" not in response.text
    assert "Categorias ativas" not in response.text


def test_executor_can_filter_open_create_and_return_to_the_same_queue(
    client, db_session
):
    executor = create_user(
        db_session,
        name="Executor Teste",
        email="executor.process@carfast.local",
        password="Secret123!",
        role_codes=["operator"],
        organizational_unit_codes=["carfast"],
    )
    _process_type, process = _seed_process(db_session)
    _link_process_task(db_session, process, user_id=executor.id)
    db_session.commit()
    _login(client, "executor.process@carfast.local")

    response = client.get("/v2-clean/processes?q=AA-00-AA&status=open&model=claims")
    assert response.status_code == 200
    assert "SIN-TEST-001" in response.text
    assert "Criar processo" in response.text
    assert "/v2-clean/tasks?workspace=management&amp;create=1" in response.text
    assert "Executor — pode criar e executar no seu âmbito." in response.text
    assert "Abrir gestão completa" not in response.text
    assert 'value="AA-00-AA"' in response.text
    token = html.unescape(re.search(r"return_context=([^\"]+)", response.text).group(1))

    detail = client.get(f"/v2-clean/processes/{process.id}?return_context={token}")
    assert detail.status_code == 200
    assert "/v2-clean/processes?q=AA-00-AA&amp;status=open&amp;model=claims#process-workbench" in detail.text


def test_process_queue_empty_and_invalid_filters_are_explicit(client, db_session):
    create_user(
        db_session,
        name="Executor Vazio",
        email="empty.process@carfast.local",
        password="Secret123!",
        role_codes=["operator"],
        organizational_unit_codes=["carfast"],
    )
    db_session.commit()
    _login(client, "empty.process@carfast.local")

    empty = client.get("/v2-clean/processes?q=nao-existe")
    invalid = client.get("/v2-clean/processes?status=unknown")

    assert "Sem processos nestes filtros" in empty.text
    assert "Filtros inválidos" in invalid.text
    assert "Nenhum processo foi consultado" in invalid.text


def test_team_and_operational_coordinators_receive_the_exact_scope_label(
    client, db_session
):
    _create_capability_role(
        db_session,
        "team_coordinator",
        {"management_center.read", "tasks.management.update", "navigation.processes.access"},
    )
    _create_capability_role(
        db_session,
        "operational_coordinator",
        {"management_center.read", "tasks.management.close", "navigation.processes.access"},
    )
    team_user = create_user(
        db_session,
        name="Coordenação Equipa",
        email="team.coordinator@carfast.local",
        password="Secret123!",
        role_codes=["team_coordinator"],
        organizational_unit_codes=["carfast"],
    )
    operational_user = create_user(
        db_session,
        name="Coordenação Operacional",
        email="operational.coordinator@carfast.local",
        password="Secret123!",
        role_codes=["operational_coordinator"],
        organizational_unit_codes=["carfast"],
    )
    team = Team(code="process-local", name="Lisboa", active=True)
    other_team = Team(code="process-other", name="Porto", active=True)
    db_session.add_all([team, other_team])
    db_session.flush()
    db_session.add(TeamMember(team_id=team.id, user_id=team_user.id))
    _type, local_process = _seed_process(db_session)
    local_process.internal_reference = "SIN-LISBOA"
    _link_process_task(db_session, local_process, team_id=team.id)
    other_process = ManagementProcess(
        process_type_id=_type.id,
        internal_reference="SIN-PORTO",
        title="Fora do âmbito localizado",
        status="open",
        phase="information_request",
        priority="normal",
    )
    db_session.add(other_process)
    db_session.flush()
    _link_process_task(db_session, other_process, team_id=other_team.id)
    db_session.commit()

    _login(client, "team.coordinator@carfast.local")
    team_page = client.get("/v2-clean/processes")
    assert "Coordenador de Equipa" in team_page.text
    assert "Lisboa" in team_page.text
    assert "SIN-LISBOA" in team_page.text
    assert "SIN-PORTO" not in team_page.text
    assert "Criar processo" not in team_page.text
    assert "Abrir gestão completa" not in team_page.text
    legacy_denied = client.get("/management-center", follow_redirects=False)
    assert legacy_denied.headers["location"] == "/v2-clean"
    scoped_detail = client.get(f"/v2-clean/processes/{local_process.id}")
    assert scoped_detail.status_code == 200
    assert "SIN-PORTO" not in scoped_detail.text

    client.get("/logout")
    _login(client, "operational.coordinator@carfast.local")
    operational_page = client.get("/v2-clean/processes")
    assert "Coordenador Operacional" in operational_page.text
    assert "acompanha a operação autorizada" in operational_page.text
    assert "SIN-LISBOA" in operational_page.text
    assert "SIN-PORTO" in operational_page.text
    assert "Abrir gestão completa" not in operational_page.text
    assert "Criar processo" not in operational_page.text


def test_manager_exception_requires_justification_and_is_audited(client, db_session):
    manager = create_user(
        db_session,
        name="Gestor Teste",
        email="manager.process@carfast.local",
        password="Secret123!",
        role_codes=["manager"],
        organizational_unit_codes=["carfast"],
    )
    _process_type, process = _seed_process(db_session)
    action = ManagementAction(
        process_id=process.id,
        title="Validar decisão excecional",
        status="open",
        mandatory=True,
    )
    db_session.add(action)
    db_session.commit()
    action_id = action.id
    process_id = process.id
    _login(client, "manager.process@carfast.local")

    detail = client.get(f"/v2-clean/processes/{process_id}")
    assert "Execução excecional de Gestor" in detail.text
    assert 'name="justification"' in detail.text

    rejected = client.post(
        f"/v2-clean/processes/{process_id}/actions/{action_id}/complete",
        data={"justification": "curta"},
        follow_redirects=False,
    )
    assert rejected.headers["location"].endswith("manager_justification_required")
    db_session.expire_all()
    assert db_session.get(ManagementAction, action_id).status == "open"

    accepted = client.post(
        f"/v2-clean/processes/{process_id}/actions/{action_id}/complete",
        data={"justification": "Intervenção necessária para desbloquear o processo."},
        follow_redirects=False,
    )
    assert accepted.status_code == 303
    assert accepted.headers["location"].endswith(f"/v2-clean/processes/{process_id}?updated=action")
    db_session.expire_all()
    assert db_session.get(ManagementAction, action_id).status == "done"
    history = db_session.scalar(
        select(ManagementHistory).where(
            ManagementHistory.process_id == process_id,
            ManagementHistory.user_id == manager.id,
            ManagementHistory.action == "action.completed",
        )
    )
    assert history is not None
    assert "Execução excecional de Gestor" in history.detail
