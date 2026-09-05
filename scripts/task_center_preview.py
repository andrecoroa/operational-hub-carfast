"""Run the approved Task Center against an isolated deterministic SQLite fixture."""

from __future__ import annotations

import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path


PREVIEW_ROOT = Path(os.environ.get("CARFAST_TASK_PREVIEW_ROOT", ".task-center-preview")).resolve()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
PREVIEW_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("DATABASE_URL", f"sqlite+pysqlite:///{(PREVIEW_ROOT / 'fixture.db').as_posix()}")
os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("APP_SECRET_KEY", "synthetic-task-center-preview-only")
os.environ.setdefault("VISUAL_FOUNDATION_ENABLED", "true")
os.environ.setdefault("TASK_CASES_ENABLED", "true")
os.environ["TASK_DECISIONS_ENABLED"] = "true"
os.environ.setdefault("EMAIL_INBOUND_ENABLED", "false")
os.environ.setdefault("EMAIL_OUTBOUND_ENABLED", "false")

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Base,
    Permission,
    Role,
    RolePermission,
    RoleWorkScope,
    Task,
    TaskCase,
    TaskDecision,
    Team,
    TeamMember,
    User,
    UserRole,
    WorkCategory,
    WorkDepartment,
    WorkQueue,
    WorkSubcategory,
)
from app.services.bootstrap import seed_initial_data  # noqa: E402
from app.services.users import create_user  # noqa: E402


FIXTURES = (
    ("Validar documentação da reserva sintética", "Documentação", "high", "new", -1, False),
    ("Confirmar fatura e arquivo do dossier", "Documentação", "normal", "in_execution", 0, False),
    ("Rever contrato recebido por email", "Documentação", "normal", "waiting", 2, False),
    ("Preparar entrada de viatura na oficina", "Oficina", "high", "new", 1, False),
    ("Confirmar peças da reparação", "Oficina", "normal", "in_execution", 3, False),
    ("Validar participação de sinistro", "Sinistros", "high", "waiting", 4, False),
    ("Arquivar pedido concluído", "Documentação", "normal", "closed", -4, True),
)


def prepare_fixture() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_initial_data(db)
        user = db.scalar(select(User).where(User.email == "executor.preview@carfast.local"))
        if not user:
            user = create_user(
                db,
                name="Executor Preview",
                email="executor.preview@carfast.local",
                password="PreviewOnly123!",
                role_codes=["admin"],
                organizational_unit_codes=["carfast"],
            )
            db.flush()
        user_role_id = db.scalar(
            select(UserRole.role_id).where(UserRole.user_id == user.id)
        )
        for code in ("tasks.request_decision", "tasks.resolve_decision"):
            permission = db.scalar(select(Permission).where(Permission.code == code))
            if permission and not db.scalar(
                select(RolePermission).where(
                    RolePermission.role_id == user_role_id,
                    RolePermission.permission_id == permission.id,
                )
            ):
                db.add(
                    RolePermission(
                        role_id=user_role_id,
                        permission_id=permission.id,
                    )
                )
        queue_user = db.scalar(
            select(User).where(User.email == "queue.preview@carfast.local")
        )
        if not queue_user:
            role = Role(
                code="queue_preview",
                name="Queue Preview",
                description="Synthetic queue authorization evidence",
                active=True,
            )
            db.add(role)
            db.flush()
            for code in (
                "navigation.tasks.access", "tasks.read", "tasks.operational.read",
                "tasks.operational.write", "tasks.audit.read", "cases.read",
                "cases.create", "cases.update", "tasks.recurring.manage",
            ):
                permission = db.scalar(select(Permission).where(Permission.code == code))
                if not permission:
                    permission = Permission(code=code, name=code)
                    db.add(permission)
                    db.flush()
                db.add(RolePermission(role_id=role.id, permission_id=permission.id))
            queue_user = create_user(
                db,
                name="Queue Preview",
                email="queue.preview@carfast.local",
                password="PreviewOnly123!",
                role_codes=["operator", role.code],
                organizational_unit_codes=["carfast"],
            )
            db.flush()
        queue = db.scalar(select(WorkQueue).where(WorkQueue.code == "tasks_support"))
        support_team = db.scalar(select(Team).where(Team.code == "support"))
        if support_team and not db.scalar(
            select(TeamMember).where(
                TeamMember.team_id == support_team.id,
                TeamMember.user_id == queue_user.id,
            )
        ):
            db.add(TeamMember(team_id=support_team.id, user_id=queue_user.id))
        queue_role = db.scalar(select(Role).where(Role.code == "queue_preview"))
        if queue_role and not db.scalar(
            select(RoleWorkScope).where(
                RoleWorkScope.role_id == queue_role.id,
                RoleWorkScope.queue_id == queue.id,
                RoleWorkScope.department_id.is_(None),
                RoleWorkScope.category_id.is_(None),
                RoleWorkScope.subcategory_id.is_(None),
            )
        ):
            db.add(
                RoleWorkScope(
                    role_id=queue_role.id,
                    queue_id=queue.id,
                    can_read=True,
                    can_assume=True,
                )
            )
        department = db.scalar(
            select(WorkDepartment).where(WorkDepartment.queue_id == queue.id)
        )
        category = db.scalar(
            select(WorkCategory).where(
                WorkCategory.department_id == department.id,
                WorkCategory.code == "synthetic_preview",
            )
        )
        if not category:
            category = WorkCategory(
                department_id=department.id,
                code="synthetic_preview",
                name="Operação sintética",
                active=True,
            )
            db.add(category)
            db.flush()
            db.add(
                WorkSubcategory(
                    category_id=category.id,
                    code="synthetic_triage",
                    name="Triagem sintética",
                    active=True,
                )
            )
        if not db.scalar(select(Task.id).where(Task.source == "synthetic_task_center_preview")):
            now = datetime.now(UTC)
            fixture_tasks: list[Task] = []
            for index, (title, category, priority, status, day_delta, closed) in enumerate(FIXTURES, 1):
                task = Task(
                        title=title,
                        description=f"Caso sintético determinístico {index}. Sem dados reais nem efeitos externos.",
                        task_type="workshop_task" if category == "Oficina" else "operational_task",
                        source="synthetic_task_center_preview",
                        category=category,
                        subcategory="Validação",
                        status=status,
                        priority=priority,
                        assigned_to_id=None if index in {1, 4} else queue_user.id,
                        created_by_id=queue_user.id,
                        due_on=date.today() + timedelta(days=day_delta),
                        closed_at=now if closed else None,
                    )
                db.add(task)
                fixture_tasks.append(task)
            db.flush()
            task_case = TaskCase(
                title="Dossier sintético de preparação",
                description="Caso persistido usado apenas na evidência local.",
                workspace="tasks_support",
                work_queue_id=queue.id,
                created_by_id=queue_user.id,
            )
            db.add(task_case)
            db.flush()
            fixture_tasks[0].case_id = task_case.id
            fixture_tasks[1].case_id = task_case.id
        if support_team:
            for task in db.scalars(
                select(Task).where(
                    Task.source == "synthetic_task_center_preview",
                    Task.assigned_to_id.is_(None),
                )
            ):
                task.team_id = support_team.id
        decision_task = db.scalar(
            select(Task).where(
                Task.source == "synthetic_task_center_preview",
                Task.title == "Validar documentação da reserva sintética",
            )
        )
        if decision_task and not db.scalar(
            select(TaskDecision.id).where(TaskDecision.task_id == decision_task.id)
        ):
            decision_task.status = "waiting_decision"
            db.add(
                TaskDecision(
                    task_id=decision_task.id,
                    requested_by_id=queue_user.id,
                    decider_id=user.id,
                    decision_needed="Aprovar reserva sintética",
                    recommendation="Aprovar",
                    impact_value="Sem impacto real",
                    previous_task_status="new",
                    status="pending",
                )
            )
        db.commit()


prepare_fixture()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("CARFAST_TASK_PREVIEW_PORT", "18766")),
        log_level="warning",
    )
