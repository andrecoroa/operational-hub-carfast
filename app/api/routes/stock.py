from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select

from app.api.auth import CurrentUser, require_method_permission, require_permission
from app.api.deps import DbSession
from app.models.documents import Document
from app.models.stock import (
    StockArticle,
    StockArticleVehicleCompatibility,
    StockDeliveryDocument,
    StockDiscrepancy,
    StockInventoryCount,
    StockInventorySession,
    StockInvoiceImport,
    StockInvoiceLine,
    StockMovement,
    StockPurchaseOrder,
    StockPurchaseOrderLine,
    StockReceipt,
)
from app.schemas.stock import (
    StockArticleCreate,
    StockArticleVehicleCompatibilityCreate,
    StockCompatibilityDecision,
    StockConferenceAction,
    StockDiscrepancyRegularize,
    StockInventoryClose,
    StockInventoryConfirm,
    StockInventorySessionCreate,
    StockInvoiceImportCreate,
    StockInvoiceReview,
    StockMovementCreate,
    StockMovementRead,
    StockMovementReverse,
    StockPurchaseOrderCreate,
    StockReceiptCreate,
    StockWorkshopCompatibilityEvidence,
)
from app.services.audit import record_audit
from app.services.stock import (
    StockDomainError,
    apply_conference_action,
    conference_comparison,
    confirm_inventory_session,
    create_inventory_session,
    create_manual_movement,
    create_physical_receipt,
    create_purchase_order,
    create_vehicle_compatibility,
    decide_vehicle_compatibility,
    ensure_invoice_import,
    extract_stock_invoice,
    link_invoice_to_receipt,
    low_stock_rows,
    record_workshop_compatibility_evidence,
    regularize_discrepancy,
    reverse_movement,
    review_and_validate_invoice,
    save_inventory_counts,
    stock_balances,
)

router = APIRouter(
    prefix="/api/stock",
    tags=["stock"],
    dependencies=[Depends(require_method_permission("stock.read", "stock.operate"))],
)
StockManager = Annotated[object, Depends(require_permission("stock.manage"))]
StockOrderManager = Annotated[object, Depends(require_permission("stock.orders.manage"))]
StockInventoryCounter = Annotated[object, Depends(require_permission("stock.inventory.count"))]
StockInventoryConfirmer = Annotated[object, Depends(require_permission("stock.inventory.confirm"))]
StockCompatibilityManager = Annotated[
    object, Depends(require_permission("stock.compatibility.manage"))
]
StockConferenceOperator = Annotated[object, Depends(require_permission("stock.conference"))]


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


@router.get("/compatibilities")
def list_compatibilities(
    db: DbSession,
    article_id: int | None = None,
    status_filter: str = "",
):
    statement = select(StockArticleVehicleCompatibility).order_by(
        StockArticleVehicleCompatibility.created_at.desc(),
        StockArticleVehicleCompatibility.id.desc(),
    )
    if article_id:
        statement = statement.where(StockArticleVehicleCompatibility.article_id == article_id)
    if status_filter:
        statement = statement.where(StockArticleVehicleCompatibility.status == status_filter)
    return db.scalars(statement).all()


@router.post("/compatibilities", status_code=status.HTTP_201_CREATED)
def create_compatibility(
    payload: StockArticleVehicleCompatibilityCreate,
    db: DbSession,
    user: CurrentUser,
    _: StockCompatibilityManager,
):
    try:
        compatibility = create_vehicle_compatibility(db, command=payload, user_id=user.id)
        db.commit()
        db.refresh(compatibility)
    except StockDomainError as exc:
        db.rollback()
        raise _domain_error(exc) from exc
    return compatibility


@router.post("/compatibilities/workshop-evidence", status_code=status.HTTP_201_CREATED)
def create_workshop_compatibility_evidence(
    payload: StockWorkshopCompatibilityEvidence,
    db: DbSession,
    user: CurrentUser,
):
    try:
        compatibility = record_workshop_compatibility_evidence(db, command=payload, user_id=user.id)
        db.commit()
        db.refresh(compatibility)
    except StockDomainError as exc:
        db.rollback()
        raise _domain_error(exc) from exc
    return {
        "id": compatibility.id,
        "status": compatibility.status,
        "evidence_type": compatibility.evidence_type,
        "automatically_validated": False,
    }


@router.post("/compatibilities/{compatibility_id}/decision")
def decide_compatibility(
    compatibility_id: int,
    payload: StockCompatibilityDecision,
    db: DbSession,
    user: CurrentUser,
    _: StockCompatibilityManager,
):
    compatibility = db.get(StockArticleVehicleCompatibility, compatibility_id)
    if not compatibility:
        raise HTTPException(status_code=404, detail="Compatibilidade não encontrada.")
    try:
        decide_vehicle_compatibility(
            db,
            compatibility=compatibility,
            status=payload.status,
            reason=payload.reason,
            user_id=user.id,
        )
        db.commit()
    except StockDomainError as exc:
        db.rollback()
        raise _domain_error(exc) from exc
    return {"id": compatibility.id, "status": compatibility.status}


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


@router.get("/invoice-imports/{invoice_import_id}/comparison")
def get_invoice_comparison(invoice_import_id: int, db: DbSession):
    invoice_import = db.get(StockInvoiceImport, invoice_import_id)
    if not invoice_import:
        raise HTTPException(status_code=404, detail="Importação não encontrada.")
    comparison = conference_comparison(db, invoice_import)
    return {
        "invoice_import_id": invoice_import.id,
        "conference_status": invoice_import.conference_status,
        "order_count": comparison["order_count"],
        "receipt_count": comparison["receipt_count"],
        "order_total": comparison["order_total"],
        "invoice_total": comparison["invoice_total"],
        "total_divergent": comparison["total_divergent"],
        "has_divergence": comparison["has_divergence"],
        "lines": [
            {
                "invoice_line_id": row["line"].id,
                "supplier_ref": row["line"].supplier_ref,
                "description": row["line"].description,
                "ordered": row["ordered"],
                "received": row["received"],
                "invoiced": row["invoiced"],
                "divergent": row["divergent"],
            }
            for row in comparison["lines"]
        ],
    }


@router.post("/invoice-imports/{invoice_import_id}/conference")
def conference_invoice_import(
    invoice_import_id: int,
    payload: StockConferenceAction,
    db: DbSession,
    user: CurrentUser,
    _: StockConferenceOperator,
):
    invoice_import = db.get(StockInvoiceImport, invoice_import_id)
    if not invoice_import:
        raise HTTPException(status_code=404, detail="Importação não encontrada.")
    try:
        apply_conference_action(db, invoice_import=invoice_import, command=payload, user_id=user.id)
        db.commit()
    except StockDomainError as exc:
        db.rollback()
        raise _domain_error(exc) from exc
    return {
        "id": invoice_import.id,
        "conference_status": invoice_import.conference_status,
        "stock_changed": False,
    }


@router.post("/inventory-sessions", status_code=status.HTTP_201_CREATED)
def start_inventory_session(
    payload: StockInventorySessionCreate,
    db: DbSession,
    user: CurrentUser,
    _: StockInventoryCounter,
):
    try:
        inventory = create_inventory_session(db, command=payload, user_id=user.id)
        db.commit()
    except StockDomainError as exc:
        db.rollback()
        raise _domain_error(exc) from exc
    return {"id": inventory.id, "status": inventory.status, "location_id": inventory.location_id}


@router.get("/inventory-sessions/{inventory_id}")
def get_inventory_session(inventory_id: int, db: DbSession):
    inventory = db.get(StockInventorySession, inventory_id)
    if not inventory:
        raise HTTPException(status_code=404, detail="Sessão de inventário não encontrada.")
    rows = db.execute(
        select(StockInventoryCount, StockArticle)
        .join(StockArticle, StockArticle.id == StockInventoryCount.article_id)
        .where(StockInventoryCount.session_id == inventory.id)
        .order_by(StockArticle.internal_ref)
    ).all()
    reveal = inventory.status in {"review", "completed"}
    items = []
    for count, article in rows:
        item = {
            "article_id": article.id,
            "internal_ref": article.internal_ref,
            "name": article.name,
            "counted_quantity": count.counted_quantity,
        }
        if reveal:
            item.update(
                {
                    "expected_quantity": count.expected_snapshot,
                    "difference_quantity": (
                        count.counted_quantity - count.expected_snapshot
                        if count.counted_quantity is not None
                        else None
                    ),
                    "justification": count.justification,
                }
            )
        items.append(item)
    return {
        "id": inventory.id,
        "location_id": inventory.location_id,
        "status": inventory.status,
        "effective_date": inventory.effective_date,
        "items": items,
    }


@router.post("/inventory-sessions/{inventory_id}/counts")
def write_inventory_counts(
    inventory_id: int,
    payload: StockInventoryClose,
    db: DbSession,
    user: CurrentUser,
    _: StockInventoryCounter,
    close: bool = False,
):
    inventory = db.get(StockInventorySession, inventory_id)
    if not inventory:
        raise HTTPException(status_code=404, detail="Sessão de inventário não encontrada.")
    try:
        save_inventory_counts(
            db,
            inventory=inventory,
            counts={item.article_id: item.counted_quantity for item in payload.counts},
            user_id=user.id,
            close=close,
        )
        db.commit()
    except StockDomainError as exc:
        db.rollback()
        raise _domain_error(exc) from exc
    return {"id": inventory.id, "status": inventory.status}


@router.post("/inventory-sessions/{inventory_id}/confirm")
def confirm_inventory(
    inventory_id: int,
    payload: StockInventoryConfirm,
    db: DbSession,
    user: CurrentUser,
    _: StockInventoryConfirmer,
):
    inventory = db.get(StockInventorySession, inventory_id)
    if not inventory:
        raise HTTPException(status_code=404, detail="Sessão de inventário não encontrada.")
    try:
        confirm_inventory_session(db, inventory=inventory, command=payload, user_id=user.id)
        db.commit()
    except StockDomainError as exc:
        db.rollback()
        raise _domain_error(exc) from exc
    return {"id": inventory.id, "status": inventory.status}


@router.get("/purchase-orders")
def list_purchase_orders(
    db: DbSession,
    supplier_id: int | None = None,
    receiving_status: str = "",
):
    statement = select(StockPurchaseOrder).order_by(
        StockPurchaseOrder.effective_date.desc(), StockPurchaseOrder.id.desc()
    )
    if supplier_id:
        statement = statement.where(StockPurchaseOrder.supplier_id == supplier_id)
    if receiving_status:
        statement = statement.where(StockPurchaseOrder.receiving_status == receiving_status)
    return db.scalars(statement).all()


@router.post("/purchase-orders", status_code=status.HTTP_201_CREATED)
def create_stock_purchase_order(
    payload: StockPurchaseOrderCreate,
    db: DbSession,
    user: CurrentUser,
    _: StockOrderManager,
):
    try:
        order = create_purchase_order(db, command=payload, user_id=user.id)
        db.commit()
        db.refresh(order)
    except StockDomainError as exc:
        db.rollback()
        raise _domain_error(exc) from exc
    return {"id": order.id, "order_number": order.order_number, "version": order.version}


@router.get("/purchase-orders/{order_id}")
def get_purchase_order(order_id: int, db: DbSession):
    order = db.get(StockPurchaseOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Encomenda não encontrada.")
    lines = db.scalars(
        select(StockPurchaseOrderLine)
        .where(StockPurchaseOrderLine.purchase_order_id == order.id)
        .order_by(StockPurchaseOrderLine.line_number)
    ).all()
    return {
        "id": order.id,
        "order_number": order.order_number,
        "version": order.version,
        "supplier_id": order.supplier_id,
        "commercial_status": order.commercial_status,
        "receiving_status": order.receiving_status,
        "effective_date": order.effective_date,
        "lines": lines,
    }


@router.get("/pending-sources")
def pending_receipt_sources(supplier_id: int, db: DbSession):
    orders = db.scalars(
        select(StockPurchaseOrder)
        .where(
            StockPurchaseOrder.supplier_id == supplier_id,
            StockPurchaseOrder.receiving_status.in_({"pending", "partial"}),
            StockPurchaseOrder.commercial_status != "cancelled",
        )
        .order_by(StockPurchaseOrder.effective_date, StockPurchaseOrder.id)
    ).all()
    guides = db.scalars(
        select(StockDeliveryDocument)
        .where(
            StockDeliveryDocument.supplier_id == supplier_id,
            StockDeliveryDocument.status == "pending",
        )
        .order_by(StockDeliveryDocument.effective_date, StockDeliveryDocument.id)
    ).all()
    invoices = db.scalars(
        select(StockInvoiceImport)
        .where(
            StockInvoiceImport.supplier_id == supplier_id,
            StockInvoiceImport.conference_status.in_({"pending", "divergent"}),
        )
        .order_by(StockInvoiceImport.invoice_date, StockInvoiceImport.id)
    ).all()
    return {
        "supplier_id": supplier_id,
        "orders": [
            {
                "id": item.id,
                "reference": f"{item.order_number} v{item.version}",
                "receiving_status": item.receiving_status,
            }
            for item in orders
        ],
        "delivery_notes": [
            {"id": item.id, "reference": item.reference, "effective_date": item.effective_date}
            for item in guides
        ],
        "invoices": [
            {"id": item.id, "reference": item.invoice_number, "date": item.invoice_date}
            for item in invoices
        ],
    }


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


@router.post("/discrepancies/{discrepancy_id}/regularize")
def regularize_stock_discrepancy(
    discrepancy_id: int,
    payload: StockDiscrepancyRegularize,
    db: DbSession,
    user: CurrentUser,
    _: StockInventoryConfirmer,
):
    discrepancy = db.get(StockDiscrepancy, discrepancy_id)
    if not discrepancy:
        raise HTTPException(status_code=404, detail="Divergência não encontrada.")
    try:
        regularize_discrepancy(db, discrepancy=discrepancy, command=payload, user_id=user.id)
        db.commit()
    except StockDomainError as exc:
        db.rollback()
        raise _domain_error(exc) from exc
    return {
        "id": discrepancy.id,
        "status": discrepancy.status,
        "adjustment_movement_id": discrepancy.adjustment_movement_id,
    }
