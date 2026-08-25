"""Assert that baseline seeding did not create CarFast operational records."""

from sqlalchemy import text

import app.models  # noqa: F401
from app.core.database import engine
from app.models.base import Base

# Versioned reference/configuration rows created by migrations or the reusable
# baseline bootstrap. Every other declared relation must remain empty.
CLEAN_INSTALL_REFERENCE_TABLES = frozenset(
    {
        "document_workflow_states",
        "installation_modules",
        "module_capabilities",
        "module_definitions",
        "module_dependencies",
        "permissions",
        "role_permissions",
        "roles",
        "service_desk_ticket_types",
        "settings_catalogs",
        "settings_values",
        "stock_categories",
        "stock_locations",
        "supplier_types",
        "work_departments",
        "work_queues",
    }
)
DECLARED_TABLES = frozenset(Base.metadata.tables)
if len(DECLARED_TABLES) < 163:
    raise RuntimeError(
        f"Clean-install relation inventory unexpectedly shrank: {len(DECLARED_TABLES)}"
    )
unknown_reference_tables = CLEAN_INSTALL_REFERENCE_TABLES - DECLARED_TABLES
if unknown_reference_tables:
    raise RuntimeError(
        f"Unknown clean-install reference tables: {sorted(unknown_reference_tables)}"
    )
OPERATIONAL_TABLES = tuple(sorted(DECLARED_TABLES - CLEAN_INSTALL_REFERENCE_TABLES))


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
    print(
        f"Clean installation verified across {len(OPERATIONAL_TABLES)} empty operational tables "
        f"and {len(CLEAN_INSTALL_REFERENCE_TABLES)} classified reference tables."
    )


if __name__ == "__main__":
    main()
