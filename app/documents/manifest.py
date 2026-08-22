from app.platform.manifest import Contribution, ModuleManifest

DOCUMENTS_MANIFEST = ModuleManifest(
    code="documents",
    version="1",
    capabilities=("records", "ingestion", "workflow", "retention", "configuration"),
    dependencies=("core",),
    navigation=(Contribution("documents.records", "documents.records.read", "records"),),
    administration=(
        Contribution("documents.configuration", "documents.records.configure", "configuration"),
    ),
    settings=(Contribution("documents.retention", "documents.retention.configure", "retention"),),
    jobs=(Contribution("documents.ingestion", "documents.records.create", "ingestion"),),
)
