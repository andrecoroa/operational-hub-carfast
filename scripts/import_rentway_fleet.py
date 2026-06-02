import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import SessionLocal, engine
from app.models import Base
from app.services.bootstrap import seed_initial_data
from app.services.rentway_fleet_importer import import_rentway_fleet_xlsx


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Rentway fleet XLSX into Operational Hub Carfast.")
    parser.add_argument("path", help="Path to the Rentway fleet XLSX file.")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_initial_data(db)
        stats = import_rentway_fleet_xlsx(db, args.path)
    print(stats)


if __name__ == "__main__":
    main()
