from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy.orm import Session

from app.schemas.stock import StockMovementCreate
from app.services.stock import create_manual_movement, reverse_movement, stock_balances
from app.stock_domain.compat import ArticleRecord, MovementRecord
from app.stock_domain.contracts import StockBalanceSnapshot, StockReference


class StockFacade:
    """Application boundary over the immutable Stock ledger and compatibility storage."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def article(self, reference: StockReference | int) -> ArticleRecord | None:
        article_id = reference.id if isinstance(reference, StockReference) else reference
        return self.db.get(ArticleRecord, article_id)

    def movement(self, reference: StockReference | int) -> MovementRecord | None:
        movement_id = reference.id if isinstance(reference, StockReference) else reference
        return self.db.get(MovementRecord, movement_id)

    def balances(self, article_ids: Iterable[int] = ()) -> list[StockBalanceSnapshot]:
        rows = stock_balances(self.db, article_ids=list(article_ids) or None)
        return [
            StockBalanceSnapshot(
                StockReference("article", article_id), location_id, Decimal(quantity)
            )
            for (article_id, location_id), quantity in sorted(rows.items())
        ]

    def record_movement(
        self, command: StockMovementCreate, *, user_id: int | None
    ) -> MovementRecord:
        return create_manual_movement(self.db, command=command, user_id=user_id)

    def reverse(
        self, movement: MovementRecord, *, reason: str, user_id: int | None
    ) -> MovementRecord:
        return reverse_movement(self.db, movement=movement, reason=reason, user_id=user_id)
