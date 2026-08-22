"""Seed only the current versioned baseline after Alembic created the schema.

This entry point is for a new installation. It must never import operational
CarFast data or copy a production database.
"""

from app.core.database import SessionLocal
from app.services.bootstrap import seed_catalogs, seed_permissions, seed_roles


def main() -> None:
    with SessionLocal() as db:
        seed_permissions(db)
        seed_roles(db)
        seed_catalogs(db)
        db.commit()
    print("Versioned installation baseline seeded.")


if __name__ == "__main__":
    main()
