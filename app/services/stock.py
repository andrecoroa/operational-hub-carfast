from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import pdfplumber
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.admin import User
from app.models.documents import Document, DocumentEvent
from app.models.stock import (
    StockArticle,
    StockArticleSupplierRef,
    StockArticleVehicleCompatibility,
    StockCategory,
    StockDeliveryDocument,
    StockDiscrepancy,
    StockInventoryCount,
    StockInventorySession,
    StockInvoiceImport,
    StockInvoiceLine,
    StockLocation,
    StockMinimum,
    StockMovement,
    StockPurchaseOrder,
    StockPurchaseOrderLine,
    StockReceipt,
    StockReceiptInvoiceLink,
    StockReceiptLine,
    StockSupplier,
)
from app.schemas.stock import (
    StockArticleVehicleCompatibilityCreate,
    StockConferenceAction,
    StockDiscrepancyRegularize,
    StockInventoryConfirm,
    StockInventorySessionCreate,
    StockInvoiceLineReview,
    StockInvoiceReview,
    StockMovementCreate,
    StockPurchaseOrderCreate,
    StockReceiptCreate,
    StockWorkshopCompatibilityEvidence,
)
from app.services.audit import record_audit

ZERO = Decimal("0")
CENT = Decimal("0.01")
QUANTITY_STEP = Decimal("1")
MONEY_STEP = Decimal("0.0001")
STOCK_LOCATION_DEFAULTS = (("WORKSHOP", "Oficina"), ("AIRPORT", "Aeroporto"))
STOCK_CATEGORY_DEFAULTS = (
    ("PARTS", "Peças"),
    ("TYRES", "Pneus"),
    ("LUBRICANTS", "Lubrificantes"),
    ("FILTERS", "Filtros"),
    ("CONSUMABLES", "Consumíveis"),
)
MOVEMENT_TYPES = {"entry", "exit", "return", "transfer", "adjustment", "reversal"}


class StockDomainError(ValueError):
    pass


def _decimal(value: Any, default: Decimal = ZERO) -> Decimal:
    if value in (None, ""):
        return default
    if isinstance(value, Decimal):
        return value
    text = str(value).strip().replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    return Decimal(text)


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_STEP, rounding=ROUND_HALF_UP)


def _cent(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _quantity(value: Decimal) -> Decimal:
    parsed = _decimal(value)
    if parsed != parsed.to_integral_value():
        raise StockDomainError("As quantidades de Stock têm de ser inteiras.")
    return parsed.quantize(QUANTITY_STEP)


def ensure_stock_defaults(db: Session) -> None:
    for code, name in STOCK_LOCATION_DEFAULTS:
        if not db.scalar(select(StockLocation).where(StockLocation.code == code)):
            db.add(StockLocation(code=code, name=name, active=True))
    for code, name in STOCK_CATEGORY_DEFAULTS:
        if not db.scalar(select(StockCategory).where(StockCategory.code == code)):
            db.add(StockCategory(code=code, name=name, active=True))


def _line_amounts(line: StockInvoiceLineReview) -> tuple[Decimal, Decimal, Decimal]:
    goods = line.quantity * line.unit_cost * (Decimal("1") - line.discount)
    net = _cent(goods + (line.quantity * line.eco_value))
    tax = _cent(net * line.tax_rate)
    gross = _cent(net + tax)
    return net, tax, gross


def _find_or_create_supplier(db: Session, review: StockInvoiceReview) -> StockSupplier:
    supplier = db.get(StockSupplier, review.supplier_id) if review.supplier_id else None
    clean_tax_id = (review.supplier_tax_id or "").strip() or None
    if not supplier and clean_tax_id:
        supplier = db.scalar(select(StockSupplier).where(StockSupplier.tax_id == clean_tax_id))
    if not supplier:
        supplier = db.scalar(
            select(StockSupplier).where(
                func.lower(StockSupplier.name) == review.supplier_name.strip().lower()
            )
        )
    if not supplier:
        supplier = StockSupplier(name=review.supplier_name.strip(), tax_id=clean_tax_id)
        db.add(supplier)
        db.flush()
    supplier.name = review.supplier_name.strip()
    supplier.tax_id = clean_tax_id or supplier.tax_id
    supplier.email = (review.supplier_email or "").strip() or supplier.email
    supplier.phone = (review.supplier_phone or "").strip() or supplier.phone
    supplier.address = (review.supplier_address or "").strip() or supplier.address
    supplier.payment_terms = (review.payment_terms or "").strip() or supplier.payment_terms
    return supplier


def ensure_invoice_import(
    db: Session,
    *,
    document: Document,
    extracted_data: dict[str, Any] | None = None,
    user_id: int | None = None,
) -> StockInvoiceImport:
    existing = db.scalar(
        select(StockInvoiceImport).where(StockInvoiceImport.document_id == document.id)
    )
    if existing:
        return existing

    data = extracted_data or {}
    content_hash = str(data.get("content_hash") or document.file_hash or "").strip() or None
    invoice_number = str(data.get("invoice_number") or "").strip() or None
    supplier_tax_id = str(data.get("supplier_tax_id") or "").strip() or None
    supplier = None
    if supplier_tax_id:
        supplier = db.scalar(select(StockSupplier).where(StockSupplier.tax_id == supplier_tax_id))

    duplicate = None
    if content_hash:
        duplicate = db.scalar(
            select(StockInvoiceImport).where(StockInvoiceImport.content_hash == content_hash)
        )
    if not duplicate and supplier and invoice_number:
        duplicate = db.scalar(
            select(StockInvoiceImport).where(
                StockInvoiceImport.supplier_id == supplier.id,
                StockInvoiceImport.invoice_number == invoice_number,
            )
        )
    if duplicate:
        return duplicate

    invoice_import = StockInvoiceImport(
        document_id=document.id,
        supplier_id=supplier.id if supplier else None,
        invoice_number=invoice_number,
        status="needs_review",
        content_hash=content_hash,
        extractor_name=str(data.get("extractor_name") or "").strip() or None,
        extractor_version=str(data.get("extractor_version") or "").strip() or None,
        raw_extraction_json=data or None,
    )
    db.add(invoice_import)
    db.flush()
    db.add(
        DocumentEvent(
            document_id=document.id,
            action="stock.invoice_import.created",
            old_value=None,
            new_value=f"stock_invoice_import:{invoice_import.id}",
            user_id=user_id,
        )
    )
    record_audit(
        db,
        action="stock.invoice_import.created",
        entity_type="stock_invoice_import",
        entity_id=invoice_import.id,
        detail="Registo documental criado para conferência; nenhuma operação de Stock foi criada.",
        user_id=user_id,
        after_json={"document_id": document.id, "status": invoice_import.status},
    )
    return invoice_import


def review_and_validate_invoice(
    db: Session,
    *,
    invoice_import: StockInvoiceImport,
    review: StockInvoiceReview,
    user_id: int | None,
) -> StockInvoiceImport:
    if invoice_import.status in {"duplicate", "failed", "cancelled"}:
        raise StockDomainError("Esta importação não pode ser validada no estado atual.")
    supplier = _find_or_create_supplier(db, review)
    duplicate = db.scalar(
        select(StockInvoiceImport).where(
            StockInvoiceImport.supplier_id == supplier.id,
            StockInvoiceImport.invoice_number == review.invoice_number.strip(),
            StockInvoiceImport.id != invoice_import.id,
        )
    )
    if duplicate:
        invoice_import.status = "duplicate"
        invoice_import.error_details = f"Duplicado da importação {duplicate.id}."
        record_audit(
            db,
            action="stock.invoice_import.duplicate",
            entity_type="stock_invoice_import",
            entity_id=invoice_import.id,
            detail=invoice_import.error_details,
            user_id=user_id,
        )
        raise StockDomainError(invoice_import.error_details)

    calculated_net = ZERO
    calculated_tax = ZERO
    calculated_gross = ZERO
    line_divergences: list[str] = []
    for line in review.lines:
        net, tax, gross = _line_amounts(line)
        calculated_net += net
        calculated_tax += tax
        calculated_gross += gross
        if line.line_total is not None and _cent(line.line_total) != _cent(gross):
            line_divergences.append(
                f"linha {line.line_number}: documento {_cent(line.line_total)} / "
                f"recalculado {_cent(gross)}"
            )
    calculated_net = _cent(calculated_net)
    calculated_tax = _cent(calculated_tax)
    calculated_gross = _cent(calculated_gross)
    expected = (
        ("líquido", review.net_total, calculated_net),
        ("IVA", review.tax_total, calculated_tax),
        ("total", review.gross_total, calculated_gross),
    )
    total_divergences = [
        f"{label}: calculado {computed} / documento {document_total}"
        for label, document_total, computed in expected
        if document_total is not None and _cent(document_total) != _cent(computed)
    ]
    divergences = line_divergences + total_divergences
    visible_divergences = divergences[:8]
    remaining_divergences = len(divergences) - len(visible_divergences)

    db.execute(
        delete(StockInvoiceLine).where(StockInvoiceLine.invoice_import_id == invoice_import.id)
    )
    for line in sorted(review.lines, key=lambda item: item.line_number):
        _net, _tax, gross = _line_amounts(line)
        db.add(
            StockInvoiceLine(
                invoice_import_id=invoice_import.id,
                line_number=line.line_number,
                article_id=None,
                supplier_ref=(line.supplier_ref or "").strip() or None,
                description=line.description.strip(),
                quantity=_quantity(line.quantity),
                unit=line.unit.strip(),
                unit_cost=_money(line.unit_cost),
                discount=line.discount,
                eco_value=_money(line.eco_value),
                tax_rate=line.tax_rate,
                line_total=_money(line.line_total if line.line_total is not None else gross),
            )
        )
    invoice_import.supplier_id = supplier.id
    invoice_import.invoice_number = review.invoice_number.strip()
    invoice_import.invoice_date = review.invoice_date
    invoice_import.due_date = review.due_date
    invoice_import.net_total = _money(
        review.net_total if review.net_total is not None else calculated_net
    )
    invoice_import.tax_total = _money(
        review.tax_total if review.tax_total is not None else calculated_tax
    )
    invoice_import.gross_total = _money(
        review.gross_total if review.gross_total is not None else calculated_gross
    )
    invoice_import.content_hash = review.content_hash or invoice_import.content_hash
    invoice_import.status = "validated"
    invoice_import.conference_status = "divergent" if divergences else "conferred"
    invoice_import.error_details = (
        "Aviso de reconciliação: os valores documentais foram guardados sem alteração. "
        + "; ".join(visible_divergences)
        + (f"; e mais {remaining_divergences} diferença(s)." if remaining_divergences else "")
        if divergences
        else None
    )
    raw_extraction = (
        dict(invoice_import.raw_extraction_json)
        if isinstance(invoice_import.raw_extraction_json, dict)
        else {}
    )
    raw_extraction["reconciliation"] = {
        "status": "divergent" if divergences else "matched",
        "document_values_preserved": True,
        "calculated": {
            "net_total": str(calculated_net),
            "tax_total": str(calculated_tax),
            "gross_total": str(calculated_gross),
        },
        "differences": divergences,
    }
    invoice_import.raw_extraction_json = raw_extraction
    invoice_import.validated_by_id = user_id
    invoice_import.validated_at = datetime.now(UTC)
    db.flush()
    document = db.get(Document, invoice_import.document_id)
    if document:
        db.add(
            DocumentEvent(
                document_id=document.id,
                action="stock.invoice_import.validated",
                old_value=document.status,
                new_value=document.status,
                user_id=user_id,
            )
        )
    record_audit(
        db,
        action="stock.invoice_import.validated",
        entity_type="stock_invoice_import",
        entity_id=invoice_import.id,
        detail="Conferência documental validada; nenhum artigo, receção ou movimento foi criado.",
        user_id=user_id,
        after_json={
            "supplier_id": supplier.id,
            "invoice_number": invoice_import.invoice_number,
            "line_count": len(review.lines),
            "receipt_created": False,
            "articles_created": False,
            "stock_changed": False,
        },
    )
    return invoice_import


def _base_movement_effects(movement: StockMovement) -> dict[int, Decimal]:
    quantity = _decimal(movement.quantity)
    effects: dict[int, Decimal] = defaultdict(lambda: ZERO)
    if movement.movement_type == "entry" and movement.to_location_id:
        effects[movement.to_location_id] += quantity
    elif movement.movement_type in {"exit", "return"} and movement.from_location_id:
        effects[movement.from_location_id] -= quantity
    elif movement.movement_type == "transfer":
        if movement.from_location_id:
            effects[movement.from_location_id] -= quantity
        if movement.to_location_id:
            effects[movement.to_location_id] += quantity
    elif movement.movement_type == "adjustment":
        location_id = movement.to_location_id or movement.from_location_id
        if location_id:
            effects[location_id] += quantity
    return dict(effects)


def stock_balances(
    db: Session,
    *,
    article_ids: Iterable[int] | None = None,
) -> dict[tuple[int, int], Decimal]:
    requested = set(article_ids or [])
    statement = select(StockMovement).order_by(StockMovement.id)
    if requested:
        statement = statement.where(StockMovement.article_id.in_(requested))
    movements = db.scalars(statement).all()
    effects_by_id: dict[int, dict[int, Decimal]] = {}
    balances: dict[tuple[int, int], Decimal] = defaultdict(lambda: ZERO)
    for movement in movements:
        if movement.movement_type == "reversal":
            original = effects_by_id.get(movement.reverses_movement_id or -1, {})
            effects = {location_id: -amount for location_id, amount in original.items()}
        else:
            effects = _base_movement_effects(movement)
        effects_by_id[movement.id] = effects
        for location_id, amount in effects.items():
            balances[(movement.article_id, location_id)] += amount
    return {key: _quantity(value) for key, value in balances.items()}


def article_total_balance(db: Session, article_id: int) -> Decimal:
    return sum(
        (
            quantity
            for (balance_article_id, _location_id), quantity in stock_balances(
                db, article_ids=[article_id]
            ).items()
            if balance_article_id == article_id
        ),
        ZERO,
    )


def _update_average_cost_for_entry(
    db: Session,
    *,
    article: StockArticle,
    quantity: Decimal,
    unit_cost: Decimal,
) -> None:
    before_quantity = article_total_balance(db, article.id)
    old_cost = _decimal(article.average_cost)
    if before_quantity > ZERO:
        article.average_cost = _money(
            ((before_quantity * old_cost) + (quantity * unit_cost)) / (before_quantity + quantity)
        )
    else:
        article.average_cost = _money(unit_cost)
    article.last_cost = _money(unit_cost)


def link_invoice_to_receipt(
    db: Session,
    *,
    receipt: StockReceipt,
    invoice_import: StockInvoiceImport,
    user_id: int | None,
) -> StockReceiptInvoiceLink:
    if (
        receipt.supplier_id
        and invoice_import.supplier_id
        and receipt.supplier_id != invoice_import.supplier_id
    ):
        raise StockDomainError("A receção e a fatura pertencem a fornecedores diferentes.")
    existing = db.scalar(
        select(StockReceiptInvoiceLink).where(
            StockReceiptInvoiceLink.receipt_id == receipt.id,
            StockReceiptInvoiceLink.invoice_import_id == invoice_import.id,
        )
    )
    if existing:
        return existing
    link = StockReceiptInvoiceLink(
        receipt_id=receipt.id,
        invoice_import_id=invoice_import.id,
        linked_by_id=user_id,
    )
    db.add(link)
    db.flush()
    record_audit(
        db,
        action="stock.receipt.invoice_linked",
        entity_type="stock_receipt",
        entity_id=receipt.id,
        detail=f"Fatura documental {invoice_import.id} ligada sem alterar existências.",
        user_id=user_id,
        after_json={"invoice_import_id": invoice_import.id, "stock_changed": False},
    )
    return link


def create_physical_receipt(
    db: Session,
    *,
    command: StockReceiptCreate,
    user_id: int | None,
) -> StockReceipt:
    if command.idempotency_key:
        existing = db.scalar(
            select(StockReceipt).where(
                StockReceipt.idempotency_key == command.idempotency_key.strip()
            )
        )
        if existing:
            return existing
    location = db.get(StockLocation, command.location_id)
    if not location or not location.active:
        raise StockDomainError("Localização de Stock inválida ou inativa.")
    supplier = db.get(StockSupplier, command.supplier_id) if command.supplier_id else None
    if command.supplier_id and (not supplier or not supplier.active):
        raise StockDomainError("Fornecedor inexistente ou inativo.")
    responsible_user = db.get(User, user_id) if user_id else None
    if not responsible_user or not responsible_user.active:
        raise StockDomainError("A receção exige um utilizador autenticado e ativo.")
    responsible_name = responsible_user.name.strip()
    manual_reason = (command.manual_reason or "").strip() or None
    if command.source_type == "manual" and not manual_reason:
        raise StockDomainError("Uma receção sem documento exige motivo.")
    purchase_order = (
        db.get(StockPurchaseOrder, command.purchase_order_id) if command.purchase_order_id else None
    )
    if command.purchase_order_id and not purchase_order:
        raise StockDomainError("Encomenda de Stock inexistente.")
    if purchase_order and supplier and purchase_order.supplier_id != supplier.id:
        raise StockDomainError("A encomenda não pertence ao fornecedor selecionado.")
    if purchase_order and not supplier:
        supplier = db.get(StockSupplier, purchase_order.supplier_id)
    invoice_imports = []
    for invoice_import_id in dict.fromkeys(command.invoice_import_ids):
        invoice_import = db.get(StockInvoiceImport, invoice_import_id)
        if not invoice_import:
            raise StockDomainError(f"Fatura documental {invoice_import_id} inexistente.")
        if supplier and invoice_import.supplier_id not in {None, supplier.id}:
            raise StockDomainError("A fatura não pertence ao fornecedor selecionado.")
        invoice_imports.append(invoice_import)
    delivery_document = (
        db.get(StockDeliveryDocument, command.delivery_document_id)
        if command.delivery_document_id
        else None
    )
    if command.delivery_document_id and not delivery_document:
        raise StockDomainError("Guia de Stock inexistente.")
    if delivery_document and supplier and delivery_document.supplier_id != supplier.id:
        raise StockDomainError("A guia não pertence ao fornecedor selecionado.")

    receipt = StockReceipt(
        supplier_id=supplier.id if supplier else None,
        location_id=location.id,
        source_type=command.source_type,
        source_reference=(command.source_reference or "").strip() or None,
        manual_reason=manual_reason,
        effective_date=command.effective_date,
        purchase_order_id=purchase_order.id if purchase_order else None,
        idempotency_key=(command.idempotency_key or "").strip() or None,
        status="completed",
        confirmed_by_id=responsible_user.id,
        responsible_name=responsible_name,
        confirmed_at=datetime.now(UTC),
        notes=(command.notes or "").strip() or None,
    )
    db.add(receipt)
    db.flush()

    seen_articles: set[int] = set()
    for item in command.lines:
        if item.article_id in seen_articles:
            raise StockDomainError("O mesmo artigo não pode aparecer duas vezes na receção.")
        seen_articles.add(item.article_id)
        article = db.get(StockArticle, item.article_id)
        if not article or not article.active:
            raise StockDomainError("Artigo inexistente ou inativo.")
        quantity = _quantity(item.accepted_quantity)
        order_line = (
            db.get(StockPurchaseOrderLine, item.purchase_order_line_id)
            if item.purchase_order_line_id
            else None
        )
        if item.purchase_order_line_id and not order_line:
            raise StockDomainError("Linha de encomenda inexistente.")
        if order_line:
            if not purchase_order or order_line.purchase_order_id != purchase_order.id:
                raise StockDomainError("A linha não pertence à encomenda selecionada.")
            if order_line.article_id != article.id:
                raise StockDomainError("O artigo recebido não corresponde à linha da encomenda.")
            if order_line.location_id != location.id:
                raise StockDomainError("A linha da encomenda destina-se a outra localização.")
        unit_cost = _money(item.unit_cost if item.unit_cost is not None else article.last_cost)
        supplier_ref = (item.supplier_ref or "").strip() or None
        supplier_reference = None
        if supplier and supplier_ref:
            supplier_reference = db.scalar(
                select(StockArticleSupplierRef).where(
                    StockArticleSupplierRef.supplier_id == supplier.id,
                    StockArticleSupplierRef.supplier_ref == supplier_ref,
                )
            )
            if supplier_reference and supplier_reference.article_id != article.id:
                raise StockDomainError(
                    f"A referência {supplier_ref} já está associada a outro artigo."
                )
            if not supplier_reference:
                supplier_reference = StockArticleSupplierRef(
                    article_id=article.id,
                    supplier_id=supplier.id,
                    supplier_ref=supplier_ref,
                    preferred=article.primary_supplier_id == supplier.id,
                )
                db.add(supplier_reference)
        if supplier_reference:
            supplier_reference.last_cost = unit_cost
            supplier_reference.last_purchase_at = datetime.now(UTC)
        _update_average_cost_for_entry(
            db,
            article=article,
            quantity=quantity,
            unit_cost=unit_cost,
        )
        receipt_line = StockReceiptLine(
            receipt_id=receipt.id,
            article_id=article.id,
            purchase_order_line_id=order_line.id if order_line else None,
            supplier_ref=supplier_ref,
            accepted_quantity=quantity,
            unit_cost=unit_cost,
            lot=(item.lot or "").strip() or None,
            divergence_reason=(item.divergence_reason or "").strip() or None,
        )
        db.add(receipt_line)
        db.flush()
        movement = StockMovement(
            article_id=article.id,
            movement_type="entry",
            quantity=quantity,
            unit=article.unit,
            unit_cost=unit_cost,
            to_location_id=location.id,
            receipt_line_id=receipt_line.id,
            external_reference_type="stock_receipt",
            external_reference_id=str(receipt.id),
            performed_by_id=user_id,
            reason=f"Receção física {command.source_reference or receipt.id}",
            effective_date=command.effective_date,
        )
        db.add(movement)
        db.flush()
        if order_line:
            remaining_before = _quantity(order_line.ordered_quantity - order_line.received_quantity)
            order_line.received_quantity = _quantity(order_line.received_quantity + quantity)
            if quantity > remaining_before:
                db.add(
                    StockDiscrepancy(
                        article_id=article.id,
                        location_id=location.id,
                        source_type="purchase_order_receipt",
                        source_id=str(receipt_line.id),
                        expected_quantity=remaining_before,
                        actual_quantity=quantity,
                        difference_quantity=_quantity(quantity - remaining_before),
                        reason=(
                            item.divergence_reason or "Quantidade superior à encomendada"
                        ).strip(),
                    )
                )
    for invoice_import in invoice_imports:
        link_invoice_to_receipt(
            db,
            receipt=receipt,
            invoice_import=invoice_import,
            user_id=user_id,
        )
    if delivery_document:
        delivery_document.status = "linked"
        delivery_document.receipt_id = receipt.id
    if purchase_order:
        order_lines = db.scalars(
            select(StockPurchaseOrderLine).where(
                StockPurchaseOrderLine.purchase_order_id == purchase_order.id
            )
        ).all()
        purchase_order.receiving_status = (
            "complete"
            if order_lines
            and all(line.received_quantity >= line.ordered_quantity for line in order_lines)
            else "partial"
        )
    record_audit(
        db,
        action="stock.receipt.confirmed",
        entity_type="stock_receipt",
        entity_id=receipt.id,
        detail=f"Receção física concluída em {location.name}; apenas quantidades aceites entraram.",
        user_id=user_id,
        after_json={
            "location_id": location.id,
            "source_type": command.source_type,
            "source_reference": receipt.source_reference,
            "manual_reason": receipt.manual_reason,
            "effective_date": receipt.effective_date.isoformat(),
            "purchase_order_id": receipt.purchase_order_id,
            "invoice_import_ids": [item.id for item in invoice_imports],
            "status": receipt.status,
            "lines": [item.model_dump(mode="json") for item in command.lines],
        },
    )
    return receipt


def _assert_location(db: Session, location_id: int | None) -> StockLocation | None:
    if location_id is None:
        return None
    location = db.get(StockLocation, location_id)
    if not location or not location.active:
        raise StockDomainError("Localização de Stock inválida ou inativa.")
    return location


def create_manual_movement(
    db: Session,
    *,
    command: StockMovementCreate,
    user_id: int | None,
) -> StockMovement:
    article = db.get(StockArticle, command.article_id)
    if not article or not article.active:
        raise StockDomainError("Artigo inexistente ou inativo.")
    _assert_location(db, command.from_location_id)
    _assert_location(db, command.to_location_id)
    balances = stock_balances(db, article_ids=[article.id])
    quantity = _quantity(command.quantity)
    if command.movement_type in {"exit", "return", "transfer"}:
        available = balances.get((article.id, command.from_location_id or 0), ZERO)
        if available < quantity:
            raise StockDomainError(f"Stock insuficiente: disponível {available} {article.unit}.")
    if command.movement_type == "adjustment" and quantity < ZERO:
        location_id = command.to_location_id or command.from_location_id or 0
        available = balances.get((article.id, location_id), ZERO)
        if available + quantity < ZERO:
            raise StockDomainError("O acerto deixaria a existência negativa.")
    if command.movement_type == "entry":
        if command.unit_cost is None:
            raise StockDomainError("Uma entrada manual exige custo unitário.")
        _update_average_cost_for_entry(
            db,
            article=article,
            quantity=quantity,
            unit_cost=command.unit_cost,
        )
    movement = StockMovement(
        article_id=article.id,
        movement_type=command.movement_type,
        quantity=quantity,
        unit=article.unit,
        unit_cost=_money(command.unit_cost) if command.unit_cost is not None else None,
        from_location_id=command.from_location_id,
        to_location_id=command.to_location_id,
        external_reference_type=command.external_reference_type,
        external_reference_id=command.external_reference_id,
        performed_by_id=user_id,
        reason=command.reason.strip(),
        effective_date=command.effective_date,
    )
    db.add(movement)
    db.flush()
    record_audit(
        db,
        action=f"stock.movement.{command.movement_type}",
        entity_type="stock_movement",
        entity_id=movement.id,
        detail=movement.reason,
        user_id=user_id,
        after_json={
            "article_id": article.id,
            "quantity": str(quantity),
            "from_location_id": movement.from_location_id,
            "to_location_id": movement.to_location_id,
        },
    )
    return movement


def reverse_movement(
    db: Session,
    *,
    movement: StockMovement,
    reason: str,
    user_id: int | None,
) -> StockMovement:
    if movement.movement_type == "reversal":
        raise StockDomainError("Uma reversão não pode ser revertida; crie um acerto.")
    if db.scalar(select(StockMovement).where(StockMovement.reverses_movement_id == movement.id)):
        raise StockDomainError("Este movimento já foi revertido.")
    reversal = StockMovement(
        article_id=movement.article_id,
        movement_type="reversal",
        quantity=movement.quantity,
        unit=movement.unit,
        unit_cost=movement.unit_cost,
        from_location_id=movement.from_location_id,
        to_location_id=movement.to_location_id,
        external_reference_type="stock_movement",
        external_reference_id=str(movement.id),
        performed_by_id=user_id,
        reason=reason.strip(),
        effective_date=movement.effective_date,
        reverses_movement_id=movement.id,
    )
    db.add(reversal)
    db.flush()
    record_audit(
        db,
        action="stock.movement.reversed",
        entity_type="stock_movement",
        entity_id=reversal.id,
        detail=reversal.reason,
        user_id=user_id,
        after_json={"reverses_movement_id": movement.id},
    )
    return reversal


def low_stock_rows(db: Session) -> list[dict[str, Any]]:
    balances = stock_balances(db)
    rows = db.execute(
        select(StockMinimum, StockArticle, StockLocation)
        .join(StockArticle, StockArticle.id == StockMinimum.article_id)
        .join(StockLocation, StockLocation.id == StockMinimum.location_id)
        .where(StockArticle.active.is_(True), StockLocation.active.is_(True))
        .order_by(StockArticle.name, StockLocation.name)
    ).all()
    return [
        {
            "minimum": minimum,
            "article": article,
            "location": location,
            "available": balances.get((article.id, location.id), ZERO),
        }
        for minimum, article, location in rows
        if balances.get((article.id, location.id), ZERO) < _decimal(minimum.minimum_quantity)
    ]


COMPATIBILITY_STATES = {"suggested", "confirmed", "validated", "rejected"}


def create_vehicle_compatibility(
    db: Session,
    *,
    command: StockArticleVehicleCompatibilityCreate,
    user_id: int | None,
) -> StockArticleVehicleCompatibility:
    article = db.get(StockArticle, command.article_id)
    if not article or not article.active:
        raise StockDomainError("Artigo inexistente ou inativo.")
    compatibility = StockArticleVehicleCompatibility(
        article_id=article.id,
        brand=command.brand.strip(),
        model=command.model.strip(),
        version=(command.version or "").strip() or None,
        engine=(command.engine or "").strip() or None,
        generation_period=(command.generation_period or "").strip() or None,
        status=command.status,
        evidence_type=command.evidence_type,
        evidence_reference=(command.evidence_reference or "").strip() or None,
        evidence_notes=(command.evidence_notes or "").strip() or None,
        created_by_id=user_id,
    )
    if command.status in {"validated", "rejected"}:
        compatibility.decided_by_id = user_id
        compatibility.decided_at = datetime.now(UTC)
    db.add(compatibility)
    db.flush()
    record_audit(
        db,
        action=f"stock.compatibility.{command.status}",
        entity_type="stock_article_vehicle_compatibility",
        entity_id=compatibility.id,
        detail=f"{compatibility.brand} {compatibility.model} · {compatibility.evidence_type}",
        user_id=user_id,
        after_json=command.model_dump(mode="json"),
    )
    return compatibility


def record_workshop_compatibility_evidence(
    db: Session,
    *,
    command: StockWorkshopCompatibilityEvidence,
    user_id: int | None,
) -> StockArticleVehicleCompatibility:
    """Stock-side contract for Oficina usage; deliberately never validates compatibility."""
    existing = db.scalar(
        select(StockArticleVehicleCompatibility).where(
            StockArticleVehicleCompatibility.article_id == command.article_id,
            StockArticleVehicleCompatibility.workshop_process_reference
            == command.workshop_process_reference.strip(),
            StockArticleVehicleCompatibility.brand == command.brand.strip(),
            StockArticleVehicleCompatibility.model == command.model.strip(),
        )
    )
    if existing:
        return existing
    payload = StockArticleVehicleCompatibilityCreate(
        article_id=command.article_id,
        brand=command.brand,
        model=command.model,
        version=command.version,
        engine=command.engine,
        generation_period=command.generation_period,
        status="confirmed",
        evidence_type="workshop",
        evidence_reference=command.workshop_process_reference,
        evidence_notes=command.evidence_notes,
    )
    compatibility = create_vehicle_compatibility(db, command=payload, user_id=user_id)
    compatibility.workshop_process_reference = command.workshop_process_reference.strip()
    return compatibility


def decide_vehicle_compatibility(
    db: Session,
    *,
    compatibility: StockArticleVehicleCompatibility,
    status: str,
    reason: str,
    user_id: int | None,
) -> StockArticleVehicleCompatibility:
    if status not in COMPATIBILITY_STATES:
        raise StockDomainError("Estado de compatibilidade inválido.")
    old_status = compatibility.status
    compatibility.status = status
    compatibility.evidence_notes = " · ".join(
        part for part in (compatibility.evidence_notes, reason.strip()) if part
    )
    if status in {"validated", "rejected"}:
        compatibility.decided_by_id = user_id
        compatibility.decided_at = datetime.now(UTC)
    record_audit(
        db,
        action="stock.compatibility.decided",
        entity_type="stock_article_vehicle_compatibility",
        entity_id=compatibility.id,
        detail=reason.strip(),
        user_id=user_id,
        before_json={"status": old_status},
        after_json={"status": status},
    )
    return compatibility


def create_inventory_session(
    db: Session,
    *,
    command: StockInventorySessionCreate,
    user_id: int | None,
) -> StockInventorySession:
    if command.idempotency_key:
        existing = db.scalar(
            select(StockInventorySession).where(
                StockInventorySession.idempotency_key == command.idempotency_key.strip()
            )
        )
        if existing:
            return existing
    location = db.get(StockLocation, command.location_id)
    if not location or not location.active:
        raise StockDomainError("Localização de Stock inválida ou inativa.")
    article_statement = select(StockArticle.id).where(StockArticle.active.is_(True))
    category = None
    if command.category_id is not None:
        category = db.get(StockCategory, command.category_id)
        if not category or not category.active:
            raise StockDomainError("Categoria de Stock inválida ou inativa.")
        article_statement = article_statement.where(
            StockArticle.category_id == category.id
        )
    article_ids = db.scalars(article_statement.order_by(StockArticle.id)).all()
    if not article_ids:
        raise StockDomainError("Não existem artigos ativos para o âmbito selecionado.")
    balances = stock_balances(db, article_ids=article_ids)
    inventory = StockInventorySession(
        location_id=location.id,
        status="draft",
        effective_date=command.effective_date,
        idempotency_key=(command.idempotency_key or "").strip() or None,
        notes=(command.notes or "").strip() or None,
        created_by_id=user_id,
    )
    db.add(inventory)
    db.flush()
    for article_id in article_ids:
        db.add(
            StockInventoryCount(
                session_id=inventory.id,
                article_id=article_id,
                expected_snapshot=_quantity(balances.get((article_id, location.id), ZERO)),
            )
        )
    record_audit(
        db,
        action="stock.inventory.created",
        entity_type="stock_inventory_session",
        entity_id=inventory.id,
        detail=(
            f"Snapshot cego criado para {location.name}"
            f" · categoria {category.name if category else 'todas'}."
        ),
        user_id=user_id,
        after_json={
            "location_id": location.id,
            "category_id": category.id if category else None,
            "article_count": len(article_ids),
            "effective_date": command.effective_date.isoformat(),
        },
    )
    return inventory


def save_inventory_counts(
    db: Session,
    *,
    inventory: StockInventorySession,
    counts: dict[int, Decimal],
    user_id: int | None,
    close: bool = False,
) -> StockInventorySession:
    if inventory.status not in {"draft", "counting"}:
        raise StockDomainError("Esta sessão já não aceita contagens.")
    rows = {
        row.article_id: row
        for row in db.scalars(
            select(StockInventoryCount).where(StockInventoryCount.session_id == inventory.id)
        ).all()
    }
    for article_id, raw_quantity in counts.items():
        if article_id not in rows:
            raise StockDomainError("O artigo não pertence ao snapshot desta sessão.")
        rows[article_id].counted_quantity = _quantity(raw_quantity)
    inventory.status = "counting"
    if close:
        missing = [row.article_id for row in rows.values() if row.counted_quantity is None]
        if missing:
            raise StockDomainError("É necessário contar todos os artigos antes de fechar.")
        inventory.status = "review"
        inventory.closed_by_id = user_id
        inventory.closed_at = datetime.now(UTC)
    record_audit(
        db,
        action="stock.inventory.closed" if close else "stock.inventory.saved",
        entity_type="stock_inventory_session",
        entity_id=inventory.id,
        detail="Contagem fechada para revisão humana." if close else "Rascunho guardado.",
        user_id=user_id,
        after_json={"counted_article_ids": sorted(counts), "status": inventory.status},
    )
    return inventory


def cancel_inventory_session(
    db: Session,
    *,
    inventory: StockInventorySession,
    reason: str,
    user_id: int | None,
) -> StockInventorySession:
    clean_reason = reason.strip()
    if inventory.status not in {"draft", "counting"}:
        raise StockDomainError("Só é possível cancelar uma sessão ainda em contagem.")
    if not clean_reason:
        raise StockDomainError("Indica o motivo do cancelamento.")
    previous_status = inventory.status
    inventory.status = "cancelled"
    inventory.notes = " · ".join(part for part in (inventory.notes, clean_reason) if part)
    inventory.closed_by_id = user_id
    inventory.closed_at = datetime.now(UTC)
    record_audit(
        db,
        action="stock.inventory.cancelled",
        entity_type="stock_inventory_session",
        entity_id=inventory.id,
        detail=clean_reason,
        user_id=user_id,
        before_json={"status": previous_status},
        after_json={"status": inventory.status},
    )
    return inventory


def archive_inventory_session(
    db: Session,
    *,
    inventory: StockInventorySession,
    user_id: int | None,
) -> StockInventorySession:
    if inventory.status not in {"completed", "cancelled"}:
        raise StockDomainError("Só é possível arquivar uma sessão concluída ou cancelada.")
    previous_status = inventory.status
    inventory.status = f"archived_{previous_status}"
    record_audit(
        db,
        action="stock.inventory.archived",
        entity_type="stock_inventory_session",
        entity_id=inventory.id,
        user_id=user_id,
        before_json={"status": previous_status},
        after_json={"status": inventory.status},
    )
    return inventory


def confirm_inventory_session(
    db: Session,
    *,
    inventory: StockInventorySession,
    command: StockInventoryConfirm,
    user_id: int | None,
) -> StockInventorySession:
    if inventory.status == "completed":
        return inventory
    if inventory.status != "review":
        raise StockDomainError("A contagem tem de ser fechada antes da confirmação.")
    justifications = {
        item.article_id: (item.justification or "").strip() for item in command.confirmations
    }
    rows = db.scalars(
        select(StockInventoryCount)
        .where(StockInventoryCount.session_id == inventory.id)
        .order_by(StockInventoryCount.id)
    ).all()
    for row in rows:
        if row.counted_quantity is None:
            raise StockDomainError("A sessão contém artigos sem contagem.")
        difference = _quantity(row.counted_quantity - row.expected_snapshot)
        if difference == ZERO:
            continue
        justification = justifications.get(row.article_id) or (row.justification or "").strip()
        if not justification:
            raise StockDomainError("Cada diferença exige justificação humana.")
        row.justification = justification
        if row.adjustment_movement_id:
            continue
        movement = create_manual_movement(
            db,
            command=StockMovementCreate(
                article_id=row.article_id,
                movement_type="adjustment",
                quantity=difference,
                from_location_id=inventory.location_id if difference < ZERO else None,
                to_location_id=inventory.location_id if difference > ZERO else None,
                external_reference_type="stock_inventory_session",
                external_reference_id=str(inventory.id),
                reason=justification,
                effective_date=inventory.effective_date,
            ),
            user_id=user_id,
        )
        row.adjustment_movement_id = movement.id
    inventory.status = "completed"
    inventory.confirmed_by_id = user_id
    inventory.confirmed_at = datetime.now(UTC)
    record_audit(
        db,
        action="stock.inventory.confirmed",
        entity_type="stock_inventory_session",
        entity_id=inventory.id,
        detail="Confirmação humana concluída; apenas diferenças geraram acertos imutáveis.",
        user_id=user_id,
        after_json={"status": inventory.status},
    )
    return inventory


def create_purchase_order(
    db: Session,
    *,
    command: StockPurchaseOrderCreate,
    user_id: int | None,
) -> StockPurchaseOrder:
    supplier = db.get(StockSupplier, command.supplier_id)
    if not supplier or not supplier.active:
        raise StockDomainError("Fornecedor inexistente ou inativo.")
    year = command.effective_date.year
    sequence = (
        int(
            db.scalar(
                select(func.count())
                .select_from(StockPurchaseOrder)
                .where(StockPurchaseOrder.order_number.like(f"PO-{year}-%"))
            )
            or 0
        )
        + 1
    )
    order_number = f"PO-{year}-{sequence:05d}"
    while db.scalar(
        select(StockPurchaseOrder.id).where(
            StockPurchaseOrder.order_number == order_number,
            StockPurchaseOrder.version == 1,
        )
    ):
        sequence += 1
        order_number = f"PO-{year}-{sequence:05d}"
    order = StockPurchaseOrder(
        order_number=order_number,
        version=1,
        supplier_id=supplier.id,
        commercial_status=command.commercial_status,
        receiving_status="pending",
        effective_date=command.effective_date,
        currency=command.currency.upper(),
        notes=(command.notes or "").strip() or None,
        created_by_id=user_id,
    )
    db.add(order)
    db.flush()
    for number, item in enumerate(command.lines, 1):
        article = db.get(StockArticle, item.article_id)
        location = db.get(StockLocation, item.location_id)
        if not article or not article.active:
            raise StockDomainError("A encomenda contém um artigo inexistente ou inativo.")
        if not location or not location.active:
            raise StockDomainError("A encomenda contém uma localização inválida.")
        db.add(
            StockPurchaseOrderLine(
                purchase_order_id=order.id,
                line_number=number,
                article_id=article.id,
                supplier_ref=(item.supplier_ref or "").strip() or None,
                ordered_quantity=_quantity(item.quantity),
                received_quantity=ZERO,
                unit=item.unit.strip(),
                unit_price=_cent(item.unit_price),
                location_id=location.id,
            )
        )
    record_audit(
        db,
        action="stock.purchase_order.created",
        entity_type="stock_purchase_order",
        entity_id=order.id,
        detail=f"{order.order_number} v{order.version}",
        user_id=user_id,
        after_json=command.model_dump(mode="json") | {"order_number": order.order_number},
    )
    return order


def conference_comparison(db: Session, invoice_import: StockInvoiceImport) -> dict[str, Any]:
    invoice_lines = db.scalars(
        select(StockInvoiceLine)
        .where(StockInvoiceLine.invoice_import_id == invoice_import.id)
        .order_by(StockInvoiceLine.line_number)
    ).all()
    receipt_rows = db.execute(
        select(StockReceiptLine, StockReceipt)
        .join(StockReceipt, StockReceipt.id == StockReceiptLine.receipt_id)
        .join(StockReceiptInvoiceLink, StockReceiptInvoiceLink.receipt_id == StockReceipt.id)
        .where(StockReceiptInvoiceLink.invoice_import_id == invoice_import.id)
        .order_by(StockReceipt.effective_date, StockReceipt.id)
    ).all()
    order_ids = {
        receipt.purchase_order_id for _, receipt in receipt_rows if receipt.purchase_order_id
    }
    order_lines = db.scalars(
        select(StockPurchaseOrderLine).where(
            StockPurchaseOrderLine.purchase_order_id.in_(order_ids or {-1})
        )
    ).all()
    receipts_by_ref: dict[str, Decimal] = defaultdict(lambda: ZERO)
    receipts_by_article: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for line, _receipt in receipt_rows:
        if line.supplier_ref:
            receipts_by_ref[line.supplier_ref] += line.accepted_quantity
        receipts_by_article[line.article_id] += line.accepted_quantity
    orders_by_ref: dict[str, Decimal] = defaultdict(lambda: ZERO)
    orders_by_article: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for line in order_lines:
        if line.supplier_ref:
            orders_by_ref[line.supplier_ref] += line.ordered_quantity
        orders_by_article[line.article_id] += line.ordered_quantity
    line_comparison = []
    for line in invoice_lines:
        ordered = orders_by_ref.get(line.supplier_ref or "", ZERO)
        received = receipts_by_ref.get(line.supplier_ref or "", ZERO)
        if line.article_id:
            ordered = ordered or orders_by_article.get(line.article_id, ZERO)
            received = received or receipts_by_article.get(line.article_id, ZERO)
        divergent = bool(order_ids and ordered != line.quantity) or bool(
            receipt_rows and received != line.quantity
        )
        line_comparison.append(
            {
                "line": line,
                "ordered": _quantity(ordered),
                "received": _quantity(received),
                "invoiced": _quantity(line.quantity),
                "divergent": divergent,
            }
        )
    order_total = sum((line.ordered_quantity * line.unit_price for line in order_lines), ZERO)
    tolerance = _decimal(invoice_import.conference_tolerance, CENT)
    gross_total = _decimal(invoice_import.gross_total)
    return {
        "lines": line_comparison,
        "receipt_count": len({receipt.id for _, receipt in receipt_rows}),
        "order_count": len(order_ids),
        "order_total": _cent(order_total),
        "invoice_total": _cent(gross_total),
        "total_divergent": bool(order_ids and abs(order_total - gross_total) > tolerance),
        "has_divergence": any(row["divergent"] for row in line_comparison)
        or bool(order_ids and abs(order_total - gross_total) > tolerance),
    }


def apply_conference_action(
    db: Session,
    *,
    invoice_import: StockInvoiceImport,
    command: StockConferenceAction,
    user_id: int | None,
) -> StockInvoiceImport:
    comparison = conference_comparison(db, invoice_import)
    invoice_import.conference_tolerance = _cent(command.tolerance)
    invoice_import.conference_notes = (command.notes or "").strip() or None
    if command.action == "save":
        invoice_import.conference_status = "pending"
    elif command.action == "divergence":
        invoice_import.conference_status = "divergent"
    else:
        if comparison["has_divergence"] and not invoice_import.conference_notes:
            raise StockDomainError("A validação com divergências exige observações.")
        invoice_import.conference_status = "conferred"
        invoice_import.validated_by_id = user_id
        invoice_import.validated_at = datetime.now(UTC)
    record_audit(
        db,
        action=f"stock.conference.{command.action}",
        entity_type="stock_invoice_import",
        entity_id=invoice_import.id,
        detail=invoice_import.conference_notes,
        user_id=user_id,
        after_json={
            "conference_status": invoice_import.conference_status,
            "has_divergence": comparison["has_divergence"],
            "stock_changed": False,
        },
    )
    return invoice_import


def regularize_discrepancy(
    db: Session,
    *,
    discrepancy: StockDiscrepancy,
    command: StockDiscrepancyRegularize,
    user_id: int | None,
) -> StockDiscrepancy:
    if discrepancy.status == "regularized":
        return discrepancy
    quantity = _quantity(command.adjustment_quantity)
    movement = create_manual_movement(
        db,
        command=StockMovementCreate(
            article_id=discrepancy.article_id,
            movement_type="adjustment",
            quantity=quantity,
            from_location_id=discrepancy.location_id if quantity < ZERO else None,
            to_location_id=discrepancy.location_id if quantity > ZERO else None,
            external_reference_type="stock_discrepancy",
            external_reference_id=str(discrepancy.id),
            reason=command.reason,
            effective_date=command.effective_date,
        ),
        user_id=user_id,
    )
    discrepancy.adjustment_movement_id = movement.id
    discrepancy.status = "regularized"
    discrepancy.regularized_by_id = user_id
    discrepancy.regularized_at = datetime.now(UTC)
    return discrepancy


def _authorized_document_path(document: Document) -> Path:
    raw_path = (document.storage_path or "").strip()
    if not raw_path or "://" in raw_path:
        raise StockDomainError(
            "O documento original não está disponível no arquivo local autorizado."
        )
    root_value = (settings.document_archive_root or "").strip()
    candidate = Path(raw_path).expanduser()
    if root_value:
        root = Path(root_value).expanduser().resolve()
        if not candidate.is_absolute():
            candidate = root / candidate
        resolved = candidate.resolve(strict=True)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise StockDomainError("O documento não pertence ao arquivo autorizado.") from exc
    else:
        resolved = candidate.resolve(strict=True)
    if not resolved.is_file() or resolved.suffix.lower() != ".pdf":
        raise StockDomainError("A extração Stock exige um PDF existente.")
    return resolved


def _pdf_lines(path: Path) -> tuple[list[str], str]:
    raw = path.read_bytes()
    lines: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            words = page.extract_words(x_tolerance=2, y_tolerance=2, keep_blank_chars=False)
            groups: list[dict[str, Any]] = []
            for word in sorted(
                words, key=lambda item: (round(float(item["top"]), 1), float(item["x0"]))
            ):
                top = float(word["top"])
                group = next((item for item in groups if abs(item["top"] - top) <= 2), None)
                if group is None:
                    group = {"top": top, "words": []}
                    groups.append(group)
                group["words"].append(word)
            for group in sorted(groups, key=lambda item: item["top"]):
                text = " | ".join(
                    str(word["text"]).strip()
                    for word in sorted(group["words"], key=lambda item: float(item["x0"]))
                    if str(word["text"]).strip()
                )
                if text:
                    lines.append(text)
    # Scanned supplier invoices have no usable PDF text layer. Reuse the
    # production OCR pipeline already used by diagnostics instead of silently
    # returning an empty extraction.
    if len(" ".join(lines).strip()) < 80:
        from app.services.diagnostic_ocr import extract_diagnostic_pdf

        payload = extract_diagnostic_pdf(path, enable_ocr=True)
        ocr_lines: list[str] = []
        for page in payload.get("pages", []):
            source = (
                (page.get("ocr") or {}).get("text")
                or page.get("layout_text")
                or page.get("native_text")
                or ""
            )
            ocr_lines.extend(line.strip() for line in source.splitlines() if line.strip())
        if ocr_lines:
            lines = ocr_lines
    return lines, hashlib.sha256(raw).hexdigest()


def _first_match(lines: list[str], pattern: str) -> str | None:
    regex = re.compile(pattern, re.IGNORECASE)
    for line in lines:
        match = regex.search(line)
        if match:
            return match.group(1)
    return None


def _joined_amount(lines: list[str], pattern: str) -> str | None:
    regex = re.compile(pattern, re.IGNORECASE)
    for line in lines:
        if match := regex.search(line):
            tokens = re.findall(r"\d+(?:[,.]\d+)?", line[match.end() :])
            if tokens:
                return "".join(tokens)
    return None


def parse_dispnal_invoice(lines: list[str], content_hash: str) -> dict[str, Any] | None:
    all_text = "\n".join(lines)
    is_dispnal = re.search(r"Dispnal(?:\s*\|?\s*)Pneus", all_text, re.IGNORECASE)
    if not is_dispnal and "504670409" not in all_text:
        return None
    invoice_number = _first_match(
        lines,
        r"Fatura\s*(?:FT)?\s*N[.ºo°]*\s*(?:\|\s*)?(\d+(?:/\d{4})?)",
    )
    invoice_number = invoice_number or _first_match(lines, r"^\s*N[.ºo°]*\s*(?:\|\s*)?(\d+/\d{4})")
    invoice_number = invoice_number or _first_match(lines, r"\*FA\s*(\d+)\s*\*")
    if not invoice_number:
        raise StockDomainError("Número da fatura Dispnal não encontrado.")
    parsed_lines: list[dict[str, Any]] = []
    for source_line in lines:
        parts = [part.strip() for part in source_line.split("|") if part.strip()]
        if len(parts) > 1:
            normalized_line = " ".join(parts)
        else:
            normalized_line = source_line
        match = re.match(
            r"^([A-Z0-9]{8,20})\s+(.+?)\s+"
            r"(\d+[,.]\d+)\s+(UN|UNI|UDS)\s+"
            r"([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s*$",
            normalized_line.strip(),
            re.IGNORECASE,
        )
        if not match:
            continue
        supplier_ref, description, quantity_text, unit, *amounts = match.groups()
        quantity = _decimal(quantity_text)
        unit_cost = _decimal(amounts[0])
        discount = _decimal(amounts[1]) / Decimal("100")
        eco_value = _decimal(amounts[2])
        tax_rate = _decimal(amounts[3]) / Decimal("100")
        goods_value = _decimal(amounts[4])
        base = _cent(goods_value + (quantity * eco_value))
        line_total = _cent(base + (base * tax_rate))
        parsed_lines.append(
            {
                "line_number": len(parsed_lines) + 1,
                "supplier_ref": supplier_ref,
                "description": description,
                "quantity": str(quantity),
                "unit": unit.lower(),
                "unit_cost": str(unit_cost),
                "discount": str(discount),
                "eco_value": str(eco_value),
                "tax_rate": str(tax_rate),
                "line_total": str(line_total),
            }
        )
    if not parsed_lines:
        raise StockDomainError("Não foram encontradas linhas de artigos na fatura Dispnal.")
    dates = re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", all_text)
    tax_match = re.search(
        r"IVA[ |]*\(?23[,.]00\)?[ |]+([\d.,]+)[ |]+([\d.,]+)",
        all_text,
        re.IGNORECASE,
    )
    total_match = re.search(
        r"Total[ |]*\([ |]*EUR[ |]*\)[ |]*([\d .,]+)",
        all_text,
        re.IGNORECASE,
    )
    return {
        "extractor_name": "dispnal",
        "extractor_version": "v1",
        "content_hash": content_hash,
        "supplier_name": "Dispnal Pneus, S.A.",
        "supplier_tax_id": "504670409",
        "invoice_number": invoice_number,
        "invoice_date": dates[0] if dates else None,
        "due_date": dates[1] if len(dates) > 1 else None,
        "net_total": tax_match.group(1) if tax_match else None,
        "tax_total": tax_match.group(2) if tax_match else None,
        "gross_total": total_match.group(1).replace(" ", "") if total_match else None,
        "lines": parsed_lines,
    }


def _document_copy(lines: list[str], marker: str) -> list[str]:
    """Keep the first logical copy when a PDF contains ORIGINAL and DUPLICADO."""
    stop = next(
        (index for index, line in enumerate(lines) if index and marker.lower() in line.lower()),
        len(lines),
    )
    return lines[:stop]


def parse_torres_cunha_invoice(lines: list[str], content_hash: str) -> dict[str, Any] | None:
    all_text = "\n".join(lines)
    if not re.search(r"Torres\s*\|?\s*&\s*\|?\s*Cunha", all_text, re.IGNORECASE):
        return None
    if "503699292" not in all_text:
        return None

    source_lines = _document_copy(lines, "DUPLICADO")
    invoice_number = _first_match(source_lines, r"Fatura\s*\|?\s*n[.ºo]*\s*\|?\s*(\d+/\d{4})")
    if not invoice_number:
        raise StockDomainError("Número da fatura Torres & Cunha não encontrado.")

    parsed_lines: list[dict[str, Any]] = []
    for source_line in source_lines:
        parts = [part.strip() for part in source_line.split("|") if part.strip()]
        if len(parts) < 8 or not re.fullmatch(r"[A-Z0-9][A-Z0-9-]{3,20}", parts[0]):
            continue
        quantity_index = next(
            (
                index
                for index, part in enumerate(parts[:-1])
                if re.fullmatch(r"\d+[,.]\d+", part)
                and parts[index + 1].upper() in {"UNI", "UN", "UDS"}
            ),
            -1,
        )
        if quantity_index < 3 or len(parts) <= quantity_index + 4:
            continue
        tail = parts[quantity_index + 2 :]
        unit_cost = _decimal(tail[0])
        discount_parts = [part for part in tail[1:] if part.endswith("%")]
        discount = sum((_decimal(part[:-1]) for part in discount_parts), ZERO) / Decimal("100")
        numeric_tail = [part for part in tail[1:] if re.fullmatch(r"\d+[,.]\d+", part)]
        if len(numeric_tail) < 2:
            continue
        line_value = _decimal(numeric_tail[0])
        tax_rate = _decimal(numeric_tail[1]) / Decimal("100")
        quantity = _decimal(parts[quantity_index])
        goods_after_discount = _cent(quantity * unit_cost * (Decimal("1") - discount))
        eco_value = max(ZERO, _cent(line_value - goods_after_discount))
        parsed_lines.append(
            {
                "line_number": len(parsed_lines) + 1,
                "supplier_ref": parts[0],
                "description": " ".join(parts[2:quantity_index]).strip(),
                "quantity": str(quantity),
                "unit": parts[quantity_index + 1].lower(),
                "unit_cost": str(unit_cost),
                "discount": str(discount),
                "eco_value": str(eco_value),
                "tax_rate": str(tax_rate),
                "line_total": str(_cent(line_value * (Decimal("1") + tax_rate))),
            }
        )
    if not parsed_lines:
        raise StockDomainError("Não foram encontradas linhas na fatura Torres & Cunha.")

    tax_match = next(
        (
            re.search(r"23[,.]00%\s*\|\s*([\d.,]+)\s*\|\s*([\d.,]+)", line)
            for line in source_lines
            if "23,00%" in line or "23.00%" in line
        ),
        None,
    )
    gross_total = next(
        (
            match.group(1)
            for line in reversed(source_lines)
            if (match := re.search(r"^Total\s*\|\s*([\d.,]+)\s*$", line, re.IGNORECASE))
        ),
        None,
    )
    return {
        "extractor_name": "torres_cunha",
        "extractor_version": "v1",
        "content_hash": content_hash,
        "supplier_name": "Torres & Cunha Peças Auto Lda.",
        "supplier_tax_id": "503699292",
        "invoice_number": invoice_number,
        "net_total": tax_match.group(1) if tax_match else None,
        "tax_total": tax_match.group(2) if tax_match else None,
        "gross_total": gross_total,
        "lines": parsed_lines,
    }


def parse_caetano_parts_invoice(lines: list[str], content_hash: str) -> dict[str, Any] | None:
    all_text = "\n".join(lines)
    invoice_number = _first_match(lines, r"JFM/(\d+/\d{4})")
    if not invoice_number or "Armazem | 1034" not in all_text:
        return None
    invoice_number = f"JFM/{invoice_number}"

    parsed_lines: list[dict[str, Any]] = []
    previous_text = ""
    for source_line in lines:
        parts = [part.strip() for part in source_line.split("|") if part.strip()]
        if len(parts) < 9 or parts[0].upper() != "PSA":
            if parts and len(parts) <= 4 and not re.search(r"\d", source_line):
                previous_text = " ".join(parts)
            continue
        location_index = next(
            (index for index, part in enumerate(parts) if part.lower() == "armazem"), -1
        )
        if location_index < 2 or location_index + 6 >= len(parts):
            continue
        quantity_match = re.fullmatch(r"(\d+[,.]\d+)([A-Za-z]+)", parts[location_index + 2])
        if not quantity_match:
            continue
        quantity = _decimal(quantity_match.group(1))
        unit_cost = _decimal(parts[location_index + 3])
        discount = _decimal(parts[location_index + 4]) / Decimal("100")
        line_value = _decimal(parts[location_index + 5])
        tax_rate = _decimal(parts[location_index + 6]) / Decimal("100")
        parsed_lines.append(
            {
                "line_number": len(parsed_lines) + 1,
                "supplier_ref": parts[1],
                "description": (" ".join(parts[2:location_index]).strip() or previous_text),
                "quantity": str(quantity),
                "unit": quantity_match.group(2).lower(),
                "unit_cost": str(unit_cost),
                "discount": str(discount),
                "eco_value": "0",
                "tax_rate": str(tax_rate),
                "line_total": str(_cent(line_value * (Decimal("1") + tax_rate))),
            }
        )
        previous_text = ""
    if not parsed_lines:
        raise StockDomainError("Não foram encontradas linhas na fatura Caetano Parts.")

    totals = next(
        (
            re.findall(r"\d+[,.]\d+", line)
            for line in lines
            if line.count("|") >= 5
            and len(re.findall(r"\d+[,.]\d+", line)) == 6
            and line.strip().startswith("0,00")
        ),
        [],
    )
    return {
        "extractor_name": "caetano_parts_jfm",
        "extractor_version": "v1",
        "content_hash": content_hash,
        "supplier_name": "Caetano Parts, LDA",
        "supplier_tax_id": "504639668",
        "invoice_number": invoice_number,
        "net_total": totals[2] if totals else None,
        "tax_total": totals[4] if totals else None,
        "gross_total": totals[5] if totals else None,
        "lines": parsed_lines,
    }


def parse_stock_invoice(lines: list[str], content_hash: str) -> dict[str, Any] | None:
    for parser in (
        parse_dispnal_invoice,
        parse_torres_cunha_invoice,
        parse_caetano_parts_invoice,
    ):
        if parsed := parser(lines, content_hash):
            return parsed
    return None


def _json_safe_extraction(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe_extraction(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_extraction(item) for item in value]
    return value


def extract_stock_invoice(db: Session, invoice_import: StockInvoiceImport) -> dict[str, Any]:
    document = db.get(Document, invoice_import.document_id)
    if not document:
        raise StockDomainError("Documento original inexistente.")
    path = _authorized_document_path(document)
    lines, content_hash = _pdf_lines(path)
    parsed = parse_stock_invoice(lines, content_hash)
    if not parsed:
        invoice_import.status = "needs_review"
        invoice_import.content_hash = content_hash
        invoice_import.extractor_name = "unsupported"
        invoice_import.extractor_version = "v1"
        invoice_import.error_details = (
            "Fornecedor/formato ainda não suportado; revisão manual necessária."
        )
        invoice_import.raw_extraction_json = {"content_hash": content_hash, "lines": lines}
        return invoice_import.raw_extraction_json
    invoice_import.content_hash = content_hash
    invoice_import.extractor_name = parsed["extractor_name"]
    invoice_import.extractor_version = parsed["extractor_version"]
    parsed = _json_safe_extraction(parsed)
    invoice_import.raw_extraction_json = parsed
    invoice_import.status = "needs_review"
    invoice_import.error_details = None
    return parsed
