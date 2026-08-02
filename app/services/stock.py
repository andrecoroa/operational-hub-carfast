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
from app.models.documents import Document, DocumentEvent
from app.models.stock import (
    StockArticle,
    StockArticleSupplierRef,
    StockCategory,
    StockInvoiceImport,
    StockInvoiceLine,
    StockLocation,
    StockMinimum,
    StockMovement,
    StockReceipt,
    StockReceiptInvoiceLink,
    StockReceiptLine,
    StockSupplier,
)
from app.schemas.stock import (
    StockInvoiceLineReview,
    StockInvoiceReview,
    StockMovementCreate,
    StockReceiptCreate,
)
from app.services.audit import record_audit

ZERO = Decimal("0")
CENT = Decimal("0.01")
QUANTITY_STEP = Decimal("0.001")
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
    return value.quantize(QUANTITY_STEP, rounding=ROUND_HALF_UP)


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
    for line in review.lines:
        net, tax, gross = _line_amounts(line)
        calculated_net += net
        calculated_tax += tax
        calculated_gross += gross
        if line.line_total is not None and abs(line.line_total - gross) > Decimal("0.02"):
            invoice_import.status = "needs_review"
            invoice_import.error_details = (
                f"Total divergente na linha {line.line_number}: "
                f"calculado {_cent(gross)} / indicado {_cent(line.line_total)}."
            )
            raise StockDomainError(invoice_import.error_details)
    calculated_net = _cent(calculated_net)
    calculated_tax = _cent(calculated_tax)
    calculated_gross = _cent(calculated_gross)
    expected = (
        ("líquido", review.net_total, calculated_net),
        ("IVA", review.tax_total, calculated_tax),
        ("total", review.gross_total, calculated_gross),
    )
    divergences = [
        f"{label}: calculado {computed} / documento {document_total}"
        for label, document_total, computed in expected
        if document_total is not None and abs(document_total - computed) > Decimal("0.02")
    ]
    if divergences:
        invoice_import.status = "needs_review"
        invoice_import.error_details = "Totais divergentes — " + "; ".join(divergences)
        raise StockDomainError(invoice_import.error_details)

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
    invoice_import.error_details = None
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
    responsible_name = (command.responsible_name or "").strip() or None
    if location.code == "AIRPORT" and not responsible_name:
        raise StockDomainError("A receção no Aeroporto exige um responsável identificado.")
    invoice_imports = []
    for invoice_import_id in dict.fromkeys(command.invoice_import_ids):
        invoice_import = db.get(StockInvoiceImport, invoice_import_id)
        if not invoice_import:
            raise StockDomainError(f"Fatura documental {invoice_import_id} inexistente.")
        invoice_imports.append(invoice_import)

    receipt = StockReceipt(
        supplier_id=supplier.id if supplier else None,
        location_id=location.id,
        source_type=command.source_type,
        source_reference=(command.source_reference or "").strip() or None,
        idempotency_key=(command.idempotency_key or "").strip() or None,
        status="completed",
        confirmed_by_id=user_id,
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
        )
        db.add(movement)
        db.flush()
    for invoice_import in invoice_imports:
        link_invoice_to_receipt(
            db,
            receipt=receipt,
            invoice_import=invoice_import,
            user_id=user_id,
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
    is_dispnal = re.search(r"Dispnal\s*\|?\s*Pneus", all_text, re.IGNORECASE)
    if not is_dispnal or "504670409" not in all_text:
        return None
    invoice_number = _first_match(lines, r"N\.º\s*\|?\s*(\d+/\d{4})")
    if not invoice_number:
        raise StockDomainError("Número da fatura Dispnal não encontrado.")
    parsed_lines: list[dict[str, Any]] = []
    for source_line in lines:
        parts = [part.strip() for part in source_line.split("|") if part.strip()]
        if not parts or not re.fullmatch(r"[A-Z0-9]{8,20}", parts[0]):
            continue
        quantity_index = next(
            (
                index
                for index, part in enumerate(parts[:-1])
                if re.fullmatch(r"\d+[,.]\d+", part) and parts[index + 1].upper() == "UN"
            ),
            -1,
        )
        if quantity_index < 2 or len(parts) < quantity_index + 7:
            continue
        description = " ".join(parts[1:quantity_index]).strip()
        quantity = _decimal(parts[quantity_index])
        unit_cost = _decimal(parts[quantity_index + 2])
        discount = _decimal(parts[quantity_index + 3]) / Decimal("100")
        eco_value = _decimal(parts[quantity_index + 4])
        tax_rate = _decimal(parts[quantity_index + 5]) / Decimal("100")
        goods_value = _decimal(parts[quantity_index + 6])
        base = _cent(goods_value + (quantity * eco_value))
        line_total = _cent(base + (base * tax_rate))
        parsed_lines.append(
            {
                "line_number": len(parsed_lines) + 1,
                "supplier_ref": parts[0],
                "description": description,
                "quantity": str(quantity),
                "unit": "un.",
                "unit_cost": str(unit_cost),
                "discount": str(discount),
                "eco_value": str(eco_value),
                "tax_rate": str(tax_rate),
                "line_total": str(line_total),
            }
        )
    if not parsed_lines:
        raise StockDomainError("Não foram encontradas linhas de artigos na fatura Dispnal.")
    return {
        "extractor_name": "dispnal",
        "extractor_version": "v1",
        "content_hash": content_hash,
        "supplier_name": "Dispnal Pneus, S.A.",
        "supplier_tax_id": "504670409",
        "invoice_number": invoice_number,
        "net_total": _first_match(lines, r"IVA\s*\|\s*\(23[,.]00\)\s*\|\s*([\d.,]+)"),
        "tax_total": _first_match(
            lines,
            r"IVA\s*\|\s*\(23[,.]00\)\s*\|\s*[\d.,]+\s*\|\s*([\d.,]+)",
        ),
        "gross_total": _joined_amount(lines, r"Total\s*\|\s*\(\s*\|\s*EUR\s*\|\s*\)\s*\|"),
        "lines": parsed_lines,
    }


def _document_copy(lines: list[str], marker: str) -> list[str]:
    """Keep the first logical copy when a PDF contains ORIGINAL and DUPLICADO."""
    stop = next(
        (index for index, line in enumerate(lines) if index and marker.lower() in line.lower()),
        len(lines),
    )
    return lines[:stop]


def parse_torres_cunha_invoice(
    lines: list[str], content_hash: str
) -> dict[str, Any] | None:
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


def parse_caetano_parts_invoice(
    lines: list[str], content_hash: str
) -> dict[str, Any] | None:
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
                "description": (
                    " ".join(parts[2:location_index]).strip() or previous_text
                ),
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
