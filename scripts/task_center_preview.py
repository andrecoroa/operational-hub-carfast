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
os.environ.setdefault("EMAIL_INBOUND_ENABLED", "false")
os.environ.setdefault("EMAIL_OUTBOUND_ENABLED", "false")

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, Task, User  # noqa: E402
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
        if not db.scalar(select(Task.id).where(Task.source == "synthetic_task_center_preview")):
            now = datetime.now(UTC)
            for index, (title, category, priority, status, day_delta, closed) in enumerate(FIXTURES, 1):
                db.add(
                    Task(
                        title=title,
                        description=f"Caso sintético determinístico {index}. Sem dados reais nem efeitos externos.",
                        task_type="workshop_task" if category == "Oficina" else "operational_task",
                        source="synthetic_task_center_preview",
                        category=category,
                        subcategory="Validação",
                        status=status,
                        priority=priority,
                        assigned_to_id=None if index in {1, 4} else user.id,
                        created_by_id=user.id,
                        due_on=date.today() + timedelta(days=day_delta),
                        closed_at=now if closed else None,
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
