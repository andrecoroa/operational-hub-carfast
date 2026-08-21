from __future__ import annotations


NAVIGATION_PERMISSIONS: dict[str, str] = {
    "navigation.home.access": "Aceder a Início",
    "navigation.tasks.access": "Aceder ao Centro de Tarefas",
    "navigation.processes.access": "Aceder ao Centro de Processos",
    "navigation.workshop.access": "Aceder à Oficina",
    "navigation.fleet.access": "Aceder à Frota",
    "navigation.stock.access": "Aceder ao Stock",
    "navigation.email.access": "Aceder ao Email",
    "navigation.documentation.access": "Aceder à Documentação",
    "navigation.admin.access": "Aceder à Administração",
}


# Used only once when a database is migrated (and when a built-in role is first
# created in a fresh database). Afterwards the navigation permissions are managed
# like every other role permission and are never reconstructed at application boot.
NAVIGATION_FUNCTIONAL_SOURCES: dict[str, set[str]] = {
    "navigation.home.access": {"dashboard.read"},
    "navigation.tasks.access": {
        "tasks.read",
        "tasks.operational.read",
        "tasks.operational.write",
        "tasks.workshop.read",
        "tasks.workshop.write",
        "tasks.audit.read",
        "tasks.audit.write",
        "tasks.administration.read",
        "tasks.administration.write",
        "tasks.management.read",
        "tasks.management.create",
        "tasks.management.update",
        "tasks.management.close",
        "tasks.recurring.manage",
    },
    "navigation.processes.access": {
        "management_center.read",
        "management_center.write",
    },
    "navigation.workshop.access": {"workshop.read", "workshop.write"},
    "navigation.fleet.access": {
        "vehicles.read",
        "vehicles.write",
        "fleet.commerce.manage",
    },
    "navigation.stock.access": {
        "stock.read",
        "stock.operate",
        "stock.manage",
        "stock.orders.manage",
        "stock.inventory.count",
        "stock.inventory.confirm",
        "stock.compatibility.manage",
        "stock.conference",
    },
    "navigation.email.access": {
        "email.read",
        "email.triage",
        "email.reply",
        "email.approve",
        "email.manage",
    },
    "navigation.documentation.access": {
        "documents.read",
        "documents.write",
        "imports.run",
        "imports.approve",
    },
    "navigation.admin.access": {
        "admin.manage",
        "users.manage",
        "settings.manage",
        "admin.dashboard.read",
        "admin.users.read",
        "admin.users.manage",
        "admin.users.credentials",
        "admin.roles.read",
        "admin.roles.manage",
        "admin.organization.read",
        "admin.organization.manage",
        "admin.settings.read",
        "admin.settings.manage",
        "admin.workshop_models.read",
        "admin.workshop_models.manage",
        "admin.workshop_models.publish",
        "admin.audit.read",
        "admin.audit.export",
        "admin.integrations.read",
        "admin.integrations.manage",
        "admin.integrations.credentials",
        "admin.security.read",
        "admin.security.manage",
    },
}


NAVIGATION_PATH_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("/v2-clean/tasks",), "navigation.tasks.access"),
    (("/v2-clean/processes",), "navigation.processes.access"),
    (("/v2-clean/workshop", "/v2-clean/workshop-entry"), "navigation.workshop.access"),
    (("/v2-clean/fleet",), "navigation.fleet.access"),
    (("/v2-clean/stock",), "navigation.stock.access"),
    (("/v2-clean/email",), "navigation.email.access"),
    (
        ("/v2-clean/documentation", "/v2-clean/documents", "/v2-clean/diagnostics"),
        "navigation.documentation.access",
    ),
    (("/v2-clean/admin",), "navigation.admin.access"),
)


def navigation_permission_for_path(path: str) -> str | None:
    if path == "/v2-clean":
        return "navigation.home.access"
    for prefixes, permission_code in NAVIGATION_PATH_RULES:
        if any(path == prefix or path.startswith(f"{prefix}/") for prefix in prefixes):
            return permission_code
    return None


def derived_navigation_permissions(functional_permissions: set[str]) -> set[str]:
    if "admin.manage" in functional_permissions:
        return set(NAVIGATION_PERMISSIONS)
    return {
        navigation_code
        for navigation_code, source_codes in NAVIGATION_FUNCTIONAL_SOURCES.items()
        if functional_permissions.intersection(source_codes)
    }
