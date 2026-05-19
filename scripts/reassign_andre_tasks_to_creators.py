from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import SessionLocal
from app.models.admin import User
from app.models.audit import AuditLog
from app.models.tasks import Task, TaskComment, TaskHistory
from app.services.audit import record_audit


ANDRE_EMAILS = {"andrecoroa@daccordinvest.pt"}
ARCHIVE_STATUSES = {"closed", "cancelled", "no_action_needed"}
SYSTEM_CREATOR_NAMES = {"codex carfast"}

WAITING_REASON = "decision"
WAITING_DETAIL = "A aguardar decisao de Andre Coroa. Responsabilidade devolvida ao criador."
COMMENT_TEXT = "Migracao pontual: tarefa devolvida ao criador e colocada a aguardar decisao de Andre Coroa."
COMPLETED_ACTION = "task.one_off.andre_tasks_to_creators.completed"


@dataclass
class Candidate:
    task: Task
    creator: User | None
    skip_reason: str | None = None


def normalise(value: str | None) -> str:
    return (value or "").strip().lower()


def get_andre(db: Session) -> User:
    andre = db.scalar(select(User).where(User.email.in_(ANDRE_EMAILS)))
    if andre is None:
        raise SystemExit("Utilizador Andre nao encontrado.")
    return andre


def describe_user(user: User | None) -> str:
    if user is None:
        return "-"
    return f"{user.name} <{user.email}>"


def validate_creator(db: Session, task: Task, andre: User) -> tuple[User | None, str | None]:
    if task.created_by_id is None:
        return None, "sem criador registado"

    creator = db.get(User, task.created_by_id)
    if creator is None:
        return None, f"criador inexistente: {task.created_by_id}"
    if not creator.active:
        return None, f"criador inativo: {describe_user(creator)}"
    if creator.id == andre.id:
        return None, "criada pelo proprio Andre"
    if normalise(creator.name) in SYSTEM_CREATOR_NAMES:
        return None, f"criador tecnico excluido: {describe_user(creator)}"

    return creator, None


def find_candidates(db: Session, andre: User, limit: int | None = None) -> list[Candidate]:
    stmt = (
        select(Task)
        .where(Task.assigned_to_id == andre.id)
        .where(Task.closed_at.is_(None))
        .where(Task.status.not_in(ARCHIVE_STATUSES))
        .order_by(Task.id)
    )
    if limit:
        stmt = stmt.limit(limit)

    candidates: list[Candidate] = []
    for task in db.scalars(stmt):
        creator, skip_reason = validate_creator(db, task, andre)
        candidates.append(Candidate(task=task, creator=creator, skip_reason=skip_reason))
    return candidates


def already_completed(db: Session) -> bool:
    return db.scalar(select(AuditLog.id).where(AuditLog.action == COMPLETED_ACTION).limit(1)) is not None


def add_history(
    db: Session,
    task: Task,
    field_name: str,
    old_value: object,
    new_value: object,
    user_id: int,
) -> None:
    if old_value == new_value:
        return
    db.add(
        TaskHistory(
            task_id=task.id,
            user_id=user_id,
            field_name=field_name,
            old_value=None if old_value is None else str(old_value),
            new_value=None if new_value is None else str(new_value),
        )
    )


def apply_candidate(db: Session, candidate: Candidate, andre: User) -> None:
    task = candidate.task
    creator = candidate.creator
    if creator is None:
        return

    before = {
        "assigned_to_id": task.assigned_to_id,
        "status": task.status,
        "waiting_for_user_id": task.waiting_for_user_id,
        "waiting_for_team_id": task.waiting_for_team_id,
        "waiting_reason": task.waiting_reason,
        "waiting_reason_detail": task.waiting_reason_detail,
    }

    add_history(db, task, "assigned_to_id", task.assigned_to_id, creator.id, andre.id)
    add_history(db, task, "status", task.status, "waiting", andre.id)
    add_history(db, task, "waiting_for_user_id", task.waiting_for_user_id, andre.id, andre.id)
    add_history(db, task, "waiting_for_team_id", task.waiting_for_team_id, None, andre.id)
    add_history(db, task, "waiting_reason", task.waiting_reason, WAITING_REASON, andre.id)
    add_history(db, task, "waiting_reason_detail", task.waiting_reason_detail, WAITING_DETAIL, andre.id)

    task.assigned_to_id = creator.id
    task.status = "waiting"
    task.waiting_for_user_id = andre.id
    task.waiting_for_team_id = None
    task.waiting_reason = WAITING_REASON
    task.waiting_reason_detail = WAITING_DETAIL

    db.add(TaskComment(task_id=task.id, user_id=andre.id, comment=COMMENT_TEXT))

    after = {
        "assigned_to_id": task.assigned_to_id,
        "status": task.status,
        "waiting_for_user_id": task.waiting_for_user_id,
        "waiting_for_team_id": task.waiting_for_team_id,
        "waiting_reason": task.waiting_reason,
        "waiting_reason_detail": task.waiting_reason_detail,
    }
    record_audit(
        db,
        action="task.reassign_to_creator_waiting_decision",
        entity_type="task",
        entity_id=task.id,
        detail=COMMENT_TEXT,
        user_id=andre.id,
        before_json=before,
        after_json=after,
    )


def print_report(candidates: list[Candidate], apply: bool) -> None:
    mode = "APLICAR" if apply else "SIMULACAO"
    print(f"Modo: {mode}")
    print(f"Tarefas encontradas: {len(candidates)}")

    changed = 0
    skipped = 0
    for candidate in candidates:
        task = candidate.task
        if candidate.skip_reason:
            skipped += 1
            print(f"[IGNORAR] #{task.id} {task.title!r}: {candidate.skip_reason}")
            continue
        changed += 1
        print(
            f"[ALTERAR] #{task.id} {task.title!r}: "
            f"responsavel -> {describe_user(candidate.creator)}; "
            "estado -> A aguardar; motivo -> Decisao; "
            "aguarda por -> Andre Coroa"
        )

    print(f"Alteraveis: {changed}")
    print(f"Ignoradas: {skipped}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Migra pontualmente tarefas existentes atribuidas a Andre para o respetivo "
            "criador, deixando-as a aguardar decisao de Andre."
        )
    )
    parser.add_argument("--apply", action="store_true", help="Aplica as alteracoes. Sem isto faz apenas simulacao.")
    parser.add_argument("--force", action="store_true", help="Permite reaplicar mesmo existindo marca de conclusao.")
    parser.add_argument("--limit", type=int, default=None, help="Limita o numero de tarefas processadas.")
    args = parser.parse_args()

    with SessionLocal() as db:
        if args.apply and already_completed(db) and not args.force:
            print("Migracao ja executada anteriormente. Nada a fazer.")
            return

        andre = get_andre(db)
        candidates = find_candidates(db, andre, args.limit)
        print_report(candidates, args.apply)

        if not args.apply:
            db.rollback()
            return

        changed_count = 0
        skipped_count = 0
        for candidate in candidates:
            if candidate.skip_reason is None:
                apply_candidate(db, candidate, andre)
                changed_count += 1
            else:
                skipped_count += 1

        record_audit(
            db,
            action=COMPLETED_ACTION,
            entity_type="task",
            detail="Migracao pontual de tarefas de Andre para criadores concluida.",
            user_id=andre.id,
            after_json={
                "changed_count": changed_count,
                "skipped_count": skipped_count,
            },
        )

        db.commit()
        print("Alteracoes aplicadas.")


if __name__ == "__main__":
    main()
