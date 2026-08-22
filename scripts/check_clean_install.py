"""Assert that baseline seeding did not create CarFast operational records."""

from sqlalchemy import text

from app.core.database import engine

OPERATIONAL_TABLES = (
    "audit_log",
    "documents",
    "email_channels",
    "email_attachments",
    "email_messages",
    "email_threads",
    "quick_records",
    "stock_movements",
    "stock_suppliers",
    "tasks",
    "teams",
    "vehicle_sale_leads",
    "vehicle_sale_proposals",
    "vehicles",
    "organizational_units",
    "workshop_phased_processes",
    "workshop_processes",
)


def main() -> None:
    unexpected: dict[str, int] = {}
    with engine.connect() as connection:
        for table in OPERATIONAL_TABLES:
            count = connection.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one()
            if count:
                unexpected[table] = count
    if unexpected:
        details = ", ".join(f"{table}={count}" for table, count in unexpected.items())
        raise SystemExit(f"Clean installation contains operational data: {details}")
    print(f"Clean installation verified across {len(OPERATIONAL_TABLES)} operational tables.")


if __name__ == "__main__":
    main()
