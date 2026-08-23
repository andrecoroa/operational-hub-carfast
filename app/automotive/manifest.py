from app.platform.manifest import Contribution, ModuleManifest

AUTOMOTIVE_MANIFEST = ModuleManifest(
    code="automotive",
    version="1",
    capabilities=("vehicles", "fleet", "workshop", "sales", "configuration"),
    dependencies=("core", "documents", "partners", "service-desk"),
    navigation=(
        Contribution("automotive.fleet", "automotive.fleet.read", "fleet"),
        Contribution("automotive.workshop", "automotive.workshop.read", "workshop"),
        Contribution("automotive.sales", "automotive.sales.read", "sales"),
    ),
    administration=(
        Contribution("automotive.configuration", "automotive.configure", "configuration"),
    ),
    settings=(
        Contribution("automotive.workshop.settings", "automotive.configure", "configuration"),
    ),
    jobs=(Contribution("automotive.source-projections", "automotive.fleet.write", "fleet"),),
)
