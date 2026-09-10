"""Reconcile only mandatory technical email identities for an existing runtime."""

from app.core.database import SessionLocal
from app.services.bootstrap import seed_email_channels


def main() -> None:
    with SessionLocal() as db:
        seed_email_channels(db, only_codes={"central"})
        db.commit()
    print("Mandatory email identities reconciled.")


if __name__ == "__main__":
    main()
