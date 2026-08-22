"""Partners & Suppliers application boundary.

The current storage remains ``stock_suppliers``. Consumers must use this package so
that ownership can evolve without changing stable partner references or historical IDs.
"""

from app.partners.compat import PartnerRecord, StockSupplier, Supplier
from app.partners.contracts import PartnerReference, PartnerSummary
from app.partners.facade import PartnersFacade
from app.partners.manifest import PARTNERS_MANIFEST
from app.partners.permissions import decide_partner_permission

__all__ = [
    "PARTNERS_MANIFEST",
    "PartnerRecord",
    "PartnerReference",
    "PartnerSummary",
    "PartnersFacade",
    "StockSupplier",
    "Supplier",
    "decide_partner_permission",
]
