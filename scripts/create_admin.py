import getpass
import os
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import SessionLocal, engine
from app.models import Base
from app.models.admin import User
from app.services.bootstrap import seed_initial_data
from app.services.users import create_user


def main() -> None:
    Base.metadata.create_all(bind=engine)
    name = os.environ.get("CARFAST_ADMIN_NAME", "Administrador")
    email = os.environ.get("CARFAST_ADMIN_EMAIL", "admin@carfast.local")
    password = os.environ.get("CARFAST_ADMIN_PASSWORD")
    if not password:
        password = getpass.getpass("Admin password: ")

    with SessionLocal() as db:
        seed_initial_data(db)
        existing = db.scalar(select(User).where(User.email == email.strip().lower()))
        if existing:
            print(f"Admin already exists: {existing.email}")
            return
        user = create_user(
            db,
            name=name,
            email=email,
            password=password,
            role_codes=["admin"],
            organizational_unit_codes=["carfast"],
        )
        db.commit()
        print(f"Admin created: {user.email}")


if __name__ == "__main__":
    main()

