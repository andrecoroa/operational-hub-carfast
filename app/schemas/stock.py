from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _integer_quantity(value: Decimal) -> Decimal:
    if value != value.to_integral_value():
        raise ValueError("As quantidades de Stock têm de ser inteiras.")
    return value


class StockInvoiceImportCreate(BaseModel):
    document_id: int
    document_url: str | None = None
    classification: Literal["stock_invoice"] = "stock_invoice"
    extracted_data: dict[str, Any] = Field(default_factory=dict)


class StockInvoiceLineReview(BaseModel):
    line_number: int = Field(ge=1)
    supplier_ref: str | None = None
    description: str = Field(min_length=1)
    quantity: Decimal = Field(gt=0)
    unit: str = Field(min_length=1, max_length=30)
    unit_cost: Decimal = Field(ge=0)
    discount: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    eco_value: Decimal = Field(default=Decimal("0"), ge=0)
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    line_total: Decimal | None = Field(default=None, ge=0)

    _quantity_is_integer = field_validator("quantity")(_integer_quantity)


class StockInvoiceReview(BaseModel):
    supplier_id: int | None = None
    supplier_tax_id: str | None = None
    supplier_name: str = Field(min_length=1)
    supplier_email: str | None = None
    supplier_phone: str | None = None
    supplier_address: str | None = None
    payment_terms: str | None = None
    invoice_number: str = Field(min_length=1)
    invoice_date: date | None = None
    due_date: date | None = None
    net_total: Decimal | None = Field(default=None, ge=0)
    tax_total: Decimal | None = Field(default=None, ge=0)
    gross_total: Decimal | None = Field(default=None, ge=0)
    content_hash: str | None = Field(default=None, max_length=64)
    lines: list[StockInvoiceLineReview] = Field(min_length=1)


class StockReceiptLineCreate(BaseModel):
    article_id: int
    supplier_ref: str | None = None
    accepted_quantity: Decimal = Field(gt=0)
    unit_cost: Decimal | None = Field(default=None, ge=0)
    lot: str | None = None
    divergence_reason: str | None = None
    purchase_order_line_id: int | None = None

    _quantity_is_integer = field_validator("accepted_quantity")(_integer_quantity)


class StockReceiptCreate(BaseModel):
    location_id: int
    supplier_id: int | None = None
    source_type: Literal["delivery_note", "invoice", "manual"]
    source_reference: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=120)
    effective_date: date = Field(default_factory=date.today)
    purchase_order_id: int | None = None
    delivery_document_id: int | None = None
    manual_reason: str | None = None
    responsible_name: str | None = None
    notes: str | None = None
    invoice_import_ids: list[int] = Field(default_factory=list)
    lines: list[StockReceiptLineCreate] = Field(min_length=1)

    @model_validator(mode="after")
    def source_reference_matches_type(self):
        if self.source_type != "manual" and not (self.source_reference or "").strip():
            raise ValueError("Uma guia ou fatura exige referência do documento físico.")
        if self.source_type == "manual" and not (self.manual_reason or "").strip():
            raise ValueError("Uma receção sem documento exige motivo.")
        return self


class StockArticleCreate(BaseModel):
    internal_ref: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=240)
    description: str | None = None
    unit: str = Field(default="un.", min_length=1, max_length=30)
    category_id: int | None = None
    classification: str | None = None
    primary_supplier_id: int | None = None


class StockMovementCreate(BaseModel):
    article_id: int
    movement_type: Literal["entry", "exit", "return", "transfer", "adjustment"]
    quantity: Decimal
    unit_cost: Decimal | None = Field(default=None, ge=0)
    from_location_id: int | None = None
    to_location_id: int | None = None
    external_reference_type: str | None = None
    external_reference_id: str | None = None
    reason: str = Field(min_length=1)
    effective_date: date = Field(default_factory=date.today)

    _quantity_is_integer = field_validator("quantity")(_integer_quantity)

    @model_validator(mode="after")
    def locations_match_type(self):
        if self.quantity == 0:
            raise ValueError("A quantidade não pode ser zero.")
        if self.movement_type != "adjustment" and self.quantity < 0:
            raise ValueError("Só os acertos podem usar quantidade negativa.")
        if self.movement_type == "entry" and not self.to_location_id:
            raise ValueError("Uma entrada exige destino.")
        if self.movement_type in {"exit", "return"} and not self.from_location_id:
            raise ValueError("A saída/devolução exige origem.")
        if self.movement_type == "transfer":
            if not self.from_location_id or not self.to_location_id:
                raise ValueError("Uma transferência exige origem e destino.")
            if self.from_location_id == self.to_location_id:
                raise ValueError("Origem e destino têm de ser diferentes.")
        if self.movement_type == "adjustment":
            if bool(self.from_location_id) == bool(self.to_location_id):
                raise ValueError("Um acerto exige exatamente uma localização.")
        return self


class StockMovementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    article_id: int
    movement_type: str
    quantity: Decimal
    unit: str
    unit_cost: Decimal | None
    from_location_id: int | None
    to_location_id: int | None
    receipt_line_id: int | None
    external_reference_type: str | None
    external_reference_id: str | None
    performed_by_id: int | None
    occurred_at: datetime
    effective_date: date
    reason: str | None
    reverses_movement_id: int | None


class StockMovementReverse(BaseModel):
    reason: str = Field(min_length=1)


class StockArticleVehicleCompatibilityCreate(BaseModel):
    article_id: int
    brand: str = Field(min_length=1, max_length=120)
    model: str = Field(min_length=1, max_length=160)
    version: str | None = Field(default=None, max_length=160)
    engine: str | None = Field(default=None, max_length=160)
    generation_period: str | None = Field(default=None, max_length=160)
    status: Literal["suggested", "confirmed", "validated", "rejected"] = "suggested"
    evidence_type: Literal["manual", "workshop", "supplier", "revision_model"] = "manual"
    evidence_reference: str | None = Field(default=None, max_length=200)
    evidence_notes: str | None = None


class StockWorkshopCompatibilityEvidence(BaseModel):
    article_id: int
    brand: str = Field(min_length=1, max_length=120)
    model: str = Field(min_length=1, max_length=160)
    version: str | None = Field(default=None, max_length=160)
    engine: str | None = Field(default=None, max_length=160)
    generation_period: str | None = Field(default=None, max_length=160)
    workshop_process_reference: str = Field(min_length=1, max_length=120)
    evidence_notes: str | None = None


class StockCompatibilityDecision(BaseModel):
    status: Literal["suggested", "confirmed", "validated", "rejected"]
    reason: str = Field(min_length=1)


class StockInventorySessionCreate(BaseModel):
    location_id: int
    effective_date: date = Field(default_factory=date.today)
    idempotency_key: str | None = Field(default=None, max_length=120)
    notes: str | None = None


class StockInventoryCountWrite(BaseModel):
    article_id: int
    counted_quantity: Decimal = Field(ge=0)

    _quantity_is_integer = field_validator("counted_quantity")(_integer_quantity)


class StockInventoryClose(BaseModel):
    counts: list[StockInventoryCountWrite] = Field(min_length=1)


class StockInventoryJustification(BaseModel):
    article_id: int
    justification: str | None = None


class StockInventoryConfirm(BaseModel):
    confirmations: list[StockInventoryJustification] = Field(default_factory=list)


class StockPurchaseOrderLineCreate(BaseModel):
    article_id: int
    supplier_ref: str | None = None
    quantity: Decimal = Field(gt=0)
    unit: str = Field(min_length=1, max_length=30)
    unit_price: Decimal = Field(ge=0)
    location_id: int

    _quantity_is_integer = field_validator("quantity")(_integer_quantity)


class StockPurchaseOrderCreate(BaseModel):
    supplier_id: int
    effective_date: date = Field(default_factory=date.today)
    commercial_status: Literal["draft", "sent", "confirmed", "cancelled"] = "draft"
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    notes: str | None = None
    lines: list[StockPurchaseOrderLineCreate] = Field(min_length=1)


class StockConferenceAction(BaseModel):
    action: Literal["save", "divergence", "validate"]
    notes: str | None = None
    tolerance: Decimal = Field(default=Decimal("0.01"), ge=0)


class StockDiscrepancyRegularize(BaseModel):
    adjustment_quantity: Decimal
    reason: str = Field(min_length=1)
    effective_date: date = Field(default_factory=date.today)

    _quantity_is_integer = field_validator("adjustment_quantity")(_integer_quantity)

    @model_validator(mode="after")
    def adjustment_is_not_zero(self):
        if self.adjustment_quantity == 0:
            raise ValueError("O acerto não pode ter quantidade zero.")
        return self
