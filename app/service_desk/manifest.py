from app.platform.manifest import Contribution, ModuleManifest

SERVICE_DESK_MANIFEST = ModuleManifest(
    code="service_desk",
    version="1",
    capabilities=("tasks", "processes", "email", "configuration"),
    dependencies=("core",),
    navigation=(
        Contribution("service_desk.tasks", "service_desk.tasks.read", "tasks"),
        Contribution("service_desk.processes", "service_desk.processes.read", "processes"),
        Contribution("service_desk.email", "service_desk.email.read", "email"),
    ),
    administration=(
        Contribution("service_desk.configuration", "service_desk.configure", "configuration"),
    ),
    settings=(Contribution("service_desk.sla", "service_desk.configure", "configuration"),),
    jobs=(Contribution("service_desk.email.ingestion", "service_desk.email.manage", "email"),),
)
