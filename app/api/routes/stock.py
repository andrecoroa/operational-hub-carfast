from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select

from app.api.auth import CurrentUser, require_method_permission, require_permission
from app.api.deps import DbSession
from app.models.documents import Document
from app.models.stock import (
    StockArticle,
    StockInvoiceImport,
    StockInvoiceLine,
    StockMovement,
    StockReceipt,
)
from app.schemas.stock import (
    StockArticleCreate,
    StockInvoiceImportCreate,
    StockInvoiceReview,
    StockMovementCreate,
    StockMovementRead,
    StockMovementReverse,
    StockReceiptCreate,
)
from app.services.audit import record_audit
from app.services.stock import (
    StockDomainError,
    create_manual_movement,
    create_physical_receipt,
    ensure_invoice_import,
    extract_stock_invoice,
    link_invoice_to_receipt,
    low_stock_rows,
    reverse_movement,
    review_and_validate_invoice,
    stock_balances,
)

router = APIRouter(
    prefix="/api/stock",
    tags=["stock"],
    dependencies=[Depends(require_method_permission("stock.read", "stock.operate"))],
)
StockManager = Annotated[object, Depends(require_permission("stock.manage"))]


def _domain_error(exc: StockDomainError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.get("/articles")
def list_articles(
    db: DbSession,
    q: str = "",
    active: bool | None = True,
    low_stock: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
):
    statement = select(StockArticle).order_by(StockArticle.name, StockArticle.id).limit(limit)
    if active is not None:
        statement = statement.where(StockArticle.active.is_(active))
    if q.strip():
        token = f"%{q.strip()}%"
        statement = statement.where(
            or_(StockArticle.internal_ref.ilike(token), StockArticle.name.ilike(token))
        )
    if low_stock:
        low_stock_article_ids = {row["article"].id for row in low_stock_rows(db)}
        if not low_stock_article_ids:
            return []
        statement = statement.where(StockArticle.id.in_(low_stock_article_ids))
    articles = db.scalars(statement).all()
    balances = stock_balances(db, article_ids=[article.id for article in articles])
    return [
        {
            "id": article.id,
            "internal_ref": article.internal_ref,
            "name": article.name,
            "unit": article.unit,
            "category_id": article.category_id,
            "classification": article.classification,
            "average_cost": article.average_cost,
            "last_cost": article.last_cost,
            "active": article.active,
            "balances": {
                str(location_id): quantity
                for (article_id, location_id), quantity in balances.items()
                if article_id == article.id
            },
        }
        for article in articles
    ]


@router.post("/articles", status_code=status.HTTP_201_CREATED)
def create_article(payload: StockArticleCreate, db: DbSession, user: CurrentUser):
    if db.scalar(
        select(StockArticle).where(StockArticle.internal_ref == payload.internal_ref.strip())
    ):
        raise HTTPException(status_code=409, detail="A referência interna já existe.")
    article = StockArticle(**payload.model_dump())
    article.internal_ref = article.internal_ref.strip()
    article.name = article.name.strip()
    db.add(article)
    db.flush()
    record_audit(
        db,
        action="stock.article.created",
        entity_type="stock_article",
        entity_id=article.id,
        user_id=user.id,
        after_json=payload.model_dump(mode="json"),
    )
    db.commit()
    return {"id": article.id, "internal_ref": article.internal_ref, "name": article.name}


@router.post("/invoice-imports")
def create_invoice_import(payload: StockInvoiceImportCreate, db: DbSession, user: CurrentUser):
    document = db.get(Document, payload.document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Documento não encontrado.")
    invoice_import = ensure_invoice_import(
        db,
        document=document,
        extracted_data=payload.extracted_data,
        user_id=user.id,
    )
    db.commit()
    return {
        "id": invoice_import.id,
        "document_id": invoice_import.document_id,
        "status": invoice_import.status,
        "stock_changed": False,
    }


@router.get("/invoice-imports/{invoice_import_id}")
def get_invoice_import(invoice_import_id: int, db: DbSession):
    invoice_import = db.get(StockInvoiceImport, invoice_import_id)
    if not invoice_import:
        raise HTTPException(status_code=404, detail="Importação não encontrada.")
    lines = db.scalars(
        select(StockInvoiceLine)
        .where(StockInvoiceLine.invoice_import_id == invoice_import.id)
        .order_by(StockInvoiceLine.line_number)
    ).all()
    return {
        "id": invoice_import.id,
        "document_id": invoice_import.document_id,
        "supplier_id": invoice_import.supplier_id,
        "invoice_number": invoice_import.invoice_number,
        "status": invoice_import.status,
        "error_details": invoice_import.error_details,
        "raw_extraction": invoice_import.raw_extraction_json,
        "lines": [
            {
                "id": line.id,
                "line_number": line.line_number,
                "article_id": line.article_id,
                "supplier_ref": line.supplier_ref,
                "description": line.description,
                "quantity": line.quantity,
                "unit": line.unit,
                "unit_cost": line.unit_cost,
                "discount": line.discount,
                "eco_value": line.eco_value,
                "tax_rate": line.tax_rate,
                "line_total": line.line_total,
            }
            for line in lines
        ],
    }


@router.post("/invoice-imports/{invoice_import_id}/extract")
def extract_invoice_import(invoice_import_id: int, db: DbSession):
    invoice_import = db.get(StockInvoiceImport, invoice_import_id)
    if not invoice_import:
        raise HTTPException(status_code=404, detail="Importação não encontrada.")
    try:
        extracted = extract_stock_invoice(db, invoice_import)
    except StockDomainError as exc:
        raise _domain_error(exc) from exc
    db.commit()
    return extracted


@router.post("/invoice-imports/{invoice_import_id}/validate")
def validate_invoice_import(
    invoice_import_id: int,
    payload: StockInvoiceReview,
    db: DbSession,
    user: CurrentUser,
):
    invoice_import = db.get(StockInvoiceImport, invoice_import_id)
    if not invoice_import:
        raise HTTPException(status_code=404, detail="Importação não encontrada.")
    try:
        review_and_validate_invoice(
            db,
            invoice_import=invoice_import,
            review=payload,
            user_id=user.id,
        )
        db.commit()
    except StockDomainError as exc:
        db.commit()
        raise _domain_error(exc) from exc
    return {"id": invoice_import.id, "status": invoice_import.status, "stock_changed": False}


@router.get("/receipts")
def list_receipts(db: DbSession, limit: int = Query(default=100, ge=1, le=500)):
    receipts = db.scalars(
        select(StockReceipt)
        .order_by(StockReceipt.confirmed_at.desc(), StockReceipt.id.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": receipt.id,
            "supplier_id": receipt.supplier_id,
            "location_id": receipt.location_id,
            "source_type": receipt.source_type,
            "source_reference": receipt.source_reference,
            "status": receipt.status,
            "confirmed_at": receipt.confirmed_at,
        }
        for receipt in receipts
    ]


@router.post("/receipts", status_code=status.HTTP_201_CREATED)
def create_receipt(
    payload: StockReceiptCreate,
    db: DbSession,
    user: CurrentUser,
):
    try:
        receipt = create_physical_receipt(
            db,
            command=payload,
            user_id=user.id,
        )
        db.commit()
    except StockDomainError as exc:
        db.rollback()
        raise _domain_error(exc) from exc
    return {"id": receipt.id, "status": receipt.status, "location_id": receipt.location_id}


@router.post("/receipts/{receipt_id}/invoice-links/{invoice_import_id}")
def link_receipt_invoice(
    receipt_id: int,
    invoice_import_id: int,
    db: DbSession,
    user: CurrentUser,
):
    receipt = db.get(StockReceipt, receipt_id)
    invoice_import = db.get(StockInvoiceImport, invoice_import_id)
    if not receipt or not invoice_import:
        raise HTTPException(status_code=404, detail="Receção ou fatura não encontrada.")
    link = link_invoice_to_receipt(
        db,
        receipt=receipt,
        invoice_import=invoice_import,
        user_id=user.id,
    )
    db.commit()
    return {
        "id": link.id,
        "receipt_id": link.receipt_id,
        "invoice_import_id": link.invoice_import_id,
        "stock_changed": False,
    }


@router.get("/movements", response_model=list[StockMovementRead])
def list_movements(db: DbSession, limit: int = Query(default=100, ge=1, le=500)):
    return db.scalars(
        select(StockMovement)
        .order_by(StockMovement.occurred_at.desc(), StockMovement.id.desc())
        .limit(limit)
    ).all()


@router.post("/movements", response_model=StockMovementRead, status_code=status.HTTP_201_CREATED)
def create_movement(payload: StockMovementCreate, db: DbSession, user: CurrentUser):
    try:
        movement = create_manual_movement(db, command=payload, user_id=user.id)
        db.commit()
        db.refresh(movement)
    except StockDomainError as exc:
        db.rollback()
        raise _domain_error(exc) from exc
    return movement


@router.post("/movements/{movement_id}/reverse", response_model=StockMovementRead)
def reverse_stock_movement(
    movement_id: int,
    payload: StockMovementReverse,
    db: DbSession,
    user: CurrentUser,
    _: StockManager,
):
    movement = db.get(StockMovement, movement_id)
    if not movement:
        raise HTTPException(status_code=404, detail="Movimento não encontrado.")
    try:
        reversal = reverse_movement(db, movement=movement, reason=payload.reason, user_id=user.id)
        db.commit()
        db.refresh(reversal)
    except StockDomainError as exc:
        db.rollback()
        raise _domain_error(exc) from exc
    return reversal
