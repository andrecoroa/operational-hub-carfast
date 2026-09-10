from app.stock_domain.compat import (
    ArticleRecord,
    MovementRecord,
    PurchaseOrderRecord,
    ReceiptRecord,
)
from app.stock_domain.contracts import (
    MaterialRequestReference,
    StockBalanceSnapshot,
    StockReference,
)
from app.stock_domain.facade import StockFacade
from app.stock_domain.manifest import STOCK_MANIFEST
from app.stock_domain.permissions import STOCK_PERMISSION_LEGACY_MAP, decide_stock_permission

__all__ = [
    "ArticleRecord",
    "MaterialRequestReference",
    "MovementRecord",
    "PurchaseOrderRecord",
    "ReceiptRecord",
    "STOCK_MANIFEST",
    "STOCK_PERMISSION_LEGACY_MAP",
    "StockBalanceSnapshot",
    "StockFacade",
    "StockReference",
    "decide_stock_permission",
]
