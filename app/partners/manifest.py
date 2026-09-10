from app.platform.manifest import Contribution, ModuleManifest

PARTNERS_MANIFEST = ModuleManifest(
    code="partners",
    version="1",
    capabilities=("records", "classification", "configuration"),
    dependencies=("core",),
    navigation=(
        Contribution(
            "partners.records",
            permission="partners.records.read",
            capability="records",
        ),
    ),
    administration=(
        Contribution(
            "partners.configuration",
            permission="partners.records.configure",
            capability="configuration",
        ),
    ),
    settings=(
        Contribution(
            "partners.classification",
            permission="partners.records.configure",
            capability="classification",
        ),
    ),
)
