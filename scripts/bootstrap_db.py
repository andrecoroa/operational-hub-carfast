import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.database import SessionLocal, engine  # noqa: E402
from app.models import Base  # noqa: E402
from app.services.bootstrap import seed_initial_data  # noqa: E402


def main() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_initial_data(db)
    print("CarFast v2 database bootstrapped.")


if __name__ == "__main__":
    main()
