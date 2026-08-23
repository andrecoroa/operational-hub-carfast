from app.models.stock import (
    StockArticle,
    StockMovement,
    StockPurchaseOrder,
    StockReceipt,
)

ArticleRecord = StockArticle
MovementRecord = StockMovement
PurchaseOrderRecord = StockPurchaseOrder
ReceiptRecord = StockReceipt

__all__ = ["ArticleRecord", "MovementRecord", "PurchaseOrderRecord", "ReceiptRecord"]
