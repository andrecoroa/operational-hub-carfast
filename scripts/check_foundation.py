import sys
import tempfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from openpyxl import Workbook

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.api.routes.imports import (
    create_import_batch,
    create_import_error,
    create_import_raw_row,
    list_import_errors,
    list_import_raw_rows,
    update_import_batch,
)
from app.api.routes.auth import login, me
from app.api.routes.organization import create_team, list_organizational_units
from app.api.routes.tasks import (
    create_task,
    create_task_comment,
    list_task_comments,
    list_tasks,
    update_task,
)
from app.api.routes.vehicles import create_vehicle, list_vehicles, lookup_vehicle, update_vehicle
from app.core.security import verify_password
from app.models.admin import User
from app.models import Base
from app.models.imports import ImportRawRow
from app.models.vehicles import VehicleExternalSnapshot
from app.schemas.imports import ImportBatchCreate, ImportBatchUpdate, ImportErrorCreate, ImportRawRowCreate
from app.schemas.auth import LoginRequest
from app.schemas.organization import TeamCreate
from app.schemas.tasks import TaskCommentCreate, TaskCreate, TaskUpdate
from app.schemas.vehicles import VehicleCreate, VehicleUpdate
from app.services.bootstrap import seed_initial_data
from app.services.authorization import (
    get_user_authorized_unit_codes,
    get_user_permission_codes,
    user_has_authorized_unit,
    user_has_permission,
)
from app.services.rentway_fleet_importer import import_rentway_fleet_xlsx
from app.services.users import create_user
from sqlalchemy import func, select


def main() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session_local() as db:
        seed_initial_data(db)

        admin = create_user(
            db,
            name="Admin",
            email="admin@carfast.local",
            password="Secret123!",
            role_codes=["admin"],
            organizational_unit_codes=["carfast"],
        )
        db.commit()

        units = list_organizational_units(db)
        fleet = next(unit for unit in units if unit.code == "fleet")
        team = create_team(
            TeamCreate(
                code="fleet_followup",
                name="Follow-up Frota",
                organizational_unit_id=fleet.id,
            ),
            db,
        )
        task = create_task(
            TaskCreate(
                title="Verificar viatura",
                team_id=team.id,
                assigned_to_id=admin.id,
                entity_type="vehicle",
                entity_id="1",
            ),
            db,
            admin,
        )
        updated_task = update_task(task.id, TaskUpdate(status="done"), db, admin)
        task_comment = create_task_comment(
            task.id,
            TaskCommentCreate(comment="Feito."),
            db,
            admin,
        )

        vehicle = create_vehicle(
            VehicleCreate(
                plate="AA 00 AA",
                vin="VIN123",
                brand="Peugeot",
                model="208",
                lifecycle_status="active",
            ),
            db,
        )
        found_vehicle = lookup_vehicle(db, plate="AA00AA")
        updated_vehicle = update_vehicle(
            vehicle.id,
            VehicleUpdate(operational_status="free"),
            db,
        )
        listed_vehicles = list_vehicles(db, q="AA00AA", limit=50, offset=0)

        batch = create_import_batch(
            ImportBatchCreate(source_system="rentway", import_type="rentway_fleet"),
            db,
        )
        create_import_raw_row(
            batch.id,
            ImportRawRowCreate(
                row_number=2,
                external_reference="AA00AA",
                raw_json={"platenr": "AA00AA"},
            ),
            db,
        )
        create_import_error(
            batch.id,
            ImportErrorCreate(
                row_number=3,
                entity_type="vehicle",
                error_message="missing identifier",
            ),
            db,
        )
        updated_batch = update_import_batch(
            batch.id,
            ImportBatchUpdate(status="completed", total_rows=2, created_rows=1, error_rows=1),
            db,
        )

        assert team.code == "fleet_followup"
        assert db.get(User, admin.id).email == "admin@carfast.local"
        assert verify_password("Secret123!", admin.password_hash)
        assert "admin.manage" in get_user_permission_codes(db, admin)
        assert user_has_permission(db, admin, "vehicles.read")
        assert "carfast" in get_user_authorized_unit_codes(db, admin)
        assert user_has_authorized_unit(db, admin, "carfast")
        token = login(LoginRequest(email="admin@carfast.local", password="Secret123!"), db)
        profile = me(admin, db)
        assert token.token_type == "bearer"
        assert profile.email == "admin@carfast.local"
        assert "vehicles.read" in profile.permissions
        assert found_vehicle.id == vehicle.id
        assert updated_vehicle.operational_status == "free"
        assert len(listed_vehicles) == 1
        assert updated_batch.status == "completed"
        assert len(list_import_raw_rows(batch.id, db)) == 1
        assert len(list_import_errors(batch.id, db)) == 1
        assert updated_task.status == "done"
        assert updated_task.closed_at is not None
        assert task_comment.task_id == task.id
        assert len(list_task_comments(task.id, db)) == 1
        assert len(list_tasks(db, limit=50, offset=0)) == 1

        sample_path = Path(tempfile.gettempdir()) / "carfast_tmp_foundation_fleet.xlsx"
        create_sample_fleet_xlsx(sample_path)
        try:
            fleet_stats = import_rentway_fleet_xlsx(db, sample_path)
        finally:
            sample_path.unlink(missing_ok=True)
        assert fleet_stats["created_rows"] == 1
        assert db.scalar(select(func.count()).select_from(VehicleExternalSnapshot)) >= 1
        assert db.scalar(select(func.count()).select_from(ImportRawRow)) >= 1

    print("Foundation check passed.")


def create_sample_fleet_xlsx(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Frota Total"
    ws.append(
        [
            "matricula",
            "vin",
            "rentway_unitnr",
            "marca",
            "modelo",
            "versao",
            "ano",
            "estado_frota",
            "estado_operacional",
            "ativo",
        ]
    )
    ws.append(["BB 00 BB", "VIN456", "12345", "Peugeot", "208", "1.2", 2024, "Ativa", "Livre", 1])
    wb.save(path)


if __name__ == "__main__":
    main()
