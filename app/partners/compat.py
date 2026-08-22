"""Storage compatibility aliases for the Partners boundary.

No table or ORM identity is duplicated. These aliases deliberately point at the
existing mapped class until an approved additive storage migration exists.
"""

from app.models.stock import StockSupplier as PartnerRecord

Supplier = PartnerRecord
StockSupplier = PartnerRecord

__all__ = ["PartnerRecord", "StockSupplier", "Supplier"]
