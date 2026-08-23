from app.platform.manifest import Contribution, ModuleManifest

STOCK_MANIFEST = ModuleManifest(
    code="stock",
    version="1",
    capabilities=("articles", "ledger", "purchasing", "inventory", "configuration"),
    dependencies=("core", "partners", "documents"),
    navigation=(
        Contribution("stock.articles", "stock.articles.read", "articles"),
        Contribution("stock.purchasing", "stock.purchasing.read", "purchasing"),
        Contribution("stock.inventory", "stock.inventory.read", "inventory"),
    ),
    administration=(Contribution("stock.configuration", "stock.configure", "configuration"),),
    settings=(Contribution("stock.locations", "stock.configure", "configuration"),),
    jobs=(Contribution("stock.minimums", "stock.ledger.read", "ledger"),),
)
