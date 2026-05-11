from app.core.database import SessionLocal, engine
from app.models import Base
from app.services.bootstrap import seed_initial_data


def main() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_initial_data(db)
    print("CarFast v2 database bootstrapped.")


if __name__ == "__main__":
    main()

